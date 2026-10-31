// Pure geometry helpers in image-pixel coordinates.

import type { Layout, PixelPoint, Wall } from './layout.ts'

export function distance(a: PixelPoint, b: PixelPoint): number {
  return Math.hypot(b.x - a.x, b.y - a.y)
}

export function wallLength(wall: Wall): number {
  return distance(wall.start, wall.end)
}

export function distanceToSegment(p: PixelPoint, a: PixelPoint, b: PixelPoint): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lengthSq = dx * dx + dy * dy
  if (lengthSq === 0) return distance(p, a)
  const t = Math.min(1, Math.max(0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSq))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

/** The wall nearest to `p` within `tolerance` pixels, if any. */
export function wallAt(layout: Layout, p: PixelPoint, tolerance: number): Wall | null {
  let best: Wall | null = null
  let bestDistance = tolerance
  for (const wall of layout.walls) {
    const d = distanceToSegment(p, wall.start, wall.end)
    if (d <= bestDistance) {
      best = wall
      bestDistance = d
    }
  }
  return best
}

/** Shoelace area of a simple polygon, in square pixels. */
export function polygonArea(points: PixelPoint[]): number {
  let sum = 0
  for (let i = 0; i < points.length; i++) {
    const a = points[i]
    const b = points[(i + 1) % points.length]
    sum += a.x * b.y - b.x * a.y
  }
  return Math.abs(sum) / 2
}

/**
 * Starting indoor outline for the user to adjust: recognition's estimate when
 * it has one, otherwise the rectangle spanned by the recognized walls (or most
 * of the image without walls).
 */
export function suggestIndoorBoundary(layout: Layout): PixelPoint[] {
  const estimate = layout.indoor_domain?.boundary
  if (estimate && estimate.length >= 3) return estimate.map((p) => ({ ...p }))
  if (layout.walls.length === 0) {
    const mx = layout.width_px * 0.1
    const my = layout.height_px * 0.1
    return rectangle(mx, my, layout.width_px - mx, layout.height_px - my)
  }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const wall of layout.walls) {
    for (const p of [wall.start, wall.end]) {
      minX = Math.min(minX, p.x)
      minY = Math.min(minY, p.y)
      maxX = Math.max(maxX, p.x)
      maxY = Math.max(maxY, p.y)
    }
  }
  return rectangle(minX, minY, maxX, maxY)
}

function rectangle(x0: number, y0: number, x1: number, y1: number): PixelPoint[] {
  return [
    { x: x0, y: y0 },
    { x: x1, y: y0 },
    { x: x1, y: y1 },
    { x: x0, y: y1 },
  ]
}

/** Even-odd test; points exactly on an edge may land either way. */
export function pointInRing(p: PixelPoint, ring: PixelPoint[]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]
    const b = ring[j]
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside
  }
  return inside
}

/** Inside the outer ring and outside every hole. */
export function pointInDomain(p: PixelPoint, boundary: PixelPoint[], holes: PixelPoint[][] = []): boolean {
  return pointInRing(p, boundary) && !holes.some((hole) => pointInRing(p, hole))
}

/** Distance from `p` to the nearest edge of any of the rings. */
export function distanceToRings(p: PixelPoint, rings: PixelPoint[][]): number {
  let best = Infinity
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i++) {
      best = Math.min(best, distanceToSegment(p, ring[i], ring[(i + 1) % ring.length]))
    }
  }
  return best
}

/**
 * Positions (0 to 1) along segment a→b where it meets an edge of the rings,
 * including both ends of any collinear overlap.
 */
export function ringCrossings(a: PixelPoint, b: PixelPoint, rings: PixelPoint[][]): number[] {
  const rx = b.x - a.x
  const ry = b.y - a.y
  const length = Math.hypot(rx, ry)
  const ts: number[] = []
  if (length === 0) return ts
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i++) {
      const c = ring[i]
      const d = ring[(i + 1) % ring.length]
      const sx = d.x - c.x
      const sy = d.y - c.y
      const denom = rx * sy - ry * sx
      const qx = c.x - a.x
      const qy = c.y - a.y
      if (Math.abs(denom) < 1e-9 * length * Math.hypot(sx, sy)) {
        // Parallel: only a collinear overlap (within 1e-6 px) matters.
        if (Math.abs(qx * ry - qy * rx) > 1e-6 * length) continue
        for (const p of [c, d]) {
          const t = ((p.x - a.x) * rx + (p.y - a.y) * ry) / (length * length)
          if (t > 0 && t < 1) ts.push(t)
        }
        continue
      }
      const t = (qx * sy - qy * sx) / denom
      const u = (qx * ry - qy * rx) / denom
      if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push(t)
    }
  }
  return ts
}

/** Meters per image pixel from a reference length, or null if unusable. */
export function metersPerPixel(start: PixelPoint, end: PixelPoint, distanceM: number): number | null {
  const px = distance(start, end)
  return px > 0 && distanceM > 0 ? distanceM / px : null
}
