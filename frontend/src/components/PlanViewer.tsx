import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { distance, distanceToSegment, wallAt } from '../floorPlan/geometry.ts'
import type { Layout, Opening, PixelPoint, Wall } from '../floorPlan/layout.ts'
import { drawGlyph } from '../diffusers/glyphs.ts'
import type { DiffuserType } from '../diffusers/types.ts'
import { LAYOUT_STYLE } from '../floorPlan/layoutStyle.ts'

/** A placed diffuser: its type's icon on a dot in its scent colour, with a number. */
export interface PlanMarker {
  id: string
  position: PixelPoint
  label: string
  type: DiffuserType
  color: string
}

/** A fan or air conditioner: a dot with an arrow toward where the air blows. */
export interface PlanDevice {
  id: string
  kind: 'fan' | 'ac'
  position: PixelPoint
  /** Degrees clockwise from image right. */
  direction: number
}

/** Major lines every `spacing` image pixels (e.g. 1 m), with quarter lines when zoomed in. */
export interface PlanGrid {
  spacing: number
  originX: number
  originY: number
}

/** An image laid over the plan without smoothing, in image pixels (e.g. a simulated field). */
export interface PlanOverlay {
  source: CanvasImageSource
  x: number
  y: number
  width: number
  height: number
}

interface PlanViewerProps {
  image: HTMLImageElement | null
  /** Recognized geometry drawn over the image, in the image's pixel coordinates. */
  layout?: Layout | null
  /** 0 hides the image; geometry stays visible. */
  imageOpacity?: number
  /** White sheet under the image; off leaves only the geometry over the background. */
  paper?: boolean
  /** Background grid in image pixels: line spacing and a point lines pass through. */
  grid?: PlanGrid | null
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
  overlay?: PlanOverlay | null
  markers?: PlanMarker[]
  selectedMarkerId?: string | null
  /** Clicking a marker selects it; clicking empty plan reports null. */
  onMarkerSelect?: (id: string | null) => void
  /** Makes markers draggable. */
  onMarkerMove?: (id: string, position: PixelPoint) => void
  /** A marker was clicked (pressed and released without dragging), at this viewport point. */
  onMarkerClick?: (id: string, client: { x: number; y: number }) => void
  /** Any press or zoom on the plan, e.g. to close a popup tied to screen positions. */
  onInteract?: () => void
  /** Placing mode: a click on the plan reports its position instead of selecting. */
  onPlanClick?: (position: PixelPoint) => void
  /** Doors and windows drawn as open. */
  openOpeningIds?: ReadonlySet<string>
  /** Enables opening and closing doors and windows by clicking them. */
  onOpeningToggle?: (openingId: string) => void
  devices?: PlanDevice[]
  selectedDeviceId?: string | null
  onDeviceSelect?: (id: string | null) => void
  /** Makes devices draggable. */
  onDeviceMove?: (id: string, position: PixelPoint) => void
  /** Shows a handle at each arrow's tip; dragging it turns the device. */
  onDeviceRotate?: (id: string, direction: number) => void
  /** A device was clicked (pressed and released without dragging), at this viewport point. */
  onDeviceClick?: (id: string, client: { x: number; y: number }) => void
  /** Extra controls placed before "화면에 맞추기". */
  toolbar?: ReactNode
  /** Shows the "화면에 맞추기" button. */
  fitButton?: boolean
  /** Screen pixels at the top covered by something else (e.g. a see-through header); fitting avoids them. */
  fitInsetTop?: number
}

interface View {
  scale: number
  tx: number
  ty: number
}

type Drag =
  | { kind: 'pan'; x: number; y: number; tx: number; ty: number; moved: boolean }
  | { kind: 'vertex'; index: number }
  | { kind: 'marker'; id: string; x: number; y: number; moved: boolean }
  | { kind: 'device'; id: string; x: number; y: number; moved: boolean }
  | { kind: 'rotate'; id: string }

const NO_OPENINGS: ReadonlySet<string> = new Set()
/** Rotation snaps to this many degrees. */
const ROTATE_STEP = 5

/** Screen-pixel radius within which a handle or wall responds to the pointer. */
const HANDLE_HIT_PX = 10
const CLICK_TOLERANCE_PX = 4
const MIN_POLYGON_POINTS = 3

