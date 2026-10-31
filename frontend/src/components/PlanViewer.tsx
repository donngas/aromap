import { useCallback, useEffect, useRef, useState } from 'react'
import { distance, wallAt } from '../floorPlan/geometry.ts'
import type { Layout, Opening, PixelPoint, Wall } from '../floorPlan/layout.ts'
import { LAYOUT_STYLE } from '../floorPlan/layoutStyle.ts'

interface PlanViewerProps {
  image: HTMLImageElement | null
  /** Recognized geometry drawn over the image, in the image's pixel coordinates. */
  layout?: Layout | null
  /** 0 hides the image; geometry stays visible. */
  imageOpacity?: number
  /** Display-only wall thickness in image pixels; scales with zoom like a real wall. */
  wallThickness?: number
  /** Highlighted wall, e.g. the calibration reference. */
  selectedWallId?: string | null
  /** Enables picking a wall by clicking it. */
  onWallSelect?: (wallId: string) => void
  /** Indoor outline drawn over the plan. */
  polygon?: PixelPoint[] | null
  /** Makes the outline editable: drag vertices, drag edge midpoints to add one, double-click to remove. */
  onPolygonChange?: (points: PixelPoint[]) => void
  onFileDrop?: (file: File) => void
}

interface View {
  scale: number
  tx: number
  ty: number
}

type Drag =
  | { kind: 'pan'; x: number; y: number; tx: number; ty: number; moved: boolean }
  | { kind: 'vertex'; index: number }

/** Screen-pixel radius within which a handle or wall responds to the pointer. */
const HANDLE_HIT_PX = 10
const CLICK_TOLERANCE_PX = 4
const MIN_POLYGON_POINTS = 3

