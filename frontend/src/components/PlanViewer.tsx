import { useCallback, useEffect, useRef, useState } from 'react'

interface PlanViewerProps {
  image: HTMLImageElement | null
  onFileDrop: (file: File) => void
}

interface View {
  scale: number
  tx: number
  ty: number
}

export function PlanViewer({ image, onFileDrop }: PlanViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const viewRef = useRef<View>({ scale: 1, tx: 0, ty: 0 })
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [redraw, setRedraw] = useState(0)
  const [dragOver, setDragOver] = useState(false)

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
    ctx.drawImage(image, 0, 0)
  }, [image, size, redraw])

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

  return (
    <div
      ref={containerRef}
      className={`viewer${dragOver ? ' viewer--drop' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragOver(false)
        const file = event.dataTransfer.files[0]
        if (file) onFileDrop(file)
      }}
    >
      <canvas
        ref={canvasRef}
        className="viewer__canvas"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          const { tx, ty } = viewRef.current
          dragRef.current = { x: event.clientX, y: event.clientY, tx, ty }
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          if (!drag) return
          viewRef.current = {
            ...viewRef.current,
            tx: drag.tx + event.clientX - drag.x,
            ty: drag.ty + event.clientY - drag.y,
          }
          setRedraw((n) => n + 1)
        }}
        onPointerUp={() => {
          dragRef.current = null
        }}
      />
      {!image && (
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
