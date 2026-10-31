import { useEffect, useRef, useState } from 'react'
import { saveProject } from './storage.ts'
import type { ProjectDocument } from './types.ts'

const DEBOUNCE_MS = 500

export type SaveStatus = 'saved' | 'failed'

/**
 * Saves the project shortly after it stops changing, and immediately when the
 * page is hidden or closed so recent edits are not lost.
 */
export function useAutosave(project: ProjectDocument | null): SaveStatus {
  const [status, setStatus] = useState<SaveStatus>('saved')
  const pending = useRef<ProjectDocument | null>(null)

  useEffect(() => {
    if (!project) return
    pending.current = project
    const timer = window.setTimeout(() => void flush(), DEBOUNCE_MS)
    return () => window.clearTimeout(timer)

    async function flush() {
      const doc = pending.current
      if (!doc) return
      pending.current = null
      try {
        await saveProject(doc)
        setStatus('saved')
      } catch {
        setStatus('failed')
      }
    }
  }, [project])

  useEffect(() => {
    const flushNow = () => {
      const doc = pending.current
      if (!doc) return
      pending.current = null
      saveProject(doc).catch(() => setStatus('failed'))
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flushNow()
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', flushNow)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', flushNow)
    }
  }, [])

  return status
}

export const SAVE_STATUS_TEXT: Record<SaveStatus, string> = {
  saved: '브라우저에 자동 저장됨',
  failed: '저장할 수 없음 (브라우저 저장소 차단)',
}
