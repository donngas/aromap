import { useEffect, useRef, type RefObject } from 'react'
import { clamp01, drawRibbon, fillNormals, type RibbonPath } from './ribbon.ts'

// A translucent scent ribbon, styled after the logo's "A" monogram, that moves
// only with scrolling. The logo's own sphere (cut out of the mark and drawn
// here) rolls off and pulls the ribbon along a fixed track: soft curves down
// the left of the explanation, then into the start button's left edge. The
// same scroll position always draws the same picture. Once the sphere reaches
// the button, further scrolling draws the rest of the ribbon in and reports
// the absorbed share through --absorb.

/** The logo's sphere as a separate image. */
export interface PearlSprite {
  src: string
  /** Sprite width relative to the mark image width. */
  widthRatio: number
  /** Sphere centre inside the sprite, as a fraction of the sprite size. */
  centerX: number
  centerY: number
}

interface ScentLinesProps {
  /** Logo mark image the sphere starts from. */
  origin: RefObject<HTMLImageElement | null>
  /** Centre of the logo's sphere, as a fraction of the mark image size. */
  originPoint: { x: number; y: number }
  pearl: PearlSprite
  ctaSection: RefObject<HTMLElement | null>
  ctaAnchor: RefObject<HTMLElement | null>
}

interface Track extends RibbonPath {
  /** Total length; the end sits just inside the button. */
  length: number
  /** Ribbon length behind the pearl. */
  ribbon: number
  /** Scroll offset at which the pearl reaches each point. */
  keys: Float32Array
  /** Scroll offset at which the pearl reaches the button. */
  keyEnd: number
  /** Scroll offset at which the ribbon is fully absorbed. */
  absorbEnd: number
  /** Rendered sphere sprite width, matching the mark's current size. */
  pearlWidth: number
  /** Overall ribbon opacity; lower on phones, where it passes behind the text. */
  opacity: number
}

const STEP = 3
const NARROW_WIDTH = 760
/** Each pixel of mostly horizontal track still costs this much scroll. */
const MIN_SCROLL_PER_PX = 0.35

interface RawPoint {
  x: number
  y: number
  spread: number
}

function catmullRom(p0: number, p1: number, p2: number, p3: number, t: number) {
  const t2 = t * t
  const t3 = t2 * t
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
}

function pageRect(el: HTMLElement) {
  const r = el.getBoundingClientRect()
  return { left: r.left + window.scrollX, top: r.top + window.scrollY, width: r.width, height: r.height }
}

function buildTrack(
  mark: HTMLImageElement,
  point: { x: number; y: number },
  pearlWidthRatio: number,
  ctaSection: HTMLElement,
  button: HTMLElement,
): Track {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const narrow = vw < NARROW_WIDTH
  const m = pageRect(mark)
  const cta = pageRect(ctaSection)
  const b = pageRect(button)
  const sx = m.left + m.width * point.x
  const sy = m.top + m.height * point.y

  // The pearl rolls off to the right like the logo's ribbon tail, then the
  // ribbon sweeps back left and drifts down in wide, gentle curves.
  const controls: RawPoint[] = [
    { x: sx - 1, y: sy - 1, spread: 20 },
    { x: sx, y: sy, spread: 20 },
    // Wide enough on desktop to clear the wordmark's last letters.
    { x: sx + vw * (narrow ? 0.06 : 0.1), y: sy + vh * 0.12, spread: 22 },
    { x: sx - vw * 0.04, y: sy + vh * 0.3, spread: 24 },
    { x: vw * (narrow ? 0.3 : 0.22), y: sy + vh * 0.5, spread: 24 },
  ]
  const xs = narrow ? [0.62, 0.28, 0.7, 0.32] : [0.14, 0.26, 0.15, 0.24, 0.17]
  const by = b.top + b.height / 2
  const approachY = by - vh * 0.14
  for (let i = 0, y = sy + vh * 0.95; y < Math.min(cta.top + vh * 0.1, approachY - vh * 0.18); i++, y += vh * 0.45) {
    controls.push({ x: vw * xs[i % xs.length], y, spread: 24 })
  }
  // Keep the approach on screen; on phones the button sits close to the left edge.
  controls.push({ x: Math.max(vw * 0.06, b.left - b.width * 1.5), y: approachY, spread: 14 })
  controls.push({ x: Math.max(vw * 0.03, b.left - b.width * 0.45), y: by - 3, spread: 6 })
  controls.push({ x: b.left + 2, y: by, spread: 1.5 })

  const raw: RawPoint[] = []
  for (let i = 1; i < controls.length - 1; i++) {
    const p0 = controls[i - 1]
    const p1 = controls[i]
    const p2 = controls[i + 1]
    const p3 = controls[Math.min(controls.length - 1, i + 2)]
    for (let s = i === 1 ? 0 : 1; s <= 32; s++) {
      const t = s / 32
      raw.push({
        x: catmullRom(p0.x, p1.x, p2.x, p3.x, t),
        y: catmullRom(p0.y, p1.y, p2.y, p3.y, t),
        spread: p1.spread + (p2.spread - p1.spread) * t,
      })
    }
  }

  // Resample at a fixed spacing so positions along the track are plain indices.
  const outX = [raw[0].x]
  const outY = [raw[0].y]
  const outS = [raw[0].spread]
  let travelled = 0
  let nextAt = STEP
  for (let i = 1; i < raw.length; i++) {
    const a = raw[i - 1]
    const c = raw[i]
    const seg = Math.hypot(c.x - a.x, c.y - a.y)
    while (seg > 0 && nextAt <= travelled + seg) {
      const t = (nextAt - travelled) / seg
      outX.push(a.x + (c.x - a.x) * t)
      outY.push(a.y + (c.y - a.y) * t)
      outS.push(a.spread + (c.spread - a.spread) * t)
      nextAt += STEP
    }
    travelled += seg
  }
  const count = outX.length

  const nxs = new Float32Array(count)
  const nys = new Float32Array(count)
  fillNormals(outX, outY, nxs, nys)
  const at = new Float32Array(count)
  for (let k = 0; k < count; k++) at[k] = k * STEP

  // Scroll keys: the pearl keeps its starting viewport height while it
  // descends, and mostly horizontal stretches still advance with scrolling.
  const keys = new Float32Array(count)
  for (let k = 1; k < count; k++) {
    keys[k] = Math.max(keys[k - 1] + STEP * MIN_SCROLL_PER_PX, outY[k] - sy)
  }
  const maxScroll = Math.max(0, document.documentElement.scrollHeight - vh)
  const minAbsorb = vh * 0.35
  let keyEnd = keys[count - 1]
  if (keyEnd > maxScroll - minAbsorb) {
    const factor = Math.max(0, maxScroll - minAbsorb) / keyEnd
    for (let k = 0; k < count; k++) keys[k] *= factor
    keyEnd = keys[count - 1]
  }

  return {
    xs: Float32Array.from(outX),
    ys: Float32Array.from(outY),
    nxs,
    nys,
    at,
    spread: Float32Array.from(outS),
    length: (count - 1) * STEP,
    ribbon: Math.min(vh * 1.1, 1000),
    keys,
    keyEnd,
    absorbEnd: Math.max(keyEnd + 1, maxScroll - 24),
    pearlWidth: m.width * pearlWidthRatio,
    opacity: narrow ? 0.5 : 1,
  }
}

