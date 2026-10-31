import { useState } from 'react'
import { createScenario, nextScenarioName, type ProjectDocument } from '../project/types.ts'

interface ScenarioListProps {
  project: ProjectDocument
  onChange: (update: (project: ProjectDocument) => ProjectDocument) => void
}

/**
 * Scenarios compare diffuser arrangements on the same floor plan. Each keeps
 * its own placements and door states; walls and diffuser products are shared
 * by all of them.
 */
export function ScenarioList({ project, onChange }: ScenarioListProps) {
  const { scenarios, activeScenarioId } = project
  const active = scenarios.find((s) => s.id === activeScenarioId) ?? scenarios[0]
  const [renaming, setRenaming] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const add = (copyActive: boolean) => {
    onChange((p) => {
      const source = p.scenarios.find((s) => s.id === p.activeScenarioId)
      const name = copyActive && source ? `${source.name} 복사본` : nextScenarioName(p.scenarios)
      const scenario = createScenario(name, copyActive ? source : undefined)
      return { ...p, scenarios: [...p.scenarios, scenario], activeScenarioId: scenario.id }
    })
    setRenaming(null)
    setConfirmDelete(false)
  }

  const select = (id: string) => {
    onChange((p) => ({ ...p, activeScenarioId: id }))
    setRenaming(null)
    setConfirmDelete(false)
  }

  const commitRename = () => {
    const name = renaming?.trim()
    if (name) {
      onChange((p) => ({
        ...p,
        scenarios: p.scenarios.map((s) => (s.id === p.activeScenarioId ? { ...s, name } : s)),
      }))
    }
    setRenaming(null)
  }

  const remove = () => {
    onChange((p) => {
      if (p.scenarios.length <= 1) return p
      const index = p.scenarios.findIndex((s) => s.id === p.activeScenarioId)
      const remaining = p.scenarios.filter((s) => s.id !== p.activeScenarioId)
      return { ...p, scenarios: remaining, activeScenarioId: remaining[Math.max(0, index - 1)].id }
    })
    setConfirmDelete(false)
  }

  if (renaming !== null) {
    return (
      <div className="scenarios">
        <div className="row scenarios__edit">
          <input
            aria-label="배치안 이름"
            value={renaming}
            autoFocus
            onChange={(event) => setRenaming(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') commitRename()
              if (event.key === 'Escape') setRenaming(null)
            }}
          />
          <button type="button" onClick={commitRename}>
            저장
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="scenarios">
      <select aria-label="배치안 고르기" value={active.id} onChange={(event) => select(event.target.value)}>
        {scenarios.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} · 디퓨저 {s.placements.length}개
          </option>
        ))}
      </select>

      {confirmDelete ? (
        <div className="row">
          <span className="note">"{active.name}"을 삭제할까요?</span>
          <button type="button" className="button--danger" onClick={remove}>
            삭제
          </button>
          <button type="button" onClick={() => setConfirmDelete(false)}>
            취소
          </button>
        </div>
      ) : (
        <div className="scenarios__actions">
          <button type="button" onClick={() => add(false)}>
            + 새 배치안
          </button>
          <button type="button" onClick={() => add(true)}>
            복제
          </button>
          <button type="button" onClick={() => setRenaming(active.name)}>
            이름
          </button>
          <button type="button" disabled={scenarios.length <= 1} onClick={() => setConfirmDelete(true)}>
            삭제
          </button>
        </div>
      )}
    </div>
  )
}
