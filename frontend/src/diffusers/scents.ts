// Scent families and their colour concept (designs/향색상.png). The colour
// tints the diffuser's icon everywhere and the scent it spreads in results.

export const SCENTS = [
  { label: '꽃향·플로럴', color: '#D995AD' },
  { label: '라벤더', color: '#AA98D1' },
  { label: '민트·아쿠아', color: '#86BDD8' },
  { label: '시트러스', color: '#E4BD72' },
  { label: '우디', color: '#BE9B7B' },
  { label: '허브·그린', color: '#9DB795' },
  { label: '머스크·파우더리', color: '#B5A6B8' },
  { label: '스위트·바닐라', color: '#E5A18B' },
] as const

/** Used until a scent family is picked. */
export const NO_SCENT_COLOR = '#8E948A'

const COLORS = new Map<string, string>(SCENTS.map((s) => [s.label, s.color]))

/** Earlier builds offered these names. */
const LEGACY: Record<string, string> = { 플로럴: '꽃향·플로럴', 스위트: '스위트·바닐라' }

export function scentColor(family: string | null): string {
  return (family && COLORS.get(family)) || NO_SCENT_COLOR
}

/** Maps a saved family to a current one; unknown names (e.g. "기타") become none. */
export function normalizeScent(family: string | null): string | null {
  if (!family) return null
  const name = LEGACY[family] ?? family
  return COLORS.has(name) ? name : null
}

export type Rgb = [number, number, number]

export function hexToRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Mix of two colours, t = 0 gives a, 1 gives b. */
export function mixRgb(a: Rgb, b: Rgb, t: number): Rgb {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

const WHITE: Rgb = [255, 255, 255]
const BLACK: Rgb = [0, 0, 0]

/** A scent's concentration shade: a pale tint at low levels, slightly deeper than the base at the top. */
export function scentShade(base: Rgb, level: number): Rgb {
  return mixRgb(mixRgb(base, WHITE, 0.62), mixRgb(base, BLACK, 0.18), level)
}

/** CSS gradient from low to high concentration for one scent colour. */
export function scentGradient(hex: string, alphaFrom = 0.35, alphaTo = 0.85): string {
  const base = hexToRgb(hex)
  const stop = (level: number, alpha: number) => {
    const [r, g, b] = scentShade(base, level).map(Math.round)
    return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(2)})`
  }
  return `linear-gradient(90deg, ${stop(0, alphaFrom)}, ${stop(0.5, (alphaFrom + alphaTo) / 2)}, ${stop(1, alphaTo)})`
}
