// IndexedDB persistence for the single current project. The document and the
// plan image are separate entries, so frequent small edits never rewrite the
// image. Upload/job ids and simulation results are never stored: they expire.

import { createStore, del, delMany, get, set } from 'idb-keyval'
import { normalizeProject, PROJECT_SCHEMA_VERSION, type ProjectDocument } from './types.ts'

const store = createStore('aromap', 'project')
const PROJECT_KEY = 'current'
const imageKey = (projectId: string) => `image:${projectId}`

/** Pre-project diffuser drafts in localStorage; superseded by the project and not migrated. */
const LEGACY_DIFFUSERS_KEY = 'aromap.diffusers.v1'

export interface SavedProject {
  project: ProjectDocument
  image: Blob
}

/** The saved project, or null when there is none, it is unreadable, or storage is unavailable. */
export async function loadProject(): Promise<SavedProject | null> {
  try {
    window.localStorage.removeItem(LEGACY_DIFFUSERS_KEY)
  } catch {
    // Storage blocked; nothing to clean up.
  }
  try {
    const project = await get<ProjectDocument>(PROJECT_KEY, store)
    if (!isProjectDocument(project)) return null
    const image = await get<Blob>(imageKey(project.id), store)
    return image instanceof Blob ? { project: normalizeProject(project), image } : null
  } catch {
    return null
  }
}

/** Saves the document, stamping updatedAt. Rejects when storage is unavailable. */
export async function saveProject(project: ProjectDocument): Promise<void> {
  await set(PROJECT_KEY, { ...project, updatedAt: new Date().toISOString() }, store)
}

export async function saveProjectImage(projectId: string, image: Blob): Promise<void> {
  await set(imageKey(projectId), image, store)
}

/** Removes the saved project and its image. */
export async function deleteProject(projectId: string | null): Promise<void> {
  if (projectId) await delMany([PROJECT_KEY, imageKey(projectId)], store)
  else await del(PROJECT_KEY, store)
}

function isProjectDocument(value: unknown): value is ProjectDocument {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Partial<ProjectDocument>
  return (
    v.schemaVersion === PROJECT_SCHEMA_VERSION &&
    typeof v.id === 'string' &&
    typeof v.plan?.fileName === 'string' &&
    Array.isArray(v.diffusers) &&
    Array.isArray(v.scenarios) &&
    v.scenarios.length > 0 &&
    typeof v.activeScenarioId === 'string'
  )
}
