// Builds one backend SimulationRequest from the project's active scenario:
// pixel geometry is converted to meters with the wall calibration, and walls
// are fitted to the indoor outline the way backend preparation requires
// (every wall covered by the indoor domain; backend simulations/geometry.py).

import type {
  ConsumerDiffuserDefinition,
  MetricOpening,
  MetricPoint,
  MetricSegment,
  SimulationRequest,
} from '../api/simulations.ts'
import { EXAMPLE_SPECS } from '../diffusers/emission.ts'
import { INTENSITY_LABELS, TYPE_INFO, type DiffuserDraft, type DiffuserType } from '../diffusers/types.ts'
import {
  distance,
  distanceToRings,
  metersPerPixel,
  pointInDomain,
  polygonArea,
  ringCrossings,
} from '../floorPlan/geometry.ts'
import type { Opening, PixelPoint, Wall } from '../floorPlan/layout.ts'
import type { ProjectDocument, Scenario } from '../project/types.ts'

/** Backend PreparationLimits.max_placements. */
export const MAX_PLACEMENTS = 16

/** Pixels within which a point counts as lying on the indoor outline. */
const ON_OUTLINE_PX = 1e-6
/** Wall ends on the outline are pulled this far inside, so they are covered despite rounding. */
const PULL_INSIDE_PX = 0.05
/** Openings shorter than this after fitting are dropped. */
const MIN_OPENING_PX = 0.5

/**
 * Backend diffuser types: reed is passive; nebulizers consume their oil like
 * other electric diffusers. Ultrasonic tanks (water mixed with oil) and candles
 * have no usable-refill model yet, so the backend falls back to its reference rate.
 */
const BACKEND_TYPES: Record<DiffuserType, string> = {
  reed: 'reed',
  ultrasonic: 'ultrasonic',
  nebulizer: 'electric_diffuser',
  candle: 'candle',
}

export type BuildResult = { ok: true; request: SimulationRequest; key: string } | { ok: false; problems: string[] }

export function buildSimulationRequest(project: ProjectDocument, scenario: Scenario): BuildResult {
  const layout = project.recognition?.layout
  const { calibration, indoor } = project
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null
  if (!layout || !indoor || !mpp) return { ok: false, problems: ['공간 설정을 먼저 마쳐 주세요.'] }

  const problems: string[] = []
  const placements = scenario.placements.filter((p) => p.enabled)
  if (placements.length === 0) problems.push('디퓨저를 하나 이상 놓아 주세요.')
  if (placements.length > MAX_PLACEMENTS) problems.push(`디퓨저는 ${MAX_PLACEMENTS}개까지 놓을 수 있어요.`)
  const products = new Map(project.diffusers.map((d) => [d.id, d]))
  scenario.placements.forEach((p, i) => {
    if (!p.enabled) return
    if (!products.has(p.definition_id)) problems.push(`${i + 1}번 디퓨저의 제품 정보가 지워졌어요. 다시 놓아 주세요.`)
    if (!pointInDomain(p.position, indoor.boundary, indoor.holes)) problems.push(`${i + 1}번 디퓨저가 실내 영역 밖에 있어요.`)
  })
  if (problems.length > 0) return { ok: false, problems }

  const toMeters = (p: PixelPoint): MetricPoint => ({ x: p.x * mpp, y: p.y * mpp })
  const { walls, doors, windows } = fitToOutline(layout.walls, layout.doors, layout.windows, indoor.boundary, indoor.holes)
  const segment = (s: { id: string; start: PixelPoint; end: PixelPoint }): MetricSegment => ({
    id: s.id,
    start: toMeters(s.start),
    end: toMeters(s.end),
  })
  const opening = (o: Opening): MetricOpening => ({ ...segment(o), wall_id: o.wall_id })

  const usedProducts = [...new Set(placements.map((p) => p.definition_id))].map((id) => products.get(id)!)
  // Windows always stay closed: the backend does not model open windows yet.
  const doorIds = new Set(doors.map((d) => d.id))
  const openDoors = new Set(scenario.opening_states.filter((s) => s.is_open).map((s) => s.opening_id))

  const body: Omit<SimulationRequest, 'client_request_id'> = {
    geometry_m: {
      indoor_domain: { boundary: indoor.boundary.map(toMeters), holes: indoor.holes.map((h) => h.map(toMeters)) },
      walls: walls.map(segment),
      doors: doors.map(opening),
      windows: windows.map(opening),
    },
    diffuser_definitions: usedProducts.map(toDefinition),
    placements: placements.map((p) => ({
      placement_id: p.id,
      definition_id: p.definition_id,
      position_m: toMeters(p.position),
      ...(p.strength_override !== null ? { strength_override: p.strength_override } : {}),
      enabled: true,
    })),
    opening_states: [...doorIds].map((id) => ({ opening_id: id, is_open: openDoors.has(id) })),
    settings: { duration_s: project.simulationHours * 3600 },
  }
  // The key identifies the configuration, to tell whether a result is out of date.
  const key = JSON.stringify(body)
  return { ok: true, request: { client_request_id: crypto.randomUUID(), ...body }, key }
}

/** Backend ExecutionLimits.max_runtime_s: longer runs are stopped. */
export const MAX_RUN_SECONDS = 120
/** Backend default cell side, in meters. */
const CELL_M = 0.25
/**
 * Measured on the Docker backend (2026-11-01): solving costs about this many
 * seconds per grid cell, per diffuser, per simulated hour. A rough guide only;
 * it depends on the machine.
 */
const SECONDS_PER_CELL_CHANNEL_HOUR = 6e-4

