// Drawing of the translucent scent ribbon, styled after the logo's "A"
// monogram: a faint band between two edge fibres, with thinner fibres of
// varied width and tone inside it. The band twists as a whole along its
// length and fades toward the tail. Shared by the intro page's scroll ribbon
// (ScentLines) and the home page's wandering ribbons (HomeRibbons).

interface Fiber {
  /** Resting position across the ribbon, -1 to 1. */
  base: number
  width: number
  alpha: number
  tone: keyof Omit<RibbonColors, 'fill'>
  /** Slight independent waviness so the fibres don't read as ruled lines. */
  waveFreq: number
  wavePhase: number
}

/** Ribbon colours; each fibre's own opacity is applied on top. */
export interface RibbonColors {
  /** Translucent band between the edge fibres (include its alpha). */
  fill: string
  /** Edge fibres and most inner fibres. */
  line: string
  /** A few thin, darker inner fibres. */
  deep: string
  /** Wide, pale inner fibres. */
  soft: string
}

/** The logo's greys; used unless a ribbon passes its own colours. */
export const DEFAULT_RIBBON_COLORS: RibbonColors = {
  fill: 'rgba(78, 83, 76, 0.07)',
  line: '#4e534c',
  deep: '#1f281e',
  soft: '#b2b7ad',
}

/** A centre line sampled from tail (index 0) to head. */
export interface RibbonPath {
  xs: Float32Array
  ys: Float32Array
  /** Unit normal at each point. */
  nxs: Float32Array
  nys: Float32Array
  /** Distance along the line from index 0, in CSS pixels. */
  at: Float32Array
  /** Ribbon half-width allowed at each point, in CSS pixels. */
  spread: Float32Array
}

export interface RibbonView {
  /** First and last path index to draw. */
  first: number
  last: number
  /** Position of the ribbon's head along the path (same units as `at`). */
  head: number
  /** Ribbon length behind the head. */
  length: number
  opacity: number
  /** Vertical shift applied to every point, e.g. minus the scroll offset. */
  dy?: number
  /** Draws only the chunks (index ranges) this accepts; used to split a ribbon across layers. */
  only?: (k0: number, k1: number) => boolean
  colors?: RibbonColors
}

/** Ribbon length between two full twists. */
const TWIST_PERIOD = 420
const CHUNK = 12

// Edge fibres outline the band like the logo's ribbon edges; inner fibres vary
// in width and tone to give it depth.
const FIBERS: Fiber[] = [
  { base: -1, width: 1.1, alpha: 0.55, tone: 'line', waveFreq: 0, wavePhase: 0 },
  { base: 1, width: 1.1, alpha: 0.55, tone: 'line', waveFreq: 0, wavePhase: 0 },
  { base: -0.72, width: 0.4, alpha: 0.45, tone: 'deep', waveFreq: 2.1, wavePhase: 0.4 },
  { base: -0.5, width: 2.4, alpha: 0.16, tone: 'soft', waveFreq: 1.3, wavePhase: 1.9 },
  { base: -0.3, width: 0.6, alpha: 0.38, tone: 'line', waveFreq: 2.7, wavePhase: 2.6 },
  { base: -0.08, width: 1.6, alpha: 0.2, tone: 'soft', waveFreq: 1.7, wavePhase: 3.3 },
  { base: 0.12, width: 0.35, alpha: 0.5, tone: 'line', waveFreq: 3.1, wavePhase: 0.9 },
  { base: 0.34, width: 0.9, alpha: 0.3, tone: 'line', waveFreq: 2.3, wavePhase: 4.1 },
  { base: 0.55, width: 2.8, alpha: 0.14, tone: 'soft', waveFreq: 1.1, wavePhase: 5.0 },
  { base: 0.78, width: 0.5, alpha: 0.42, tone: 'deep', waveFreq: 2.9, wavePhase: 5.7 },
]

export function clamp01(t: number) {
  return Math.min(1, Math.max(0, t))
}

export function smoothstep(t: number) {
  const c = clamp01(t)
  return c * c * (3 - 2 * c)
}

/** Unit normals from neighbouring points, written into `nxs`/`nys`. */
export function fillNormals(xs: ArrayLike<number>, ys: ArrayLike<number>, nxs: Float32Array, nys: Float32Array) {
  const count = xs.length
  for (let k = 0; k < count; k++) {
    const a = Math.max(0, k - 1)
    const c = Math.min(count - 1, k + 1)
    const tx = xs[c] - xs[a]
    const ty = ys[c] - ys[a]
    const len = Math.hypot(tx, ty) || 1
    nxs[k] = -ty / len
    nys[k] = tx / len
  }
}

export function drawRibbon(ctx: CanvasRenderingContext2D, path: RibbonPath, view: RibbonView) {
  const { first, last, head, length: ribbon, opacity, dy = 0, only, colors = DEFAULT_RIBBON_COLORS } = view
  if (last - first < 2) return
  const { xs, ys, nxs, nys, at, spread } = path

  // Offset of a fibre at path index k: the band twists as a whole (cos of the
  // twist angle), so all fibres pinch together at each twist.
  const offset = (k: number, f: Fiber) => {
    const fromHead = head - at[k]
    const r = clamp01(fromHead / ribbon) // 0 at the head, 1 at the tail
    const halfWidth = spread[k] * smoothstep(r / 0.08) * (0.45 + 0.55 * smoothstep((1 - r) / 0.35))
    const twist = Math.cos((fromHead / TWIST_PERIOD) * Math.PI * 2 + 0.6)
    const wave = f.waveFreq ? 0.12 * Math.sin((fromHead / 160) * f.waveFreq + f.wavePhase) : 0
    return halfWidth * (f.base * (0.12 + 0.88 * twist) + wave)
  }
  const fade = (k0: number, k1: number) => {
    const r = clamp01((head - (at[k0] + at[k1]) / 2) / ribbon)
    return opacity * Math.pow(1 - r, 0.8)
  }

  // Translucent band between the two edge fibres.
  ctx.fillStyle = colors.fill
  for (let c0 = first; c0 < last; c0 += CHUNK) {
    const c1 = Math.min(last, c0 + CHUNK)
    if (only && !only(c0, c1)) continue
    ctx.globalAlpha = fade(c0, c1)
    ctx.beginPath()
    for (let k = c0; k <= c1; k++) {
      const off = offset(k, FIBERS[0])
      const x = xs[k] + nxs[k] * off
      const y = ys[k] + nys[k] * off + dy
      if (k === c0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    for (let k = c1; k >= c0; k--) {
      const off = offset(k, FIBERS[1])
      ctx.lineTo(xs[k] + nxs[k] * off, ys[k] + nys[k] * off + dy)
    }
    ctx.closePath()
    ctx.fill()
  }

  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const f of FIBERS) {
    ctx.strokeStyle = colors[f.tone]
    ctx.lineWidth = f.width
    for (let c0 = first; c0 < last; c0 += CHUNK) {
      const c1 = Math.min(last, c0 + CHUNK)
      if (only && !only(c0, c1)) continue
      ctx.globalAlpha = f.alpha * fade(c0, c1)
      ctx.beginPath()
      for (let k = c0; k <= c1; k++) {
        const off = offset(k, f)
        const x = xs[k] + nxs[k] * off
        const y = ys[k] + nys[k] * off + dy
        if (k === c0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
}
