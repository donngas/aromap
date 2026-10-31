// One simulation run: submit, poll the job, then download and unpack the
// fields. Playback works on the unpacked arrays locally.

import { ApiError } from '../api/floorPlans.ts'
import {
  fetchSimulationFields,
  getSimulation,
  simulationErrorMessage,
  submitSimulation,
  type SimulationRequest,
  type SimulationResult,
} from '../api/simulations.ts'
import { parseNpz } from './npz.ts'

const POLL_MS = 1000

export type RunPhase = 'submitting' | 'queued' | 'running' | 'downloading'

/** Unpacked result, laid out [time][channel][row][column] like the backend arrays. */
export interface SimulationField {
  grid: SimulationResult['grid']
  /** Placement ids in channel order. */
  placementIds: string[]
  times: number[]
  concentration: Float32Array
  /** 1 where the cell is usable indoor space. */
  mask: Uint8Array
  warnings: string[]
}

export async function runSimulation(
  request: SimulationRequest,
  onPhase: (phase: RunPhase) => void,
  signal: AbortSignal,
): Promise<SimulationField> {
  onPhase('submitting')
  const accepted = await submitSimulation(request)

  let result: SimulationResult | null = null
  while (!result) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    const status = await getSimulation(accepted.status_url)
    if (status.state === 'failed') {
      const code = status.error?.code ?? 'simulation_failed'
      throw new ApiError(0, code, simulationErrorMessage(code, status.error?.message))
    }
    if (status.state === 'succeeded') result = status.result
    else {
      onPhase(status.state)
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
    }
  }

  onPhase('downloading')
  const arrays = await parseNpz(await fetchSimulationFields(result.fields.url))
  const concentration = arrays.get('concentration')
  const mask = arrays.get('active_domain_mask')
  if (!(concentration?.data instanceof Float32Array) || !(mask?.data instanceof Uint8Array)) {
    throw new ApiError(0, 'simulation_failed', simulationErrorMessage('simulation_failed'))
  }
  return {
    grid: result.grid,
    placementIds: result.channels.map((c) => c.placement_id),
    times: result.sample_times_s,
    concentration: concentration.data,
    mask: mask.data,
    warnings: result.warnings,
  }
}
