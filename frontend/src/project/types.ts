// Browser-owned project document, saved locally (backend README: "Browser data
// ownership"). One project holds one floor plan; scenarios try different
// diffuser layouts on it. Objects that the backend also defines keep its
// snake_case shapes so they can be submitted unchanged; the rest is camelCase.

import { normalizeScent } from '../diffusers/scents.ts'
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
  /** Fans and air conditioners, placed in the workspace like diffusers. */
  airflow_devices: AirflowDevice[]
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

/** Mirrors backend simulations.models.AirflowDevice, positioned in image pixels. */
export interface AirflowDevice {
  id: string
  type: 'fan' | 'ac'
  position: PixelPoint
  /** Direction the air blows toward, in degrees clockwise from image right (0 right, 90 down). */
  direction_degrees: number
  strength: AirflowStrength
}

export const AIRFLOW_STRENGTHS = ['low', 'medium', 'high'] as const
export type AirflowStrength = (typeof AIRFLOW_STRENGTHS)[number]

/** Backend AirflowSettings.devices max_length, per scenario. */
export const MAX_AIRFLOW_DEVICES = 8

export const OUTDOOR_CONDITIONS = ['calm', 'moderate', 'breezy'] as const
export type OutdoorConditions = (typeof OUTDOOR_CONDITIONS)[number]

/**
 * How much the room air mixes on its own (people moving, heating, natural
 * drafts): backend settings.mixing_preset. Medium is the backend default.
 */
export const MIXING_PRESETS = ['low', 'medium', 'high'] as const
export type MixingPreset = (typeof MIXING_PRESETS)[number]

/** Outside weather, mirroring backend AirflowSettings.outdoor_conditions and wind direction. */
export interface Outdoor {
  conditions: OutdoorConditions
  /** Direction the wind travels toward, degrees clockwise from image right. */
  wind_direction_degrees: number
}

/** Space setup runs in this order between the diffuser page and the workspace. */
export const SETUP_STEPS = ['thickness', 'calibration', 'indoor'] as const
export type SetupStep = (typeof SETUP_STEPS)[number]

export type ProjectStep = 'diffusers' | SetupStep | 'workspace'

/** Selectable simulation lengths; the backend allows up to 6 hours. */
export const SIMULATION_HOURS = [1, 2, 3, 4, 5, 6] as const
export type SimulationHours = (typeof SIMULATION_HOURS)[number]

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
  /** Simulated duration for every scenario, so their results compare. */
  simulationHours: SimulationHours
  /** Outside weather for every scenario. */
  outdoor: Outdoor
  /** Indoor air mixing for every scenario. Background ventilation stays at the backend default. */
  mixing: MixingPreset
  /** Furthest page reached, where "continue" resumes. */
  step: ProjectStep
}

export function createScenario(name: string, from?: Scenario): Scenario {
  return {
    id: crypto.randomUUID(),
    name,
    placements: from ? from.placements.map((p) => ({ ...p, id: crypto.randomUUID() })) : [],
    opening_states: from ? from.opening_states.map((s) => ({ ...s })) : [],
    airflow_devices: from ? from.airflow_devices.map((d) => ({ ...d, id: crypto.randomUUID() })) : [],
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
    simulationHours: 1,
    outdoor: { conditions: 'calm', wind_direction_degrees: 0 },
    mixing: 'medium',
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
  // A setup step that no longer exists resumes at the workspace.
  let step: ProjectStep = (SETUP_STEPS as readonly string[]).includes(doc.step) || doc.step === 'diffusers' ? doc.step : 'workspace'
  if (!doc.recognition) step = 'diffusers'
  else if (step === 'workspace' || step === 'indoor') {
    if (!calibration) step = 'calibration'
    else if (step === 'workspace' && !indoor) step = 'indoor'
  }
  const simulationHours = SIMULATION_HOURS.includes(doc.simulationHours) ? doc.simulationHours : 1
  const outdoor = doc.outdoor ?? { conditions: 'calm', wind_direction_degrees: 0 }
  const mixing = MIXING_PRESETS.includes(doc.mixing) ? doc.mixing : 'medium'
  const scenarios = doc.scenarios.map((s) => ({ ...s, airflow_devices: s.airflow_devices ?? [] }))
  const diffusers = doc.diffusers.map((d) => ({ ...d, scentFamily: normalizeScent(d.scentFamily) }))
  return { ...doc, calibration, indoor, simulationHours, outdoor, mixing, scenarios, diffusers, step }
}

/** Next unused "배치안 N" name. */
export function nextScenarioName(scenarios: Scenario[]): string {
  const used = new Set(scenarios.map((s) => s.name))
  let n = scenarios.length + 1
  while (used.has(`배치안 ${n}`)) n++
  return `배치안 ${n}`
}
