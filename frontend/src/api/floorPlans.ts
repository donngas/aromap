// Floor-plan endpoints (backend/README.md, "Frontend contract"). Paths are
// relative so the Vite/Nginx proxy forwards them to the backend.

import type { RecognitionDraft } from '../floorPlan/layout.ts'

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const MESSAGES: Record<string, string> = {
  image_too_large: '이미지가 너무 커요. 10MB 이하의 이미지를 올려 주세요.',
  unsupported_image: 'PNG, JPG, WebP 이미지만 올릴 수 있어요.',
  animated_image: '움직이는 이미지는 올릴 수 없어요.',
  invalid_image: '이미지를 읽을 수 없어요. 다른 파일로 시도해 주세요.',
  image_not_found: '올린 이미지가 만료됐어요. 평면도를 다시 올려 주세요.',
  job_not_found: '분석 작업이 만료됐어요. 다시 분석해 주세요.',
  queue_full: '분석 요청이 많아요. 잠시 후 다시 시도해 주세요.',
  recognition_unavailable: '평면도 분석 기능이 아직 켜져 있지 않아요.',
  recognition_failed: '평면도를 분석하지 못했어요.',
  job_interrupted: '서버가 다시 시작돼 분석이 중단됐어요. 다시 분석해 주세요.',
  network: '서버에 연결할 수 없어요. 백엔드가 실행 중인지 확인해 주세요.',
}

/** User-facing message for a backend error code, falling back to the server's message. */
export function errorMessage(code: string, fallback?: string): string {
  return MESSAGES[code] ?? fallback ?? '요청을 처리하지 못했어요.'
}

/** JSON request to the backend; failures become an ApiError with a user-facing message. */
export async function request<T>(input: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(input, init)
  } catch {
    throw new ApiError(0, 'network', errorMessage('network'))
  }
  if (!response.ok) {
    let code = 'http_error'
    let message = `요청이 실패했어요 (${response.status}).`
    try {
      const body = (await response.json()) as { detail?: { code?: string; message?: string } }
      if (body.detail?.code) {
        code = body.detail.code
        message = errorMessage(code, body.detail.message)
      }
    } catch {
      // Non-JSON error body (e.g. proxy failure); keep the generic message.
    }
    if (response.status === 502 || response.status === 504) message = errorMessage('network')
    throw new ApiError(response.status, code, message)
  }
  return (await response.json()) as T
}

export interface UploadedImage {
  image_id: string
  /** Relative path to the prepared PNG; recognized coordinates refer to it. */
  image_url: string
  width_px: number
  height_px: number
  media_type: string
  expires_at: string
}

export function uploadPlanImage(file: File): Promise<UploadedImage> {
  const body = new FormData()
  body.append('image', file)
  // The browser sets the multipart Content-Type and boundary.
  return request<UploadedImage>('/api/floor-plans/uploads', { method: 'POST', body })
}

export async function fetchPreparedImage(imageUrl: string): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(imageUrl)
  } catch {
    throw new ApiError(0, 'network', errorMessage('network'))
  }
  if (!response.ok) throw new ApiError(response.status, 'image_not_found', errorMessage('image_not_found'))
  return response.blob()
}

export interface RecognitionAccepted {
  job_id: string
  status_url: string
}

export function startRecognition(imageId: string): Promise<RecognitionAccepted> {
  return request<RecognitionAccepted>('/api/floor-plans/recognitions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_id: imageId }),
  })
}

export type JobState = 'queued' | 'running' | 'succeeded' | 'failed'

export interface RecognitionStatus {
  job_id: string
  state: JobState
  created_at: string
  updated_at: string
  expires_at: string
  result: RecognitionDraft | null
  error: { code: string; message: string } | null
}

export function getRecognition(jobId: string): Promise<RecognitionStatus> {
  return request<RecognitionStatus>(`/api/floor-plans/recognitions/${encodeURIComponent(jobId)}`)
}
