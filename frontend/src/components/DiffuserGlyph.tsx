import { GLYPHS } from '../diffusers/glyphs.ts'
import type { DiffuserType } from '../diffusers/types.ts'

interface DiffuserGlyphProps {
  type: DiffuserType
  /** Scent colour; the icon follows it. */
  color: string
  size?: number
  className?: string
}

/** The diffuser type's line icon, tinted with its scent colour. */
export function DiffuserGlyph({ type, color, size = 24, className }: DiffuserGlyphProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 128 128"
      fill="none"
      style={{ color }}
      aria-hidden="true"
    >
      {GLYPHS[type].map((part, i) =>
        part.fill ? (
          <path key={i} d={part.d} fill="currentColor" opacity={part.opacity} />
        ) : (
          <path
            key={i}
            d={part.d}
            stroke="currentColor"
            strokeWidth={part.width}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={part.opacity}
          />
        ),
      )}
    </svg>
  )
}