export function PlanViewer({
  image,
  layout = null,
  imageOpacity = 1,
  wallThickness = 4,
  selectedWallId = null,
  onWallSelect,
  polygon = null,
  onPolygonChange,
  onFileDrop,
}: PlanViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const viewRef = useRef<View>({ scale: 1, tx: 0, ty: 0 })
  const dragRef = useRef<Drag | null>(null)
  // Latest outline for drag handlers, which outlive a single render.
  const polygonRef = useRef(polygon)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [redraw, setRedraw] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [hoverWallId, setHoverWallId] = useState<string | null>(null)
  const [cursor, setCursor] = useState('grab')
  const editable = Boolean(polygon && onPolygonChange)

  useEffect(() => {
    polygonRef.current = polygon
  }, [polygon])

  const fitToView = useCallback(() => {
    if (!image || size.width === 0) return
    const scale = Math.min(size.width / image.naturalWidth, size.height / image.naturalHeight) * 0.92
    viewRef.current = {
      scale,
      tx: (size.width - image.naturalWidth * scale) / 2,
      ty: (size.height - image.naturalHeight * scale) / 2,
    }
    setRedraw((n) => n + 1)
  }, [image, size.width, size.height])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Refit only when a different plan is loaded, not on every resize.
  const fittedImage = useRef<HTMLImageElement | null>(null)
  useEffect(() => {
    if (image && size.width > 0 && fittedImage.current !== image) {
      fittedImage.current = image
      fitToView()
    }
  }, [image, size.width, fitToView])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(size.width * dpr)
    canvas.height = Math.round(size.height * dpr)
    const ctx = canvas.getContext('2d')!
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!image) return

    const { scale, tx, ty } = viewRef.current
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * tx, dpr * ty)
    // Paper background, so transparent plans stay readable.
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, image.naturalWidth, image.naturalHeight)
    if (imageOpacity > 0) {
      ctx.globalAlpha = imageOpacity
      ctx.drawImage(image, 0, 0)
      ctx.globalAlpha = 1
    }
    if (polygon) fillPolygon(ctx, polygon)
    if (layout) {
      drawLayout(ctx, layout, scale, wallThickness)
      const highlighted = [selectedWallId, hoverWallId !== selectedWallId ? hoverWallId : null]
      for (const id of highlighted) {
        const wall = id ? layout.walls.find((w) => w.id === id) : undefined
        if (wall) drawWallHighlight(ctx, wall, scale, wallThickness, id === selectedWallId)
      }
    }
    if (polygon) strokePolygon(ctx, polygon, scale, editable)
  }, [image, layout, imageOpacity, wallThickness, selectedWallId, hoverWallId, polygon, editable, size, redraw])

  // React registers wheel listeners as passive, so zoom needs a manual listener.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = canvas.getBoundingClientRect()
      const sx = event.clientX - rect.left
      const sy = event.clientY - rect.top
      const view = viewRef.current
      const factor = Math.exp(-event.deltaY * 0.0015)
      const scale = Math.min(40, Math.max(0.05, view.scale * factor))
      viewRef.current = {
        scale,
        tx: sx - ((sx - view.tx) * scale) / view.scale,
        ty: sy - ((sy - view.ty) * scale) / view.scale,
      }
      setRedraw((n) => n + 1)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  const toImage = (clientX: number, clientY: number): PixelPoint => {
    const rect = canvasRef.current!.getBoundingClientRect()
    const { scale, tx, ty } = viewRef.current
    return { x: (clientX - rect.left - tx) / scale, y: (clientY - rect.top - ty) / scale }
  }

  const clampToImage = (p: PixelPoint): PixelPoint =>
    image
      ? { x: Math.min(image.naturalWidth, Math.max(0, p.x)), y: Math.min(image.naturalHeight, Math.max(0, p.y)) }
      : p

  /** Index of the vertex under `p`, or -1. */
  const vertexAt = (p: PixelPoint): number => {
    const points = polygonRef.current
    if (!points || !onPolygonChange) return -1
    const tolerance = HANDLE_HIT_PX / viewRef.current.scale
    return points.findIndex((v) => distance(v, p) <= tolerance)
  }

  /** Index of the edge whose midpoint handle is under `p`, or -1. */
  const midpointAt = (p: PixelPoint): number => {
    const points = polygonRef.current
    if (!points || !onPolygonChange) return -1
    const tolerance = HANDLE_HIT_PX / viewRef.current.scale
    return points.findIndex((a, i) => distance(midpoint(a, points[(i + 1) % points.length]), p) <= tolerance)
  }

  const wallUnder = (p: PixelPoint): Wall | null => {
    if (!layout || !onWallSelect) return null
    const tolerance = Math.max(wallThickness / 2, HANDLE_HIT_PX / viewRef.current.scale)
    return wallAt(layout, p, tolerance)
  }

  const updateHover = (p: PixelPoint) => {
    const handle = vertexAt(p) >= 0 || midpointAt(p) >= 0
    const wall = handle ? null : wallUnder(p)
    const nextCursor = handle ? 'move' : wall ? 'pointer' : 'grab'
    if (nextCursor !== cursor) setCursor(nextCursor)
    const nextWall = wall?.id ?? null
    if (nextWall !== hoverWallId) setHoverWallId(nextWall)
  }

  return (
    <div
      ref={containerRef}
      className={`viewer${dragOver ? ' viewer--drop' : ''}`}
      onDragOver={(event) => {
        if (!onFileDrop) return
        event.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        if (!onFileDrop) return
        event.preventDefault()
        setDragOver(false)
        const file = event.dataTransfer.files[0]
        if (file) onFileDrop(file)
      }}
    >
      <canvas
        ref={canvasRef}
        className="viewer__canvas"
        style={{ cursor }}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          const p = toImage(event.clientX, event.clientY)
          const vertex = vertexAt(p)
          if (vertex >= 0) {
            dragRef.current = { kind: 'vertex', index: vertex }
            return
          }
          const edge = midpointAt(p)
          const points = polygonRef.current
          if (edge >= 0 && points && onPolygonChange) {
            // Dragging an edge midpoint inserts a vertex there and moves it.
            const next = [...points]
            next.splice(edge + 1, 0, midpoint(points[edge], points[(edge + 1) % points.length]))
            polygonRef.current = next
            onPolygonChange(next)
            dragRef.current = { kind: 'vertex', index: edge + 1 }
            return
          }
          const { tx, ty } = viewRef.current
          dragRef.current = { kind: 'pan', x: event.clientX, y: event.clientY, tx, ty, moved: false }
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          const p = toImage(event.clientX, event.clientY)
          if (!drag) {
            updateHover(p)
            return
          }
          if (drag.kind === 'vertex') {
            const points = polygonRef.current
            if (!points || !onPolygonChange) return
            const next = points.map((v, i) => (i === drag.index ? clampToImage(p) : v))
            polygonRef.current = next
            onPolygonChange(next)
            return
          }
          const dx = event.clientX - drag.x
          const dy = event.clientY - drag.y
          if (drag.moved || Math.hypot(dx, dy) > CLICK_TOLERANCE_PX) {
            drag.moved = true
            viewRef.current = { ...viewRef.current, tx: drag.tx + dx, ty: drag.ty + dy }
            setRedraw((n) => n + 1)
          }
        }}
        onPointerUp={(event) => {
          const drag = dragRef.current
          dragRef.current = null
          if (drag?.kind === 'pan' && !drag.moved) {
            const wall = wallUnder(toImage(event.clientX, event.clientY))
            if (wall) onWallSelect?.(wall.id)
          }
        }}
        onDoubleClick={(event) => {
          const points = polygonRef.current
          if (!points || !onPolygonChange || points.length <= MIN_POLYGON_POINTS) return
          const vertex = vertexAt(toImage(event.clientX, event.clientY))
          if (vertex < 0) return
          const next = points.filter((_, i) => i !== vertex)
          polygonRef.current = next
          onPolygonChange(next)
        }}
        onPointerLeave={() => {
          if (hoverWallId) setHoverWallId(null)
        }}
      />
      {!image && onFileDrop && (
        <div className="viewer__empty">
          <p>평면도 이미지를 여기로 끌어다 놓거나</p>
          <p>왼쪽에서 파일을 선택하세요.</p>
        </div>
      )}
      {image && (
        <div className="viewer__toolbar">
          <button type="button" onClick={fitToView}>
            화면에 맞추기
          </button>
        </div>
      )}
    </div>
  )
}

