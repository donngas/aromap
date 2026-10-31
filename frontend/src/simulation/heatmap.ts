// Draws one time step of the simulated field over the floor plan, one flat
// colour per 25 cm grid cell. Colour never crosses a wall: the plan is split
// into rooms by its closed walls (open doors and windows are gaps), and every
// pixel takes the value of the nearest cell whose centre lies in the same room. This is
// the backend's own rule: a cell belongs where its centre is, and cells only
// exchange scent when the line between their centres crosses no wall.

import { scentShade, type Rgb } from '../diffusers/scents.ts'
import type { Layout, PixelPoint } from '../floorPlan/layout.ts'
import type { SimulationField } from './run.ts'

/** Strength of the log scale; concentrations fall off steeply from a source. */
const LOG_K = 40
const MAX_ALPHA = 0.72
/** Longest side of the room raster, in pixels. */
const RASTER_MAX = 1200

/** For each raster pixel, the grid cell whose colour it shows (-1: none). */
export interface CellMap {
  width: number
  height: number
  source: Int32Array
}

export interface CellMapInput {
  layout: Layout
  openOpeningIds: ReadonlySet<string>
  boundary: PixelPoint[]
  holes: PixelPoint[][]
  field: SimulationField
  /** Meters per image pixel when the run was made. */
  mpp: number
}

export function buildCellMap({ layout, openOpeningIds, boundary, holes, field, mpp }: CellMapInput): CellMap {
  const s = Math.min(1, RASTER_MAX / Math.max(layout.width_px, layout.height_px))
  const width = Math.ceil(layout.width_px * s)
  const height = Math.ceil(layout.height_px * s)
  const region = labelRooms(layout, openOpeningIds, boundary, holes, s, width, height)

  const { grid, mask } = field
  const { rows, columns, cell_size_m: cell } = grid
  const cellPx = cell / mpp
  const originX = grid.origin_m.x / mpp
  const originY = grid.origin_m.y / mpp

  // Room of each cell centre; -1 when inactive or right on a wall.
  const cellRoom = new Int32Array(rows * columns).fill(-1)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < columns; c++) {
      const i = r * columns + c
      if (!mask[i]) continue
      const x = Math.floor((originX + (c + 0.5) * cellPx) * s)
      const y = Math.floor((originY + (r + 0.5) * cellPx) * s)
      if (x >= 0 && y >= 0 && x < width && y < height) cellRoom[i] = region[y * width + x]
    }
  }

  const source = new Int32Array(width * height).fill(-1)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = y * width + x
      const room = region[p]
      if (room < 0) continue
      // Position in cell units.
      const u = ((x + 0.5) / s - originX) / cellPx
      const v = ((y + 0.5) / s - originY) / cellPx
      const c0 = Math.floor(u)
      const r0 = Math.floor(v)
      let best = -1
      let bestDistance = Infinity
      // Nearest centre in the same room: the containing cell when its centre
      // is in this room, otherwise a neighbour on this side of the wall.
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const r = r0 + dr
          const c = c0 + dc
          if (r < 0 || c < 0 || r >= rows || c >= columns) continue
          const i = r * columns + c
          if (cellRoom[i] !== room) continue
          const d = (c + 0.5 - u) ** 2 + (r + 0.5 - v) ** 2
          if (d < bestDistance) {
            best = i
            bestDistance = d
          }
        }
      }
      source[p] = best
    }
  }
  return { width, height, source }
}

/**
 * Rasterizes the indoor area with closed walls as barriers and labels the
 * connected rooms (4-connected). Anti-aliased edges count as barriers, so no
 * room leaks through a wall.
 */
function labelRooms(
  layout: Layout,
  openOpeningIds: ReadonlySet<string>,
  boundary: PixelPoint[],
  holes: PixelPoint[][],
  s: number,
  width: number,
  height: number,
): Int32Array {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, width, height)
  ctx.setTransform(s, 0, 0, s, 0, 0)

  ctx.beginPath()
  for (const ring of [boundary, ...holes]) {
    ring.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)))
    ctx.closePath()
  }
  ctx.fillStyle = '#fff'
  ctx.fill('evenodd')

  ctx.beginPath()
  for (const [a, b] of barrierSegments(layout, openOpeningIds)) {
    ctx.moveTo(a.x, a.y)
    ctx.lineTo(b.x, b.y)
  }
  ctx.strokeStyle = '#000'
  ctx.lineWidth = 2 / s
  ctx.lineCap = 'square'
  ctx.stroke()

  const pixels = ctx.getImageData(0, 0, width, height).data
  const region = new Int32Array(width * height).fill(-1)
  const open = (p: number) => pixels[p * 4] === 255 && region[p] === -1
  const stack: number[] = []
  let next = 0
  for (let start = 0; start < width * height; start++) {
    if (!open(start)) continue
    region[start] = next
    stack.push(start)
    while (stack.length > 0) {
      const p = stack.pop()!
      const x = p % width
      for (const q of [x > 0 ? p - 1 : -1, x < width - 1 ? p + 1 : -1, p - width, p + width]) {
        if (q >= 0 && q < width * height && open(q)) {
          region[q] = next
          stack.push(q)
        }
      }
    }
    next++
  }
  return region
}