/** Rough solver time in seconds, or null before space setup is done. */
export function estimateRunSeconds(project: ProjectDocument, scenario: Scenario): number | null {
  const { calibration, indoor } = project
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null
  if (!mpp || !indoor) return null
  const areaM2 = (polygonArea(indoor.boundary) - indoor.holes.reduce((sum, h) => sum + polygonArea(h), 0)) * mpp * mpp
  const cells = areaM2 / (CELL_M * CELL_M)
  const channels = Math.max(1, scenario.placements.filter((p) => p.enabled).length)
  return cells * channels * project.simulationHours * SECONDS_PER_CELL_CHANNEL_HOUR
}

function toDefinition(d: DiffuserDraft): ConsumerDiffuserDefinition {
  const info = TYPE_INFO[d.type]
  const spec = d.usesExampleValues ? EXAMPLE_SPECS[d.type] : { volume: d.volume, durationDays: d.durationDays }
  return {
    id: d.id,
    name: d.name.trim() || info.label,
    diffuser_type: BACKEND_TYPES[d.type],
    ...(spec.volume ? { capacity: spec.volume, capacity_unit: info.unit } : {}),
    ...(spec.durationDays ? { lifetime_days: spec.durationDays } : {}),
    ...(info.timed && d.dailyHours ? { operating_hours_per_day: d.dailyHours } : {}),
    ...(d.intensity ? { intensity: INTENSITY_LABELS[d.intensity] } : {}),
    provenance: d.usesExampleValues ? 'example' : 'user',
  }
}

interface Piece {
  id: string
  wall: Wall
  /** Range along the original wall, 0 at its start and 1 at its end. */
  from: number
  to: number
}

/**
 * The backend needs every wall inside the indoor outline (its edge counts).
 * Walls are cut where they cross the outline; parts outside are dropped, and so
 * are parts lying along the outline, which already bounds the space. Ends that
 * touch the outline are pulled slightly inside so rounding never puts them out.
 * Doors and windows follow their wall's remaining part.
 */
function fitToOutline(
  walls: Wall[],
  doors: Opening[],
  windows: Opening[],
  boundary: PixelPoint[],
  holes: PixelPoint[][],
): { walls: Wall[]; doors: Opening[]; windows: Opening[] } {
  const rings = [boundary, ...holes]
  const at = (wall: Wall, t: number): PixelPoint => ({
    x: wall.start.x + (wall.end.x - wall.start.x) * t,
    y: wall.start.y + (wall.end.y - wall.start.y) * t,
  })
  const onOutline = (p: PixelPoint) => distanceToRings(p, rings) <= ON_OUTLINE_PX

  const piecesByWall = new Map<string, Piece[]>()
  const fitted: Wall[] = []
  for (const wall of walls) {
    const length = distance(wall.start, wall.end)
    if (length === 0) continue
    const cuts = [0, ...ringCrossings(wall.start, wall.end, rings).sort((a, b) => a - b), 1]
    // Keep the parts strictly inside, merging neighbours split only by a touch.
    const kept: [number, number][] = []
    for (let i = 0; i < cuts.length - 1; i++) {
      const [a, b] = [cuts[i], cuts[i + 1]]
      if (b - a <= 1e-9) continue
      const mid = at(wall, (a + b) / 2)
      if (onOutline(mid) || !pointInDomain(mid, boundary, holes)) continue
      const last = kept[kept.length - 1]
      if (last && Math.abs(last[1] - a) <= 1e-9) last[1] = b
      else kept.push([a, b])
    }

    const pull = Math.min(PULL_INSIDE_PX, length * 0.01) / length
    const pieces: Piece[] = kept.map(([a, b], i) => ({
      id: kept.length === 1 && a === 0 && b === 1 ? wall.id : `${wall.id}~${i + 1}`,
      wall,
      from: onOutline(at(wall, a)) ? a + pull : a,
      to: onOutline(at(wall, b)) ? b - pull : b,
    }))
    // A pulled end changes the wall, so it gets its own id too.
    for (const piece of pieces) {
      if (piece.id === wall.id && (piece.from !== 0 || piece.to !== 1)) piece.id = `${wall.id}~1`
      fitted.push({ id: piece.id, start: at(wall, piece.from), end: at(wall, piece.to) })
    }
    piecesByWall.set(wall.id, pieces)
  }

  const fitOpening = (o: Opening): Opening | null => {
    const pieces = piecesByWall.get(o.wall_id)
    if (!pieces || pieces.length === 0) return null
    const wall = pieces[0].wall
    const length = distance(wall.start, wall.end)
    const param = (p: PixelPoint) =>
      ((p.x - wall.start.x) * (wall.end.x - wall.start.x) + (p.y - wall.start.y) * (wall.end.y - wall.start.y)) /
      (length * length)
    const a = Math.min(param(o.start), param(o.end))
    const b = Math.max(param(o.start), param(o.end))
    let best: { piece: Piece; from: number; to: number } | null = null
    for (const piece of pieces) {
      const from = Math.max(a, piece.from)
      const to = Math.min(b, piece.to)
      if (to > from && (!best || to - from > best.to - best.from)) best = { piece, from, to }
    }
    if (!best || (best.to - best.from) * length < MIN_OPENING_PX) return null
    return { id: o.id, wall_id: best.piece.id, start: at(wall, best.from), end: at(wall, best.to) }
  }

  return {
    walls: fitted,
    doors: doors.map(fitOpening).filter((o): o is Opening => o !== null),
    windows: windows.map(fitOpening).filter((o): o is Opening => o !== null),
  }
}
