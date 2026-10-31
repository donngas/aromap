// Predicts the backend's automatic grid (backend/app/simulations/resolution.py)
// and how long a run takes, before submitting. Mirrors the backend so the
// workspace can show the real cell size and a realistic time estimate.

import { distance, metersPerPixel, pointInDomain, polygonArea } from '../floorPlan/geometry.ts'
import type { PixelPoint } from '../floorPlan/layout.ts'
import type { ProjectDocument, Scenario } from '../project/types.ts'

/** Backend DEFAULT_CELL_SIZE_M and PreparationLimits. */
export const BASE_CELL_M = 0.25
const MAX_CELL_M = 1.0
const MAX_CELLS = 100_000
const MAX_SAMPLES = 600
const MAX_OUTPUT_BYTES = 256 * 1024 * 1024
/** Backend DEFAULT_SAMPLE_INTERVAL_S: automatic output every 30 s. */
const SAMPLE_INTERVAL_S = 30
/** Backend resolution.TARGET_CELL_COUNT (raised from 6,000 in backend PR #27). */
const TARGET_CELL_COUNT = 10_000

/** Backend ExecutionLimits.max_runtime_s: longer runs are stopped. */
export const MAX_RUN_SECONDS = 120

/** Number of output snapshots with automatic sampling. */
function sampleCount(durationS: number): number {
  const count = Math.ceil(durationS / Math.min(SAMPLE_INTERVAL_S, durationS)) + 1
  return Math.min(count, MAX_SAMPLES)
}

/**
 * Cell side in meters the backend picks when the request leaves it out:
 * 25 cm, coarser for large spaces, many diffusers or long runs, but kept at
 * two cells across each open door or window. The backend also keeps the
 * footprint from splitting apart; that check can only make cells smaller.
 */
export function predictCellSize(
  bounds: { width: number; height: number },
  channels: number,
  durationS: number,
  openWidthsM: number[],
): number {
  const p = Math.max(1, channels)
  let target = (TARGET_CELL_COUNT / Math.sqrt(p)) * Math.min(1, Math.sqrt(3600 / durationS))
  target = Math.min(target, MAX_CELLS, MAX_OUTPUT_BYTES / (4 * p * sampleCount(durationS) + 1))
  const desired = Math.sqrt((bounds.width * bounds.height) / Math.max(1, target))
  let cell = Math.min(MAX_CELL_M, Math.max(BASE_CELL_M, Math.ceil(desired / 0.05) * 0.05))
  for (const width of openWidthsM) {
    cell = Math.min(cell, Math.max(BASE_CELL_M, Math.floor((width / 2 + 1e-9) / 0.05) * 0.05))
  }
  return Math.round(cell * 1e10) / 1e10
}

/** Predicted cell size for the scenario as it stands, or null before space setup. */
export function scenarioCellSize(project: ProjectDocument, scenario: Scenario): number | null {
  const { calibration, indoor } = project
  const layout = project.recognition?.layout
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null
  if (!mpp || !indoor || !layout) return null
  const xs = indoor.boundary.map((p) => p.x)
  const ys = indoor.boundary.map((p) => p.y)
  const bounds = { width: (Math.max(...xs) - Math.min(...xs)) * mpp, height: (Math.max(...ys) - Math.min(...ys)) * mpp }
  const open = new Set(scenario.opening_states.filter((s) => s.is_open).map((s) => s.opening_id))
  const openWidths = [...layout.doors, ...layout.windows]
    .filter((o) => open.has(o.id))
    .map((o) => distance(o.start, o.end) * mpp)
  const channels = scenario.placements.filter((p) => p.enabled).length
  let cell = predictCellSize(bounds, channels, project.simulationHours * 3600, openWidths)

  // Like the backend, refine (0.05 m at a time) while a diffuser would land in
  // a cell whose centre is outdoors or behind a wall from it, or a fan/AC in a
  // cell whose centre is outdoors (devices get no wall check there).
  const originX = Math.min(...xs)
  const originY = Math.min(...ys)
  const centerOf = (p: PixelPoint, cellPx: number): PixelPoint => ({
    x: originX + (Math.floor((p.x - originX) / cellPx) + 0.5) * cellPx,
    y: originY + (Math.floor((p.y - originY) / cellPx) + 0.5) * cellPx,
  })
  const indoorCenter = (c: PixelPoint) => pointInDomain(c, indoor.boundary, indoor.holes)
  const sources = scenario.placements.filter((p) => p.enabled).map((p) => p.position)
  const devices = scenario.airflow_devices.map((d) => d.position)
  const resolved = (cellPx: number) =>
    sources.every((p) => {
      const c = centerOf(p, cellPx)
      return indoorCenter(c) && !layout.walls.some((w) => segmentsCross(p, c, w.start, w.end))
    }) && devices.every((p) => indoorCenter(centerOf(p, cellPx)))
  while (cell > BASE_CELL_M + 1e-9 && !resolved(cell / mpp)) {
    cell = Math.max(BASE_CELL_M, Math.round((cell - 0.05) * 1e10) / 1e10)
  }
  return cell
}

