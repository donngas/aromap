// Scent families with two colours each: `color` (designs/향색상.png) tints the
// diffuser's icon and marker; `spread` (designs/향퍼지는색상.png) is the light
// pastel the scent spreads in on the plan. 라벤더 and 스위트·바닐라 are not on
// the spread sheet; theirs follow the same pastel style.

export const SCENTS = [
  { label: '꽃향·플로럴', color: '#D995AD', spread: '#EFC9D8' },
  { label: '라벤더', color: '#AA98D1', spread: '#DCD1F4' },
  { label: '민트·아쿠아', color: '#86BDD8', spread: '#CFEAF8' },
  { label: '시트러스', color: '#E4BD72', spread: '#F7E9B5' },
  { label: '우디', color: '#BE9B7B', spread: '#F0DEC9' },
  { label: '허브·그린', color: '#9DB795', spread: '#DCEFD3' },
  { label: '머스크·파우더리', color: '#B5A6B8', spread: '#E2DBEE' },
  { label: '스위트·바닐라', color: '#E5A18B', spread: '#F8D9CC' },
] as const

/** Used until a scent family is picked. */
export const NO_SCENT_COLOR = '#8E948A'
export const NO_SCENT_SPREAD = '#CDD9C4'

const BY_LABEL = new Map<string, (typeof SCENTS)[number]>(SCENTS.map((s) => [s.label, s]))

/** Earlier builds offered these names. */
const LEGACY: Record<string, string> = { 플로럴: '꽃향·플로럴', 스위트: '스위트·바닐라' }

/** Icon and marker colour. */
export function scentColor(family: string | null): string {
  return (family && BY_LABEL.get(family)?.color) || NO_SCENT_COLOR
}

/** Colour the scent spreads in on the plan. */
export function spreadColor(family: string | null): string {
  return (family && BY_LABEL.get(family)?.spread) || NO_SCENT_SPREAD
}

/** Maps a saved family to a current one; unknown names (e.g. "기타") become none. */
export function normalizeScent(family: string | null): string | null {
  if (!family) return null
  const name = LEGACY[family] ?? family
  return BY_LABEL.has(name) ? name : null
}

export type Rgb = [number, number, number]

export function hexToRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/**
 * Concentration shade of a pastel spread colour. The pastel itself at low
 * levels; higher levels move it further from white (more of the same hue)
 * instead of toward black, so dense areas stay clean rather than muddy.
 */
export function spreadShade(base: Rgb, level: number): Rgb {
  const k = 1 + 1.1 * level
  return base.map((c) => Math.max(0, Math.min(255, 255 - (255 - c) * k))) as Rgb
}

/** Opacity of the spread at a concentration level (0–1). */
export function spreadAlpha(level: number): number {
  return Math.min(1, 0.3 + 0.65 * level * 1.25)
}

/** CSS gradient from low to high concentration for one spread colour, matching the plan. */
export function spreadGradient(hex: string): string {
  const base = hexToRgb(hex)
  const stop = (level: number) => {
    const [r, g, b] = spreadShade(base, level).map(Math.round)
    return `rgba(${r}, ${g}, ${b}, ${spreadAlpha(level).toFixed(2)})`
  }
  return `linear-gradient(90deg, ${stop(0)}, ${stop(0.5)}, ${stop(1)})`
}