function midpoint(a: PixelPoint, b: PixelPoint): PixelPoint {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

type Interval = [number, number]

const EPSILON = 1e-6

/** Position of `p` along `wall`, 0 at its start and 1 at its end. */
function paramOnWall(wall: Wall, p: PixelPoint): number {
  const dx = wall.end.x - wall.start.x
  const dy = wall.end.y - wall.start.y
  const lengthSq = dx * dx + dy * dy
  if (lengthSq === 0) return 0
  return Math.min(1, Math.max(0, ((p.x - wall.start.x) * dx + (p.y - wall.start.y) * dy) / lengthSq))
}

/** Parts of [0, 1] not covered by `cuts`. */
function solidParts(cuts: Interval[]): Interval[] {
  const sorted = [...cuts].sort((a, b) => a[0] - b[0])
  const parts: Interval[] = []
  let from = 0
  for (const [a, b] of sorted) {
    if (a > from + EPSILON) parts.push([from, a])
    from = Math.max(from, b)
  }
  if (from < 1 - EPSILON) parts.push([from, 1])
  return parts
}

/**
 * Walls are drawn as bands of the given thickness, broken where a door or
 * window sits, with square joints at their endpoints so corners and
 * T-junctions close cleanly. Openings fill their gap within the band.
 */
function drawLayout(ctx: CanvasRenderingContext2D, layout: Layout, scale: number, thickness: number) {
  const wallsById = new Map(layout.walls.map((w) => [w.id, w]))
  const cutsByWall = new Map<string, Interval[]>()
  for (const o of [...layout.doors, ...layout.windows]) {
    const wall = wallsById.get(o.wall_id)
    if (!wall) continue
    const a = paramOnWall(wall, o.start)
    const b = paramOnWall(wall, o.end)
    const cuts = cutsByWall.get(wall.id) ?? []
    cuts.push([Math.min(a, b), Math.max(a, b)])
    cutsByWall.set(wall.id, cuts)
  }
  const at = (wall: Wall, t: number): PixelPoint => ({
    x: wall.start.x + (wall.end.x - wall.start.x) * t,
    y: wall.start.y + (wall.end.y - wall.start.y) * t,
  })

  ctx.strokeStyle = LAYOUT_STYLE.wall.color
  ctx.fillStyle = LAYOUT_STYLE.wall.color
  ctx.lineWidth = thickness
  ctx.lineCap = 'butt'
  ctx.beginPath()
  const joints = new Path2D()
  const half = thickness / 2
  for (const wall of layout.walls) {
    const cuts = cutsByWall.get(wall.id) ?? []
    for (const [a, b] of solidParts(cuts)) {
      const p = at(wall, a)
      const q = at(wall, b)
      ctx.moveTo(p.x, p.y)
      ctx.lineTo(q.x, q.y)
    }
    // No joint where an opening runs right up to the wall's end.
    const openStart = cuts.some(([a]) => a <= EPSILON)
    const openEnd = cuts.some(([, b]) => b >= 1 - EPSILON)
    if (!openStart) joints.rect(wall.start.x - half, wall.start.y - half, thickness, thickness)
    if (!openEnd) joints.rect(wall.end.x - half, wall.end.y - half, thickness, thickness)
  }
  ctx.stroke()
  ctx.fill(joints)

  const openings = (items: Opening[], style: { color: string; band: string; line: number }) => {
    ctx.beginPath()
    for (const o of items) {
      ctx.moveTo(o.start.x, o.start.y)
      ctx.lineTo(o.end.x, o.end.y)
    }
    ctx.strokeStyle = style.band
    ctx.lineWidth = thickness
    ctx.stroke()
    ctx.strokeStyle = style.color
    ctx.lineWidth = style.line / scale
    ctx.stroke()
  }
  openings(layout.doors, LAYOUT_STYLE.door)
  openings(layout.windows, LAYOUT_STYLE.window)
}

function drawWallHighlight(ctx: CanvasRenderingContext2D, wall: Wall, scale: number, thickness: number, selected: boolean) {
  const style = LAYOUT_STYLE.selection
  ctx.beginPath()
  ctx.moveTo(wall.start.x, wall.start.y)
  ctx.lineTo(wall.end.x, wall.end.y)
  ctx.strokeStyle = selected ? style.color : style.hover
  ctx.lineWidth = thickness + style.outset / scale
  ctx.lineCap = 'square'
  ctx.stroke()
}

function fillPolygon(ctx: CanvasRenderingContext2D, points: PixelPoint[]) {
  if (points.length < 3) return
  ctx.beginPath()
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)))
  ctx.closePath()
  ctx.fillStyle = LAYOUT_STYLE.indoor.fill
  ctx.fill()
}

