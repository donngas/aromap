// Line icons for each diffuser type (designs/01_reed.svg … 04_candle_wax.svg),
// as path data on a 128×128 grid so the same drawing serves the SVG icon and
// the plan canvas. Circles and rounded rectangles are written as paths.

import type { DiffuserType } from './types.ts'

export interface GlyphPart {
  d: string
  /** Stroke width on the 128 grid; ignored when filled. */
  width?: number
  fill?: boolean
  opacity?: number
}

const circle = (cx: number, cy: number, r: number) =>
  `M${cx - r} ${cy} A${r} ${r} 0 1 0 ${cx + r} ${cy} A${r} ${r} 0 1 0 ${cx - r} ${cy} Z`

export const GLYPHS: Record<DiffuserType, GlyphPart[]> = {
  reed: [
    { d: 'M55 43 35 12', width: 4.5 },
    { d: 'M61 43 53 9', width: 4.5 },
    { d: 'M67 43 77 9', width: 4.5 },
    { d: 'M73 43 94 12', width: 4.5 },
    {
      d: 'M50 45 H78 Q82 45 82 49 V55 Q82 58 79 58 H77 V65 H91 Q99 65 99 73 V107 Q99 115 91 115 H37 Q29 115 29 107 V73 Q29 65 37 65 H51 V58 H49 Q46 58 46 55 V49 Q46 45 50 45 Z',
      width: 4.5,
    },
    { d: 'M59 55 65 75 54 102', width: 4.5 },
    { d: 'M70 55 64 74 76 102', width: 4.5 },
  ],
  ultrasonic: [
    { d: 'M61 37 C52 28 61 23 66 16 C70 10 69 7 66 5', width: 4, opacity: 0.55 },
    { d: 'M77 37 C72 30 79 26 83 21 C87 16 86 12 83 10', width: 4, opacity: 0.55 },
    { d: 'M64 44 C88 44 105 62 108 81 C112 102 100 115 82 115 H46 C27 115 16 101 20 81 C24 62 41 44 64 44 Z', width: 4.5 },
    { d: 'M24 82 H104', width: 4.5 },
    { d: 'M61 44 H67', width: 4.5 },
    { d: 'M61 101 H67', width: 4.5 },
  ],
  nebulizer: [
    { d: circle(89, 14, 3.2), fill: true },
    { d: circle(101, 22, 2.7), fill: true },
    { d: circle(88, 31, 2.3), fill: true },
    { d: circle(108, 34, 2.7), fill: true },
    { d: circle(97, 43, 3.2), fill: true },
    { d: circle(83, 23, 2.3), fill: true },
    { d: 'M50 49 V27 Q50 24 53 24 H70 V49', width: 4.5 },
    { d: 'M49 49 H72 Q75 49 75 53 V57 H46 V53 Q46 49 49 49 Z', width: 4.5 },
    { d: 'M43 57 H79 A10 10 0 0 1 89 67 V105 A10 10 0 0 1 79 115 H43 A10 10 0 0 1 33 105 V67 A10 10 0 0 1 43 57 Z', width: 4.5 },
    { d: circle(61, 79, 5.5), width: 4.5 },
  ],
  candle: [
    { d: 'M64 53 C51 48 49 38 54 28 C57 21 63 16 64 12 C68 19 77 27 76 38 C75 47 71 51 64 53 Z', width: 4.5 },
    { d: 'M64 54 V65', width: 4.5 },
    { d: 'M51 64 C34 65 24 69 24 77 C24 85 41 89 64 89 C87 89 104 85 104 77 C104 69 93 65 77 64', width: 4.5 },
    { d: 'M24 77 V105 C24 114 42 119 64 119 C86 119 104 114 104 105 V77', width: 4.5 },
  ],
}

/** Draws a glyph centred on (x, y) at `size` units across, in the current transform. */
export function drawGlyph(
  ctx: CanvasRenderingContext2D,
  type: DiffuserType,
  x: number,
  y: number,
  size: number,
  color: string,
  lineScale = 1,
) {
  const k = size / 128
  ctx.save()
  ctx.translate(x - size / 2, y - size / 2)
  ctx.scale(k, k)
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const part of GLYPHS[type]) {
    const path = new Path2D(part.d)
    ctx.globalAlpha = part.opacity ?? 1
    if (part.fill) ctx.fill(path)
    else {
      ctx.lineWidth = (part.width ?? 4.5) * lineScale
      ctx.stroke(path)
    }
  }
  ctx.restore()
}