/** Pearl position on the track; past `length` means the ribbon is partly absorbed. */
function headAt(track: Track, scroll: number): number {
  if (scroll <= 0) return 0
  if (scroll <= track.keyEnd) {
    const { keys } = track
    let lo = 0
    let hi = keys.length - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (keys[mid] <= scroll) lo = mid
      else hi = mid
    }
    const span = keys[hi] - keys[lo]
    const t = span > 0 ? (scroll - keys[lo]) / span : 0
    return (lo + t) * STEP
  }
  const absorbed = clamp01((scroll - track.keyEnd) / (track.absorbEnd - track.keyEnd))
  return track.length + track.ribbon * absorbed
}

export function ScentLines({ origin, originPoint, pearl, ctaSection, ctaAnchor }: ScentLinesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { x: pointX, y: pointY } = originPoint
  const { src: pearlSrc, widthRatio: pearlRatio, centerX: pearlCX, centerY: pearlCY } = pearl

  useEffect(() => {
    const canvas = canvasRef.current
    const mark = origin.current
    const section = ctaSection.current
    const button = ctaAnchor.current
    if (!canvas || !mark || !section || !button) return
    const ctx = canvas.getContext('2d')!

    let width = 0
    let height = 0
    let dpr = 1
    let track: Track | null = null
    let pending = 0
    const sphere = new Image()
    sphere.src = pearlSrc

    const draw = () => {
      pending = 0
      if (!track) return
      const scroll = window.scrollY
      const head = headAt(track, scroll)
      const ribbon = track.ribbon
      const absorbed = clamp01((head - track.length) / ribbon)
      button.style.setProperty('--absorb', absorbed.toFixed(3))
      button.classList.toggle('is-charged', absorbed >= 0.999)

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, height)
      const first = Math.max(0, Math.ceil((head - ribbon) / STEP))
      const last = Math.min(track.xs.length - 1, Math.floor(head / STEP))

      drawRibbon(ctx, track, { first, last, head, length: ribbon, opacity: track.opacity, dy: -scroll })

      // The logo's sphere leads the ribbon; at the top of the page it sits
      // exactly in its place in the mark, and it disappears into the button.
      if (head < track.length && sphere.complete && sphere.naturalWidth > 0) {
        const k = Math.min(track.xs.length - 1, Math.round(head / STEP))
        const w = track.pearlWidth
        const h = w * (sphere.naturalHeight / sphere.naturalWidth)
        ctx.globalAlpha = 1
        ctx.drawImage(sphere, track.xs[k] - w * pearlCX, track.ys[k] - scroll - h * pearlCY, w, h)
      }
      ctx.globalAlpha = 1
    }

    const schedule = () => {
      if (!pending) pending = requestAnimationFrame(draw)
    }

    const layout = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = window.innerWidth
      height = window.innerHeight
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      track = buildTrack(mark, { x: pointX, y: pointY }, pearlRatio, section, button)
      schedule()
    }

    layout()
    sphere.addEventListener('load', schedule)
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', layout)
    // Late layout shifts (web fonts, the logo image loading) move the anchors,
    // so rebuild then too.
    const observer = new ResizeObserver(layout)
    observer.observe(document.body)
    observer.observe(mark)

    return () => {
      cancelAnimationFrame(pending)
      sphere.removeEventListener('load', schedule)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', layout)
      observer.disconnect()
    }
  }, [origin, pointX, pointY, pearlSrc, pearlRatio, pearlCX, pearlCY, ctaSection, ctaAnchor])

  return <canvas ref={canvasRef} className="scent-lines" aria-hidden="true" />
}