function strokePolygon(ctx: CanvasRenderingContext2D, points: PixelPoint[], scale: number, editable: boolean) {
  if (points.length < 2) return
  const style = LAYOUT_STYLE.indoor
  ctx.beginPath()
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)))
  ctx.closePath()
  ctx.strokeStyle = style.line
  ctx.lineWidth = style.width / scale
  ctx.setLineDash([6 / scale, 4 / scale])
  ctx.stroke()
  ctx.setLineDash([])
  if (!editable) return

  ctx.lineWidth = 1.5 / scale
  // Edge midpoints: drag to add a vertex.
  for (let i = 0; i < points.length; i++) {
    const m = midpoint(points[i], points[(i + 1) % points.length])
    ctx.beginPath()
    ctx.arc(m.x, m.y, style.midpointRadius / scale, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(255, 255, 255, 0.85)'
    ctx.fill()
    ctx.strokeStyle = style.line
    ctx.stroke()
  }
  // Vertices: drag to move, double-click to remove.
  for (const p of points) {
    const r = style.vertexRadius / scale
    ctx.beginPath()
    ctx.rect(p.x - r, p.y - r, r * 2, r * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()
    ctx.strokeStyle = style.line
    ctx.lineWidth = 2 / scale
    ctx.stroke()
  }
}