/** Walls minus the open doors and windows on them. */
function barrierSegments(layout: Layout, openOpeningIds: ReadonlySet<string>): [PixelPoint, PixelPoint][] {
  const segments: [PixelPoint, PixelPoint][] = []
  for (const wall of layout.walls) {
    const dx = wall.end.x - wall.start.x
    const dy = wall.end.y - wall.start.y
    const lengthSq = dx * dx + dy * dy
    if (lengthSq === 0) continue
    const at = (t: number): PixelPoint => ({ x: wall.start.x + dx * t, y: wall.start.y + dy * t })
    const param = (p: PixelPoint) => ((p.x - wall.start.x) * dx + (p.y - wall.start.y) * dy) / lengthSq
    const gaps = [...layout.doors, ...layout.windows]
      .filter((d) => d.wall_id === wall.id && openOpeningIds.has(d.id))
      .map((d) => [Math.min(param(d.start), param(d.end)), Math.max(param(d.start), param(d.end))])
      .sort((a, b) => a[0] - b[0])
    let cursor = 0
    for (const [a, b] of gaps) {
      if (a > cursor) segments.push([at(cursor), at(a)])
      cursor = Math.max(cursor, b)
    }
    if (cursor < 1) segments.push([at(cursor), at(1)])
  }
  return segments
}

/** Sum over channels (or one channel) at time index t, per cell. */
export function cellValues(field: SimulationField, t: number, channel: number | null, out: Float32Array) {
  const { rows, columns } = field.grid
  const cells = rows * columns
  const channels = field.placementIds.length
  const base = t * channels * cells
  out.fill(0)
  for (let c = 0; c < channels; c++) {
    if (channel !== null && c !== channel) continue
    const offset = base + c * cells
    for (let i = 0; i < cells; i++) out[i] += field.concentration[offset + i]
  }
}

/** Largest value over all times, so playback shows the scent building up. */
export function fieldMax(field: SimulationField, channel: number | null): number {
  const cells = field.grid.rows * field.grid.columns
  const values = new Float32Array(cells)
  let max = 0
  for (let t = 0; t < field.times.length; t++) {
    cellValues(field, t, channel, values)
    for (let i = 0; i < cells; i++) if (values[i] > max) max = values[i]
  }
  return max
}

/**
 * The frame as an image the size of the cell map, covering the whole plan.
 * Each diffuser's scent has its own colour (channelColors, in channel order);
 * a cell mixes them in proportion to each one's share of the concentration.
 */
export function renderFrame(
  field: SimulationField,
  map: CellMap,
  t: number,
  channel: number | null,
  max: number,
  channelColors: Rgb[],
): HTMLCanvasElement {
  const { rows, columns } = field.grid
  const cells = rows * columns
  const channels = field.placementIds.length
  const base = t * channels * cells

  // One packed RGBA colour per cell (ImageData is little-endian RGBA).
  const colours = new Uint32Array(cells)
  const scale = max > 0 ? 1 / max : 0
  for (let i = 0; i < cells; i++) {
    if (!field.mask[i]) continue
    let total = 0
    let r = 0
    let g = 0
    let b = 0
    for (let c = 0; c < channels; c++) {
      if (channel !== null && c !== channel) continue
      const v = field.concentration[base + c * cells + i]
      if (v <= 0) continue
      const [cr, cg, cb] = channelColors[c]
      total += v
      r += cr * v
      g += cg * v
      b += cb * v
    }
    const level = Math.log1p(LOG_K * total * scale) / Math.log1p(LOG_K)
    if (level <= 0.01) continue
    const [sr, sg, sb] = scentShade([r / total, g / total, b / total], Math.min(1, level))
    const a = Math.round(255 * MAX_ALPHA * Math.min(1, level * 1.4))
    colours[i] = ((a << 24) | (Math.round(sb) << 16) | (Math.round(sg) << 8) | Math.round(sr)) >>> 0
  }

  const canvas = document.createElement('canvas')
  canvas.width = map.width
  canvas.height = map.height
  const ctx = canvas.getContext('2d')!
  const image = ctx.createImageData(map.width, map.height)
  const out = new Uint32Array(image.data.buffer)
  const { source } = map
  for (let p = 0; p < source.length; p++) {
    const c = source[p]
    if (c >= 0) out[p] = colours[c]
  }
  ctx.putImageData(image, 0, 0)
  return canvas
}
