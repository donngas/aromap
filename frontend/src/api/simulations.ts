// Simulation endpoints (backend/README.md, "Simulation API"). Shapes mirror
// backend/app/simulations/models.py and schemas.py; every length is in meters.

import { ApiError, errorMessage, request, type JobState } from './floorPlans.ts'

export interface MetricPoint {
  x: number
  y: number
}

export interface MetricSegment {
  id: string
  start: MetricPoint
  end: MetricPoint
}

export interface MetricOpening extends MetricSegment {
  wall_id: string
}

/** Mirrors backend ConsumerDiffuserDefinition. */
export interface ConsumerDiffuserDefinition {
  id: string
  name: string
  diffuser_type: string
  capacity?: number
  capacity_unit?: 'ml' | 'g'
  lifetime_days?: number
  operating_hours_per_day?: number
  intensity?: string
  provenance: 'user' | 'example'
}

export interface SimulationRequest {
  client_request_id: string
  geometry_m: {
    indoor_domain: { boundary: MetricPoint[]; holes: MetricPoint[][] }
    walls: MetricSegment[]
    doors: MetricOpening[]
    windows: MetricOpening[]
  }
  diffuser_definitions: ConsumerDiffuserDefinition[]
  placements: {
    placement_id: string
    definition_id: string
    position_m: MetricPoint
    strength_override?: number
    enabled: boolean
  }[]
  opening_states: { opening_id: string; is_open: boolean }[]
  /** Sampling is left automatic; the backend keeps it within its sample limit. */
  settings: { duration_s: number }
}

export interface SimulationAccepted {
  job_id: string
  client_request_id: string
  status_url: string
}

export interface SimulationResult {
  run_id: string
  grid: {
    origin_m: MetricPoint
    cell_size_m: number
    rows: number
    columns: number
  }
  /** List order is the array's channel order. */
  channels: { channel_id: string; placement_id: string; definition_id: string }[]
  sample_times_s: number[]
  fields: {
    url: string
    encoding: string
    shape: [number, number, number, number]
  }
  resolved_assumptions: string[]
  warnings: string[]
  expires_at: string
}

export interface SimulationStatus {
  job_id: string
  client_request_id: string
  state: JobState
  result: SimulationResult | null
  error: { code: string; message: string } | null
}

const MESSAGES: Record<string, string> = {
  queue_full: '계산 요청이 많아요. 잠시 후 다시 시도해 주세요.',
  result_not_found: '계산 결과가 만료됐어요. 다시 시작해 주세요.',
  job_interrupted: '서버가 다시 시작돼 계산이 중단됐어요. 다시 시작해 주세요.',
  execution_timeout: '계산이 너무 오래 걸려 중단됐어요. 시뮬레이션 시간을 줄이거나 디퓨저 수를 줄여 주세요.',
  resource_limit: '공간이 너무 커서 계산할 수 없어요. 실측 길이가 맞는지 확인해 주세요.',
  empty_grid: '실내 영역이 너무 작아요. 실내 영역과 실측 길이를 확인해 주세요.',
  invalid_domain: '실내 영역 모양이 올바르지 않아요. 선이 서로 엇갈리지 않게 다시 그려 주세요.',
  invalid_wall: '실내 영역 밖으로 나간 벽이 있어요. 실내 영역을 다시 확인해 주세요.',
  invalid_wall_junction: '인식된 벽이 서로 겹쳐 있어 계산할 수 없어요.',
  invalid_opening: '문이나 창의 위치를 읽을 수 없어요.',
  overlapping_openings: '겹쳐 있는 문이나 창이 있어 계산할 수 없어요.',
  unsupported_open_window: '창문을 연 상태는 아직 계산할 수 없어요.',
  invalid_source: '디퓨저가 실내 밖이나 벽 위에 있어요. 위치를 조금 옮겨 주세요.',
  unresolved_source: '디퓨저가 벽에 너무 가까워요. 벽에서 조금 떨어뜨려 주세요.',
  no_sources: '디퓨저를 하나 이상 놓아 주세요.',
  invalid_emission: '디퓨저 제품 정보로 향의 양을 계산할 수 없어요. 용량과 사용 기간을 확인해 주세요.',
  simulation_failed: '시뮬레이션을 계산하지 못했어요.',
}

export function simulationErrorMessage(code: string, fallback?: string): string {
  return MESSAGES[code] ?? errorMessage(code, fallback)
}

export function submitSimulation(body: SimulationRequest): Promise<SimulationAccepted> {
  return request<SimulationAccepted>('/api/simulations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getSimulation(statusUrl: string): Promise<SimulationStatus> {
  return request<SimulationStatus>(statusUrl)
}

/** Downloads the NPZ field bundle of a finished run. */
export async function fetchSimulationFields(url: string): Promise<ArrayBuffer> {
  let response: Response
  try {
    response = await fetch(url, { cache: 'no-store' })
  } catch {
    throw new ApiError(0, 'network', errorMessage('network'))
  }
  if (!response.ok) throw new ApiError(response.status, 'result_not_found', simulationErrorMessage('result_not_found'))
  return response.arrayBuffer()
}
