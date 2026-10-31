import { useRef, useState, type ReactNode } from 'react'
import './FloatingWindow.css'

/** Stacking order shared by all windows: the last one touched comes to the front. */
let frontmost = 10

interface FloatingWindowProps {
  title: string
  /** Side the window is measured from; it keeps that side when the container resizes. */
  anchor: 'left' | 'right'
  /** Starting distance from the anchored side and from the top of the container, in px. */
  initialX: number
  initialY: number
  width: number
  /** Highest the window may be dragged, e.g. to stay below a header. */
  minY?: number
  initialCollapsed?: boolean
  className?: string
  children: ReactNode
}

/**
 * A small app-style window floating over the workspace. Drag its title bar to
 * move it (it stays inside its container); the minimize button folds it down
 * to the title bar. Children stay mounted while folded, so their state is kept.
 */
export function FloatingWindow({
  title,
  anchor,
  initialX,
  initialY,
  width,
  minY = 0,
  initialCollapsed = false,
  className = '',
  children,
}: FloatingWindowProps) {
  const ref = useRef<HTMLElement>(null)
  const [position, setPosition] = useState({ x: initialX, y: initialY })
  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const [z, setZ] = useState(() => ++frontmost)
  const drag = useRef<{ pointerX: number; pointerY: number; x: number; y: number } | null>(null)

  const bringToFront = () => {
    if (z !== frontmost) setZ(++frontmost)
  }

  return (
    <section
      ref={ref}
      className={`fwin${collapsed ? ' fwin--collapsed' : ''} ${className}`}
      style={{
        [anchor]: position.x,
        top: position.y,
        width: collapsed ? undefined : width,
        maxHeight: `calc(100% - ${position.y + 16}px)`,
        zIndex: z,
      }}
      aria-label={title}
      onPointerDownCapture={bringToFront}
    >
      <header
        className="fwin__bar"
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest('button')) return
          event.currentTarget.setPointerCapture(event.pointerId)
          drag.current = { pointerX: event.clientX, pointerY: event.clientY, ...position }
        }}
        onPointerMove={(event) => {
          const start = drag.current
          const el = ref.current
          const parent = el?.parentElement
          if (!start || !el || !parent) return
          const dx = event.clientX - start.pointerX
          const bounds = parent.getBoundingClientRect()
          const maxX = Math.max(0, bounds.width - el.offsetWidth)
          // Keep the title bar reachable.
          const maxY = Math.max(minY, bounds.height - 44)
          setPosition({
            x: Math.min(maxX, Math.max(0, start.x + (anchor === 'left' ? dx : -dx))),
            y: Math.min(maxY, Math.max(minY, start.y + event.clientY - start.pointerY)),
          })
        }}
        onPointerUp={() => {
          drag.current = null
        }}
      >
        <h2 className="fwin__title">{title}</h2>
        <button
          type="button"
          className="fwin__toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? `${title} 창 펼치기` : `${title} 창 접기`}
          title={collapsed ? '펼치기' : '접기'}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? <RestoreIcon /> : <MinimizeIcon />}
        </button>
      </header>
      <div className="fwin__body" hidden={collapsed}>
        {children}
      </div>
    </section>
  )
}

function MinimizeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 6.5h8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function RestoreIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <rect x="2" y="2" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  )
}
