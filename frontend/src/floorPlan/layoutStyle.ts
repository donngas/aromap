// How recognized geometry is drawn; shared by the viewer and its legend.
// Widths and radii without units in their name are screen pixels.

export const LAYOUT_STYLE = {
  wall: { color: '#1f281e' },
  /** Openings fill the wall band faintly and carry a centre line. */
  door: { color: '#3f5e43', band: 'rgba(63, 94, 67, 0.22)', line: 2.5 },
  /** A door opened for the simulation: lighter, with a dashed centre line. */
  openDoor: { color: '#7f9a52', band: 'rgba(201, 219, 166, 0.55)', line: 2.5, dash: 5 },
  window: { color: '#6f8fa8', band: 'rgba(111, 143, 168, 0.35)', line: 2.5 },
  /** The chosen (or hovered) calibration wall, drawn slightly wider than the wall. */
  selection: { color: '#c2873a', hover: 'rgba(194, 135, 58, 0.45)', outset: 6 },
  indoor: { fill: 'rgba(63, 94, 67, 0.12)', line: '#3f5e43', width: 2, vertexRadius: 6, midpointRadius: 4.5 },
  /** Placed diffusers: numbered dots; the selected one gets a ring. */
  marker: { fill: '#1f281e', text: '#f2f0ee', ring: '#7f9a52', radius: 11, ringRadius: 16, font: 11 },
} as const

/**
 * Display-only wall thickness in image pixels. Recognition returns zero-thickness
 * centre lines, so this only affects drawing, never the simulation.
 */
export function defaultWallThickness(width: number, height: number): number {
  return Math.max(2, Math.round(Math.max(width, height) * 0.012))
}

export function maxWallThickness(width: number, height: number): number {
  return Math.max(40, Math.round(Math.max(width, height) * 0.05))
}
