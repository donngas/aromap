import { useState } from 'react'
import './App.css'
import { loadDiffusers, saveDiffusers } from './diffusers/storage.ts'
import type { DiffuserDraft } from './diffusers/types.ts'
import type { PlanImage } from './floorPlan/loadImage.ts'
import { DiffuserPage } from './pages/DiffuserPage.tsx'
import { LandingPage } from './pages/LandingPage.tsx'
import { UploadPage } from './pages/UploadPage.tsx'

const STEPS = ['평면도', '디퓨저', '작업 공간']

export default function App() {
  // The flow only moves forward: landing, then upload, then the diffuser page.
  const [started, setStarted] = useState(false)
  const [plan, setPlan] = useState<PlanImage | null>(null)
  const [diffusers, setDiffusers] = useState<DiffuserDraft[]>(loadDiffusers)
  const [saved, setSaved] = useState(true)

  function updateDiffusers(next: DiffuserDraft[]) {
    setDiffusers(next)
    setSaved(saveDiffusers(next))
  }

  const currentIndex = plan ? 1 : 0

  if (!started) {
    return (
      <LandingPage
        onStart={() => {
          setStarted(true)
          window.scrollTo(0, 0)
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>Aromap</h1>
        <ol className="steps">
          {STEPS.map((label, i) => (
            <li key={label} className={i === currentIndex ? 'is-current' : i < currentIndex ? 'is-done' : ''}>
              {i + 1}. {label}
            </li>
          ))}
        </ol>
      </header>

      <main className="content">
        {plan ? (
          <DiffuserPage plan={plan} diffusers={diffusers} saved={saved} onChange={updateDiffusers} />
        ) : (
          <UploadPage onLoaded={setPlan} />
        )}
      </main>
    </div>
  )
}
