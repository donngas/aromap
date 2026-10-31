// Numbers for the "분석" window. Everything is in the backend's relative units
// (a surrogate for mg of consumed formulation per m²), so the figures compare
// arrangements, not perceived scent.

import { cellValues } from './heatmap.ts'
import type { SimulationField } from './run.ts'

/**
 * A cell counts as reached once this much has built up, in relative units per
 * m². Chosen so a single reed in a two-room 60 m² space reaches about half the
 * floor after an hour; it is a reading aid, not a perception threshold.
 */
export const COVERAGE_THRESHOLD = 1

/** Share (0–1) of indoor cells at or above the threshold at time index t. */
export function coverageAt(field: SimulationField, t: number): number {
  const values = new Float32Array(field.grid.rows * field.grid.columns)
  cellValues(field, t, null, values)
  let active = 0
  let reached = 0
  for (let i = 0; i < values.length; i++) {
    if (!field.mask[i]) continue
    active++
    if (values[i] >= COVERAGE_THRESHOLD) reached++
  }
  return active > 0 ? reached / active : 0
}
