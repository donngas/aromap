// Browser-owned project document, saved locally (backend README: "Browser data
// ownership"). One project holds one floor plan; scenarios try different
// diffuser layouts on it. Objects that the backend also defines keep its
// snake_case shapes so they can be submitted unchanged; the rest is camelCase.

import type { DiffuserDraft } from '../diffusers/types.ts'
import type { Layout, PixelPoint } from '../floorPlan/layout.ts'

export const PROJECT_SCHEMA_VERSION = 1

/** Mirrors backend simulations.models.DiffuserPlacement. */
export interface DiffuserPlacement {
  id: string
  definition_id: string
  position: PixelPoint
  strength_override: number | null
  enabled: boolean
}

/** Mirrors backend simulations.models.OpeningState; omitted openings count as closed. */
export interface OpeningState {
  opening_id: string
  is_open: boolean
}

/** One arrangement to compare; becomes one backend SimulationConfiguration. */
export interface Scenario {
  id: string
  name: string
  placements: DiffuserPlacement[]
  opening_states: OpeningState[]
}

/**
 * Scale reference: the user picks one recognized wall and enters its real
 * length. start/end are that wall's endpoints, matching the backend's
 * ScaleCalibration; wall_id records which wall was chosen.
 */
export interface WallCalibration {
  wall_id: string
  start: PixelPoint
  end: PixelPoint
  distance_m: number
}

/** Indoor footprint in image pixels; converted to meters for simulation requests. */
export interface IndoorBoundary {
  boundary: PixelPoint[]
  holes: PixelPoint[][]
}

/** Space setup runs in this order between the diffuser page and the workspace. */
export const SETUP_STEPS = ['thickness', 'calibration', 'indoor'] as const
export type SetupStep = (typeof SETUP_STEPS)[number]

export type ProjectStep = 'diffusers' | SetupStep | 'workspace'

export interface ProjectDocument {
  schemaVersion: typeof PROJECT_SCHEMA_VERSION
  id: string
  createdAt: string
  /** Set on every save. */
  updatedAt: string
  /** The backend-prepared PNG is stored separately under the project id. */
  plan: { fileName: string; width: number; height: number }
  /** Shared by every scenario; null until recognition succeeds. */
  recognition: { layout: Layout; warnings: string[] } | null
  /** Diffuser products, shared by every scenario. */
  diffusers: DiffuserDraft[]
  scenarios: Scenario[]
  activeScenarioId: string
  /** Null until set in space setup. */
  calibration: WallCalibration | null
  indoor: IndoorBoundary | null
  /** Display-only settings. wallThickness null means the default for the image. */
  view: { wallThickness: number | null; showImage: boolean }
  /** Furthest page reached, where "continue" resumes. */
  step: ProjectStep
}

export function createScenario(name: string, from?: Scenario): Scenario {
  return {
    id: crypto.randomUUID(),
    name,
    placements: from ? from.placements.map((p) => ({ ...p, id: crypto.randomUUID() })) : [],
    opening_states: from ? from.opening_states.map((s) => ({ ...s })) : [],
  }
}

export function createProject(plan: ProjectDocument['plan']): ProjectDocument {
  const now = new Date().toISOString()
  const scenario = createScenario('배치안 1')
  return {
    schemaVersion: PROJECT_SCHEMA_VERSION,
    id: crypto.randomUUID(),
    createdAt: now,
    updatedAt: now,
    plan,
    recognition: null,
    diffusers: [],
    scenarios: [scenario],
    activeScenarioId: scenario.id,
    calibration: null,
    indoor: null,
    view: { wallThickness: null, showImage: true },
    step: 'diffusers',
  }
}

/**
 * Brings documents saved by earlier builds up to date: fills fields added later
 * and never resumes past a setup step whose data is missing.
 */
export function normalizeProject(doc: ProjectDocument): ProjectDocument {
  const calibration = doc.calibration ?? null
  const indoor = doc.indoor ?? null
  let step = doc.step
  if (!doc.recognition) step = 'diffusers'
  else if (step === 'workspace' || step === 'indoor') {
    if (!calibration) step = 'calibration'
    else if (step === 'workspace' && !indoor) step = 'indoor'
  }
  return { ...doc, calibration, indoor, step }
}

/** Next unused "배치안 N" name. */
export function nextScenarioName(scenarios: Scenario[]): string {
  const used = new Set(scenarios.map((s) => s.name))
  let n = scenarios.length + 1
  while (used.has(`배치안 ${n}`)) n++
  return `배치안 ${n}`
}
