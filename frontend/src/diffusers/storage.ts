import { DIFFUSER_TYPES, type DiffuserDraft } from './types.ts'

const STORAGE_KEY = 'aromap.diffusers.v1'

// Storage can be unavailable (private mode, blocked site data), so failures are
// ignored and the app keeps working with in-memory state.

export function loadDiffusers(): DiffuserDraft[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isDiffuserDraft) : []
  } catch {
    return []
  }
}

export function saveDiffusers(diffusers: DiffuserDraft[]): boolean {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(diffusers))
    return true
  } catch {
    return false
  }
}

function isDiffuserDraft(value: unknown): value is DiffuserDraft {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.id === 'string' &&
    typeof v.name === 'string' &&
    DIFFUSER_TYPES.includes(v.type as DiffuserDraft['type']) &&
    typeof v.usesExampleValues === 'boolean'
  )
}
