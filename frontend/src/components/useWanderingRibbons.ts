import { useEffect, type RefObject } from 'react'
import { drawRibbon, fillNormals, type RibbonColors, type RibbonPath } from './ribbon.ts'

// Scent ribbons that drift around the home page's diffuser. Each ribbon's head
// follows a slow, slightly irregular orbit around the bottle; the ribbon is the
// trail of where the head has been. Orbits are worked out on the floor and
// lifted above it, then flattened to match the space image's tilt. The half
// of each orbit nearer the viewer is drawn on the front canvas (over the
// bottle), the far half on the back canvas (under it).

interface Orbit {
  /** Seconds per lap. */
  period: number
  /** 1 counter-clockwise, -1 clockwise, seen from above. */
  dir: number
  /** Orbit radius and its swing, in scene widths. */
  radius: number
  wobble: number
  /** Height above the floor and its swing, in scene widths. */
  lift: number
  liftSwing: number
  phase: number
  /** Seconds of trail behind the head. */
  trail: number
  opacity: number
}

const ORBITS: Orbit[] = [
  { period: 16, dir: 1, radius: 0.27, wobble: 0.18, lift: 0.04, liftSwing: 0.03, phase: 0, trail: 7, opacity: 0.9 },
  { period: 21, dir: -1, radius: 0.36, wobble: 0.2, lift: 0.07, liftSwing: 0.05, phase: 2.4, trail: 7.5, opacity: 0.75 },
  { period: 12.5, dir: 1, radius: 0.17, wobble: 0.3, lift: 0.12, liftSwing: 0.04, phase: 4.3, trail: 5, opacity: 0.8 },
]

/**
 * Home page ribbon colours (the intro page keeps DEFAULT_RIBBON_COLORS).
 * A light leaf green, close to the space image's scent glows.
 */
const HOME_RIBBON_COLORS: RibbonColors = {
  fill: 'rgba(140, 172, 88, 0.09)',
  line: '#7f9a52',
  deep: '#5d7a38',
  soft: '#c9dba6',
}

/** Where the diffuser stands, as a fraction of the scene size (centre of the floor glow). */
const CENTER = { x: 0.481, y: 0.51 }
/** Vertical squash of the floor in the space image. */
const FLOOR_SQUASH = 0.4
const SAMPLES = 180
/** Time shown on the first frame, so the ribbons start out fully drawn. */
const START_TIME = 12

interface Trail extends RibbonPath {
  /** Toward the viewer (positive) or away from them, at each point. */
  depth: Float32Array
}

function makeTrail(): Trail {
  return {
    xs: new Float32Array(SAMPLES),
    ys: new Float32Array(SAMPLES),
    nxs: new Float32Array(SAMPLES),
    nys: new Float32Array(SAMPLES),
    at: new Float32Array(SAMPLES),
    spread: new Float32Array(SAMPLES),
    depth: new Float32Array(SAMPLES),
  }
}

/** Head position at time t, in scene widths from the centre, plus its depth. */
function orbitAt(o: Orbit, t: number) {
  const angle = o.phase + (o.dir * 2 * Math.PI * t) / o.period + 0.35 * Math.sin(t * 0.23 + o.phase)
  const r = o.radius * (1 + o.wobble * Math.sin(t * 0.41 + o.phase * 1.7))
  const h = o.lift + o.liftSwing * Math.sin(t * 0.29 + o.phase)
  const z = Math.sin(angle) * r
  return { x: Math.cos(angle) * r, y: z * FLOOR_SQUASH - h, depth: z }
}

/** Fills the trail (index 0 = oldest) for time t, in canvas pixels. */
function sampleTrail(trail: Trail, o: Orbit, t: number, cx: number, cy: number, w: number, spread: number) {
  const { xs, ys, at, depth } = trail
  for (let k = 0; k < SAMPLES; k++) {
    const p = orbitAt(o, t - o.trail * (1 - k / (SAMPLES - 1)))
    xs[k] = cx + p.x * w
    ys[k] = cy + p.y * w
    depth[k] = p.depth
    // Older scent has spread out a little more.
    trail.spread[k] = spread * (1.25 - 0.45 * (k / (SAMPLES - 1)))
    at[k] = k === 0 ? 0 : at[k - 1] + Math.hypot(xs[k] - xs[k - 1], ys[k] - ys[k - 1])
  }
  fillNormals(xs, ys, trail.nxs, trail.nys)
}

export function useWanderingRibbons(
  scene: RefObject<HTMLElement | null>,
  back: RefObject<HTMLCanvasElement | null>,
  front: RefObject<HTMLCanvasElement | null>,
) {
  useEffect(() => {
    const sceneEl = scene.current
    const backEl = back.current
    const frontEl = front.current
    if (!sceneEl || !backEl || !frontEl) return
    const layers = [backEl.getContext('2d')!, frontEl.getContext('2d')!]
    const trails = ORBITS.map(makeTrail)
    const still = window.matchMedia('(prefers-reduced-motion: reduce)')

    let dpr = 1
    let width = 0
    let height = 0
    // Scene geometry inside the canvases, which overhang the scene.
    let cx = 0
    let cy = 0
    let sceneWidth = 0
    let frame = 0
    const t0 = performance.now()

    const draw = (now: number) => {
      const t = START_TIME + (still.matches ? 0 : (now - t0) / 1000)
      for (const ctx of layers) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, width, height)
      }
      const spread = Math.max(10, sceneWidth * 0.022)
      const dim = window.innerWidth < 760 ? 0.75 : 1
      ORBITS.forEach((o, i) => {
        const trail = trails[i]
        sampleTrail(trail, o, t, cx, cy, sceneWidth, spread)
        const last = SAMPLES - 1
        const head = trail.at[last]
        const view = { first: 0, last, head, length: head, opacity: o.opacity * dim, colors: HOME_RIBBON_COLORS }
        const facing = (k0: number, k1: number) => trail.depth[(k0 + k1) >> 1] >= 0
        drawRibbon(layers[0], trail, { ...view, only: (k0, k1) => !facing(k0, k1) })
        drawRibbon(layers[1], trail, { ...view, only: facing })
      })
    }

    const tick = (now: number) => {
      draw(now)
      frame = still.matches ? 0 : requestAnimationFrame(tick)
    }

    const layout = () => {
      const s = sceneEl.getBoundingClientRect()
      const c = backEl.getBoundingClientRect()
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = c.width
      height = c.height
      for (const canvas of [backEl, frontEl]) {
        canvas.width = Math.round(width * dpr)
        canvas.height = Math.round(height * dpr)
      }
      sceneWidth = s.width
      cx = s.left - c.left + s.width * CENTER.x
      cy = s.top - c.top + s.height * CENTER.y
      if (!frame) draw(performance.now())
    }

    const restart = () => {
      cancelAnimationFrame(frame)
      frame = 0
      tick(performance.now())
    }

    layout()
    restart()
    const observer = new ResizeObserver(layout)
    observer.observe(sceneEl)
    still.addEventListener('change', restart)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      still.removeEventListener('change', restart)
    }
  }, [scene, back, front])
}