/** Whether segments ab and cd cross or touch. */
function segmentsCross(a: PixelPoint, b: PixelPoint, c: PixelPoint, d: PixelPoint): boolean {
  const cross = (p: PixelPoint, q: PixelPoint, r: PixelPoint) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)
  const d1 = cross(c, d, a)
  const d2 = cross(c, d, b)
  const d3 = cross(a, b, c)
  const d4 = cross(a, b, d)
  return ((d1 > 0) !== (d2 > 0) || d1 === 0 || d2 === 0) && ((d3 > 0) !== (d4 > 0) || d3 === 0 || d4 === 0)
}

/**
 * Measured on the Docker backend after the solver update (2026-11-01): each
 * solver step costs about STEP_CELL seconds per cell plus STEP_CELL_CHANNEL
 * per cell and diffuser. Steps are 2 s, shortened with fans and ACs to keep
 * air moving at most 0.2 cells per step; their peak speed after balancing
 * came out near 45% of the preset. JOB_OVERHEAD covers process start, writing
 * and downloading the result. A rough guide; it depends on the machine.
 */
const STEP_CELL = 4.3e-8
const STEP_CELL_CHANNEL = 2.05e-8
const MAX_STEP_S = 2
const STARTUP_STEPS = 16
const JOB_OVERHEAD_S = 1.5
/** Backend airflow DEVICE_SPEEDS (m/s). */
const DEVICE_SPEEDS = {
  fan: { low: 0.08, medium: 0.16, high: 0.28 },
  ac: { low: 0.1, medium: 0.2, high: 0.35 },
} as const
const BALANCED_PEAK_SHARE = 0.45

/** Rough job time in seconds, or null before space setup is done. */
export function estimateRunSeconds(project: ProjectDocument, scenario: Scenario): number | null {
  const cell = scenarioCellSize(project, scenario)
  const { calibration, indoor } = project
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null
  if (cell === null || !mpp || !indoor) return null
  const areaM2 = (polygonArea(indoor.boundary) - indoor.holes.reduce((sum, h) => sum + polygonArea(h), 0)) * mpp * mpp
  const cells = areaM2 / (cell * cell)
  const channels = Math.max(1, scenario.placements.filter((p) => p.enabled).length)
  const speed = Math.max(0, ...scenario.airflow_devices.map((d) => DEVICE_SPEEDS[d.type][d.strength] * BALANCED_PEAK_SHARE))
  const step = speed > 0 ? Math.min(MAX_STEP_S, (0.2 * cell) / speed) : MAX_STEP_S
  const steps = (project.simulationHours * 3600) / step + STARTUP_STEPS
  return JOB_OVERHEAD_S + steps * cells * (STEP_CELL + STEP_CELL_CHANNEL * channels)
}
