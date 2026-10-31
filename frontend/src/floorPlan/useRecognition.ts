import { useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage, getRecognition, startRecognition } from '../api/floorPlans.ts'
import type { RecognitionDraft } from './layout.ts'

export type RecognitionState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'succeeded'; draft: RecognitionDraft }
  | { status: 'failed'; message: string }

const POLL_INTERVAL_MS = 1000

interface Tracked {
  key: string
  state: RecognitionState
}

/**
 * Submits a recognition job for an uploaded image and polls it about once a
 * second until it finishes. A new image id (or retry) starts a fresh job; any
 * response for a previous one is ignored. `onSucceeded` lets the caller keep
 * the result, e.g. in the saved project.
 */
export function useRecognition(
  imageId: string | null,
  onSucceeded?: (draft: RecognitionDraft) => void,
): { state: RecognitionState; retry: () => void } {
  const [attempt, setAttempt] = useState(0)
  const [tracked, setTracked] = useState<Tracked | null>(null)
  const key = imageId ? `${imageId}#${attempt}` : null
  const onSucceededRef = useRef(onSucceeded)
  useEffect(() => {
    onSucceededRef.current = onSucceeded
  })

  useEffect(() => {
    if (!imageId || !key) return
    let cancelled = false
    let timer = 0
    const finish = (state: RecognitionState) => {
      if (cancelled) return
      setTracked({ key, state })
      if (state.status === 'succeeded') onSucceededRef.current?.(state.draft)
    }
    const fail = (error: unknown) =>
      finish({ status: 'failed', message: error instanceof ApiError ? error.message : errorMessage('recognition_failed') })

    const poll = async (jobId: string) => {
      try {
        const status = await getRecognition(jobId)
        if (cancelled) return
        if (status.state === 'succeeded' && status.result) finish({ status: 'succeeded', draft: status.result })
        else if (status.state === 'failed')
          finish({ status: 'failed', message: errorMessage(status.error?.code ?? 'recognition_failed', status.error?.message) })
        else timer = window.setTimeout(() => void poll(jobId), POLL_INTERVAL_MS)
      } catch (error) {
        fail(error)
      }
    }

    startRecognition(imageId)
      .then(({ job_id }) => {
        if (!cancelled) void poll(job_id)
      })
      .catch(fail)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [imageId, key])

  // Until the current job reports back, anything stored belongs to an older one.
  const state: RecognitionState = !key ? { status: 'idle' } : tracked?.key === key ? tracked.state : { status: 'running' }
  return { state, retry: () => setAttempt((n) => n + 1) }
}
