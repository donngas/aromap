import { useState } from 'react'
import './App.css'
import { DiffuserForm } from './components/DiffuserForm.tsx'
import { PlanViewer } from './components/PlanViewer.tsx'
import { validateDiffuser } from './diffusers/emission.ts'
import { loadDiffusers, saveDiffusers } from './diffusers/storage.ts'
import type { DiffuserDraft } from './diffusers/types.ts'
import { ACCEPTED_PLAN_TYPES, loadPlanImage, releasePlanImage, type PlanImage } from './floorPlan/loadImage.ts'

export default function App() {
  const [plan, setPlan] = useState<PlanImage | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [diffusers, setDiffusers] = useState<DiffuserDraft[]>(loadDiffusers)
  const [saved, setSaved] = useState(true)

  function updateDiffusers(next: DiffuserDraft[]) {
    setDiffusers(next)
    setSaved(saveDiffusers(next))
  }

  async function openPlan(file: File) {
    setLoadError(null)
    try {
      const loaded = await loadPlanImage(file)
      if (plan) releasePlanImage(plan)
      setPlan(loaded)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
    }
  }

  const invalidCount = diffusers.filter((d) => validateDiffuser(d).length > 0).length

  return (
    <div className="app">
      <aside className="panel">
        <header className="panel__header">
          <h1>Aromap</h1>
          <ol className="steps">
            <li className={plan ? 'is-done' : 'is-current'}>평면도</li>
            <li className={plan ? 'is-current' : ''}>디퓨저</li>
            <li>작업 공간</li>
          </ol>
        </header>

        <section className="section">
          <h2>1. 평면도</h2>
          <div className="section__body">
            <div className="row">
              <label className="file-button">
                <input
                  type="file"
                  accept={ACCEPTED_PLAN_TYPES.join(',')}
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void openPlan(file)
                    event.target.value = ''
                  }}
                />
                {plan ? '다시 선택' : '이미지 선택'}
              </label>
              {plan && (
                <span className="note">
                  {plan.file.name} · {plan.width}×{plan.height}px
                </span>
              )}
            </div>
            {!plan && <p className="note">PNG, JPG, WebP · 화면으로 끌어다 놓아도 돼요.</p>}
            {loadError && <p className="note note--error">{loadError}</p>}
          </div>
        </section>

        {plan && (
          <section className="section">
            <h2>2. 디퓨저 등록</h2>
            <div className="section__body">
              <DiffuserForm diffusers={diffusers} onChange={updateDiffusers} />
            </div>
          </section>
        )}

        {plan && (
          <footer className="panel__footer">
            <p className="note">
              디퓨저 {diffusers.length}개
              {invalidCount > 0 && ` · 입력 필요 ${invalidCount}개`}
              {saved ? ' · 브라우저에 자동 저장됨' : ' · 저장할 수 없음 (브라우저 저장소 차단)'}
            </p>
            {/* Enabled once backend recognition is connected and the workspace exists. */}
            <button type="button" disabled title="백엔드 변환 연동 후 활성화">
              다음: 작업 공간
            </button>
          </footer>
        )}
      </aside>

      <main className="stage">
        <PlanViewer image={plan?.image ?? null} onFileDrop={(file) => void openPlan(file)} />
      </main>
    </div>
  )
}
