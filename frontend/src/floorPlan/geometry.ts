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
 * Starting indoor outline for the user to adjust. Recognition does not provide
 * one yet, so this is the rectangle spanned by the recognized walls (or most of
 * the image without walls). A backend-provided outline should take its place.
 */
export function suggestIndoorBoundary(layout: Layout): PixelPoint[] {
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

/** Meters per image pixel from a reference length, or null if unusable. */
export function metersPerPixel(start: PixelPoint, end: PixelPoint, distanceM: number): number | null {
  const px = distance(start, end)
  return px > 0 && distanceM > 0 ? distanceM / px : null
}