export function PlanViewer({
  image,
  layout = null,
  imageOpacity = 1,
  paper = true,
  grid = null,
  wallThickness = 4,
  selectedWallId = null,
  onWallSelect,
  polygon = null,
  onPolygonChange,
  onFileDrop,
  overlay = null,
  markers,
  selectedMarkerId = null,
  onMarkerSelect,
  onMarkerMove,
  onMarkerClick,
  onInteract,
  onPlanClick,
  openOpeningIds = NO_OPENINGS,
  onOpeningToggle,
  devices,
  selectedDeviceId = null,
  onDeviceSelect,
  onDeviceMove,
  onDeviceRotate,
  onDeviceClick,
  toolbar,
  fitButton = true,
  fitInsetTop = 0,
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
  const [hoverOpeningId, setHoverOpeningId] = useState<string | null>(null)
  const [cursor, setCursor] = useState('grab')
  const editable = Boolean(polygon && onPolygonChange)

  useEffect(() => {
    polygonRef.current = polygon
  }, [polygon])

  const fitToView = useCallback(() => {
    if (!image || size.width === 0) return
    const height = Math.max(1, size.height - fitInsetTop)
    const scale = Math.min(size.width / image.naturalWidth, height / image.naturalHeight) * 0.92
    viewRef.current = {
      scale,
      tx: (size.width - image.naturalWidth * scale) / 2,
      ty: fitInsetTop + (height - image.naturalHeight * scale) / 2,
    }
    setRedraw((n) => n + 1)
  }, [image, size.width, size.height, fitInsetTop])

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
    if (grid) drawGrid(ctx, grid, scale, { x: -tx / scale, y: -ty / scale, width: size.width / scale, height: size.height / scale })
    if (paper) {
      // Paper background, so transparent plans stay readable.
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, image.naturalWidth, image.naturalHeight)
      if (imageOpacity > 0) {
        ctx.globalAlpha = imageOpacity
        ctx.drawImage(image, 0, 0)
        ctx.globalAlpha = 1
      }
    }
    if (polygon) fillPolygon(ctx, polygon)
    if (overlay) {
      // Flat colour per cell; smoothing would blend values across walls.
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(overlay.source, overlay.x, overlay.y, overlay.width, overlay.height)
      ctx.imageSmoothingEnabled = true
    }
    if (layout) {
      drawLayout(ctx, layout, scale, wallThickness, openOpeningIds, hoverOpeningId)
      const highlighted = [selectedWallId, hoverWallId !== selectedWallId ? hoverWallId : null]
      for (const id of highlighted) {
        const wall = id ? layout.walls.find((w) => w.id === id) : undefined
        if (wall) drawWallHighlight(ctx, wall, scale, wallThickness, id === selectedWallId)
      }
    }
    if (polygon) strokePolygon(ctx, polygon, scale, editable)
    if (devices) drawDevices(ctx, devices, selectedDeviceId, scale, Boolean(onDeviceRotate))
    if (markers) drawMarkers(ctx, markers, selectedMarkerId, scale)
  }, [
    image,
    layout,
    imageOpacity,
    paper,
    grid,
    wallThickness,
    selectedWallId,
    hoverWallId,
    polygon,
    editable,
    overlay,
    markers,
    selectedMarkerId,
    openOpeningIds,
    hoverOpeningId,
    devices,
    selectedDeviceId,
    onDeviceRotate,
    size,
    redraw,
  ])

  // Latest onInteract for the wheel listener, which is registered once.
  const onInteractRef = useRef(onInteract)
  useEffect(() => {
    onInteractRef.current = onInteract
  }, [onInteract])

  // React registers wheel listeners as passive, so zoom needs a manual listener.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      onInteractRef.current?.()
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

  /** The topmost marker under `p`, if markers respond to the pointer. */
  const markerUnder = (p: PixelPoint): PlanMarker | null => {
    if (!markers || !(onMarkerSelect || onMarkerMove)) return null
    const tolerance = (LAYOUT_STYLE.marker.radius + 3) / viewRef.current.scale
    for (let i = markers.length - 1; i >= 0; i--) {
      if (distance(markers[i].position, p) <= tolerance) return markers[i]
    }
    return null
  }

  /** The door or window under `p`, if they can be toggled. */
  const openingUnder = (p: PixelPoint): Opening | null => {
    if (!layout || !onOpeningToggle) return null
    const tolerance = Math.max(wallThickness / 2, HANDLE_HIT_PX / viewRef.current.scale)
    let best: Opening | null = null
    let bestDistance = tolerance
    for (const opening of [...layout.doors, ...layout.windows]) {
      const d = distanceToSegment(p, opening.start, opening.end)
      if (d <= bestDistance) {
        best = opening
        bestDistance = d
      }
    }
    return best
  }

  /** A device whose rotate handle is under `p`. */
  const rotateHandleUnder = (p: PixelPoint): PlanDevice | null => {
    if (!devices || !onDeviceRotate) return null
    const scale = viewRef.current.scale
    for (let i = devices.length - 1; i >= 0; i--) {
      if (distance(deviceHandle(devices[i], scale), p) <= (LAYOUT_STYLE.device.handleRadius + 4) / scale) return devices[i]
    }
    return null
  }

  const deviceUnder = (p: PixelPoint): PlanDevice | null => {
    if (!devices || !(onDeviceSelect || onDeviceMove)) return null
    const tolerance = (LAYOUT_STYLE.device.radius + 3) / viewRef.current.scale
    for (let i = devices.length - 1; i >= 0; i--) {
      if (distance(devices[i].position, p) <= tolerance) return devices[i]
    }
    return null
  }

  const updateHover = (p: PixelPoint) => {
    const rotating = rotateHandleUnder(p) !== null
    const handle =
      rotating || vertexAt(p) >= 0 || midpointAt(p) >= 0 || markerUnder(p) !== null || deviceUnder(p) !== null
    const door = handle || onPlanClick ? null : openingUnder(p)
    const wall = handle || door ? null : wallUnder(p)
    const nextCursor = rotating ? 'alias' : handle ? 'move' : door || wall ? 'pointer' : 'grab'
    if (nextCursor !== cursor) setCursor(nextCursor)
    const nextWall = wall?.id ?? null
    if (nextWall !== hoverWallId) setHoverWallId(nextWall)
    const nextDoor = door?.id ?? null
    if (nextDoor !== hoverOpeningId) setHoverOpeningId(nextDoor)
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
        style={{ cursor: cursor === 'grab' && onPlanClick ? 'crosshair' : cursor }}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          onInteract?.()
          const p = toImage(event.clientX, event.clientY)
          const turning = rotateHandleUnder(p)
          if (turning) {
            onDeviceSelect?.(turning.id)
            dragRef.current = { kind: 'rotate', id: turning.id }
            return
          }
          const device = deviceUnder(p)
          if (device) {
            onDeviceSelect?.(device.id)
            dragRef.current = { kind: 'device', id: device.id, x: event.clientX, y: event.clientY, moved: false }
            return
          }
          const marker = markerUnder(p)
          if (marker) {
            onMarkerSelect?.(marker.id)
            dragRef.current = { kind: 'marker', id: marker.id, x: event.clientX, y: event.clientY, moved: false }
            return
          }
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
          if (drag.kind === 'rotate') {
            const device = devices?.find((d) => d.id === drag.id)
            if (!device || !onDeviceRotate) return
            const angle = (Math.atan2(p.y - device.position.y, p.x - device.position.x) * 180) / Math.PI
            onDeviceRotate(drag.id, (Math.round(angle / ROTATE_STEP) * ROTATE_STEP + 360) % 360)
            return
          }
          if (drag.kind === 'device') {
            if (!onDeviceMove) return
            if (drag.moved || Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > CLICK_TOLERANCE_PX) {
              drag.moved = true
              onDeviceMove(drag.id, clampToImage(p))
            }
            return
          }
          if (drag.kind === 'marker') {
            if (!onMarkerMove) return
            if (drag.moved || Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > CLICK_TOLERANCE_PX) {
              drag.moved = true
              onMarkerMove(drag.id, clampToImage(p))
            }
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
          if (drag?.kind === 'device' && !drag.moved) {
            onDeviceClick?.(drag.id, { x: event.clientX, y: event.clientY })
            return
          }
          if (drag?.kind === 'marker' && !drag.moved) {
            onMarkerClick?.(drag.id, { x: event.clientX, y: event.clientY })
            return
          }
          if (drag?.kind === 'pan' && !drag.moved) {
            const p = toImage(event.clientX, event.clientY)
            if (onPlanClick) {
              onPlanClick(clampToImage(p))
              return
            }
            const opening = openingUnder(p)
            if (opening) {
              onOpeningToggle?.(opening.id)
              return
            }
            const wall = wallUnder(p)
            if (wall) onWallSelect?.(wall.id)
            else {
              onMarkerSelect?.(null)
              onDeviceSelect?.(null)
            }
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
          if (hoverOpeningId) setHoverOpeningId(null)
        }}
      />
      {!image && onFileDrop && (
        <div className="viewer__empty">
          <p>평면도 이미지를 여기로 끌어다 놓거나</p>
          <p>왼쪽에서 파일을 선택하세요.</p>
        </div>
      )}
      {hoverOpeningId && (
        <p className="viewer__hint" role="status">
          {openingHint(layout, hoverOpeningId, openOpeningIds.has(hoverOpeningId))}
        </p>
      )}
      {image && (toolbar || fitButton) && (
        <div className="viewer__toolbar">
          {toolbar}
          {fitButton && (
            <button type="button" onClick={fitToView}>
              화면에 맞추기
            </button>
          )}
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
function drawLayout(
  ctx: CanvasRenderingContext2D,
  layout: Layout,
  scale: number,
  thickness: number,
  openIds: ReadonlySet<string>,
  hoverId: string | null,
) {
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

  const openings = (items: Opening[], style: { color: string; band: string; line: number; dash?: number }) => {
    if (items.length === 0) return
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
    if (style.dash) ctx.setLineDash([style.dash / scale, style.dash / scale])
    ctx.stroke()
    ctx.setLineDash([])
  }
  openings(
    layout.doors.filter((d) => !openIds.has(d.id)),
    LAYOUT_STYLE.door,
  )
  openings(
    layout.doors.filter((d) => openIds.has(d.id)),
    LAYOUT_STYLE.openDoor,
  )
  openings(
    layout.windows.filter((w) => !openIds.has(w.id)),
    LAYOUT_STYLE.window,
  )
  openings(
    layout.windows.filter((w) => openIds.has(w.id)),
    LAYOUT_STYLE.openWindow,
  )

  const hovered = hoverId ? [...layout.doors, ...layout.windows].find((o) => o.id === hoverId) : undefined
  if (hovered) {
    ctx.beginPath()
    ctx.moveTo(hovered.start.x, hovered.start.y)
    ctx.lineTo(hovered.end.x, hovered.end.y)
    ctx.strokeStyle = LAYOUT_STYLE.selection.hover
    ctx.lineWidth = thickness + LAYOUT_STYLE.selection.outset / scale
    ctx.stroke()
  }
}

/** Hint shown while hovering a door or window. */
function openingHint(layout: Layout | null, id: string, open: boolean): string {
  const kind = layout?.windows.some((w) => w.id === id) ? '창문' : '문'
  return open ? `열린 ${kind} · 클릭하면 닫혀요` : `닫힌 ${kind} · 클릭하면 열려요`
}

/** Arrow tip of a device, in image pixels (the arrow has a fixed screen length). */
function deviceHandle(d: PlanDevice, scale: number): PixelPoint {
  const length = LAYOUT_STYLE.device.arrow / scale
  const a = (d.direction * Math.PI) / 180
  return { x: d.position.x + Math.cos(a) * length, y: d.position.y + Math.sin(a) * length }
}

function drawDevices(
  ctx: CanvasRenderingContext2D,
  devices: PlanDevice[],
  selectedId: string | null,
  scale: number,
  rotatable: boolean,
) {
  const style = LAYOUT_STYLE.device
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const d of devices) {
    const { x, y } = d.position
    const tip = deviceHandle(d, scale)
    const a = (d.direction * Math.PI) / 180
    // Arrow toward where the air blows.
    ctx.strokeStyle = style.color
    ctx.fillStyle = style.color
    ctx.lineWidth = 2.5 / scale
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.lineTo(tip.x, tip.y)
    ctx.stroke()
    const head = 9 / scale
    ctx.beginPath()
    ctx.moveTo(tip.x + Math.cos(a) * head * 0.4, tip.y + Math.sin(a) * head * 0.4)
    ctx.lineTo(tip.x - Math.cos(a - 0.5) * head, tip.y - Math.sin(a - 0.5) * head)
    ctx.lineTo(tip.x - Math.cos(a + 0.5) * head, tip.y - Math.sin(a + 0.5) * head)
    ctx.closePath()
    ctx.fill()

    if (d.id === selectedId) {
      ctx.beginPath()
      ctx.arc(x, y, style.ringRadius / scale, 0, Math.PI * 2)
      ctx.strokeStyle = style.ring
      ctx.lineWidth = 3 / scale
      ctx.stroke()
    }
    ctx.beginPath()
    if (d.kind === 'ac') {
      const r = style.radius / scale
      ctx.roundRect(x - r, y - r * 0.8, r * 2, r * 1.6, 4 / scale)
    } else {
      ctx.arc(x, y, style.radius / scale, 0, Math.PI * 2)
    }
    ctx.fillStyle = style.color
    ctx.fill()
    ctx.strokeStyle = style.text
    ctx.lineWidth = 1.5 / scale
    ctx.stroke()
    ctx.fillStyle = style.text
    ctx.font = `700 ${(d.kind === 'ac' ? 9 : 10) / scale}px system-ui, sans-serif`
    ctx.fillText(d.kind === 'ac' ? 'AC' : '팬', x, y + 0.5 / scale)

    if (rotatable) {
      ctx.beginPath()
      ctx.arc(tip.x + Math.cos(a) * (6 / scale), tip.y + Math.sin(a) * (6 / scale), style.handleRadius / scale, 0, Math.PI * 2)
      ctx.fillStyle = '#ffffff'
      ctx.fill()
      ctx.strokeStyle = style.color
      ctx.lineWidth = 2 / scale
      ctx.stroke()
    }
  }
}

/** Thin lines over the visible area; quarter lines appear once they are far enough apart. */
function drawGrid(
  ctx: CanvasRenderingContext2D,
  grid: PlanGrid,
  scale: number,
  visible: { x: number; y: number; width: number; height: number },
) {
  const levels = [
    { step: grid.spacing / 4, color: 'rgba(78, 83, 76, 0.07)', minScreen: 10 },
    { step: grid.spacing, color: 'rgba(78, 83, 76, 0.16)', minScreen: 6 },
  ]
  ctx.lineWidth = 1 / scale
  for (const { step, color, minScreen } of levels) {
    if (!(step > 0) || step * scale < minScreen) continue
    ctx.beginPath()
    const x0 = grid.originX + Math.floor((visible.x - grid.originX) / step) * step
    for (let x = x0; x <= visible.x + visible.width; x += step) {
      ctx.moveTo(x, visible.y)
      ctx.lineTo(x, visible.y + visible.height)
    }
    const y0 = grid.originY + Math.floor((visible.y - grid.originY) / step) * step
    for (let y = y0; y <= visible.y + visible.height; y += step) {
      ctx.moveTo(visible.x, y)
      ctx.lineTo(visible.x + visible.width, y)
    }
    ctx.strokeStyle = color
    ctx.stroke()
  }
}

function drawMarkers(ctx: CanvasRenderingContext2D, markers: PlanMarker[], selectedId: string | null, scale: number) {
  const style = LAYOUT_STYLE.marker
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const m of markers) {
    const { x, y } = m.position
    const r = style.radius / scale
    if (m.id === selectedId) {
      ctx.beginPath()
      ctx.arc(x, y, style.ringRadius / scale, 0, Math.PI * 2)
      ctx.strokeStyle = style.ring
      ctx.lineWidth = 3 / scale
      ctx.stroke()
    }
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = m.color
    ctx.fill()
    ctx.strokeStyle = style.edge
    ctx.lineWidth = 1.5 / scale
    ctx.stroke()
    // The type icon in white; thicker lines so it reads at this size.
    drawGlyph(ctx, m.type, x, y, (style.radius * 1.5) / scale, style.text, 1.6)

    // Number badge, matching the playback's per-diffuser list.
    const bx = x + r * 0.78
    const by = y + r * 0.78
    ctx.beginPath()
    ctx.arc(bx, by, style.badge / scale, 0, Math.PI * 2)
    ctx.fillStyle = style.badgeFill
    ctx.fill()
    ctx.fillStyle = style.text
    ctx.font = `700 ${style.font / scale}px system-ui, sans-serif`
    ctx.fillText(m.label, bx, by + 0.5 / scale)
  }
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
