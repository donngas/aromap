import { useState } from 'react'
import './App.css'
import { ApiError, uploadPlanImage } from './api/floorPlans.ts'
import type { DiffuserDraft } from './diffusers/types.ts'
import type { RecognitionDraft } from './floorPlan/layout.ts'
import { loadPlanImage, type PlanImage } from './floorPlan/loadImage.ts'
import { useRecognition, type RecognitionState } from './floorPlan/useRecognition.ts'
import { DiffuserPage } from './pages/DiffuserPage.tsx'
import { LandingPage } from './pages/LandingPage.tsx'
import { ResumePage } from './pages/ResumePage.tsx'
import { SetupPage } from './pages/SetupPage.tsx'
import { UploadPage } from './pages/UploadPage.tsx'
import { WorkspacePage } from './pages/WorkspacePage.tsx'
import { deleteProject, loadProject, saveProjectImage, type SavedProject } from './project/storage.ts'
import { createProject, SETUP_STEPS, type ProjectDocument, type SetupStep } from './project/types.ts'
import { useAutosave } from './project/useAutosave.ts'

const STEPS = ['평면도', '디퓨저', '공간 설정', '작업 공간']

const isSetupStep = (step: string): step is SetupStep => (SETUP_STEPS as readonly string[]).includes(step)

type Phase = 'landing' | 'resume' | 'flow'

export default function App() {
  // Started once; the landing page gives it plenty of time to finish.
  const [savedPromise] = useState(loadProject)
  const [phase, setPhase] = useState<Phase>('landing')
  const [saved, setSaved] = useState<{ data: SavedProject; thumbnailUrl: string } | null>(null)
  const [resumeBusy, setResumeBusy] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)

  // Upload, diffusers, space setup (thickness, scale, indoor outline), then the workspace.
  const [project, setProject] = useState<ProjectDocument | null>(null)
  const [planImage, setPlanImage] = useState<PlanImage | null>(null)
  // Runtime-only upload handle for recognition; it expires, so it is never saved.
  const [imageId, setImageId] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const saveStatus = useAutosave(project)

  const updateProject = (update: (p: ProjectDocument) => ProjectDocument) =>
    setProject((p) => (p ? update(p) : p))

  const keepRecognition = (draft: RecognitionDraft) =>
    updateProject((p) =>
      p.recognition ? p : { ...p, recognition: { layout: draft.floor_plan.layout, warnings: draft.warnings } },
    )
  const liveRecognition = useRecognition(project?.recognition ? null : imageId, keepRecognition)

  const recognition: RecognitionState = project?.recognition
    ? { status: 'succeeded', draft: { floor_plan: { layout: project.recognition.layout, reference_image: null }, warnings: project.recognition.warnings } }
    : uploadError
      ? { status: 'failed', message: uploadError }
      : liveRecognition.state

  /** Upload ids expire, so a resumed project re-uploads its stored image to recognize it. */
  async function reupload(image: Blob, fileName: string) {
    setUploadError(null)
    try {
      const uploaded = await uploadPlanImage(new File([image], fileName, { type: image.type || 'image/png' }))
      setImageId(uploaded.image_id)
    } catch (error) {
      setUploadError(error instanceof ApiError ? error.message : '평면도를 다시 올리지 못했어요.')
    }
  }

  async function start() {
    window.scrollTo(0, 0)
    const data = await savedPromise
    if (data) {
      setSaved({ data, thumbnailUrl: URL.createObjectURL(data.image) })
      setPhase('resume')
    } else {
      setPhase('flow')
    }
  }

  async function continueSaved() {
    if (!saved) return
    setResumeBusy(true)
    setResumeError(null)
    const { project: doc, image } = saved.data
    try {
      setPlanImage(await loadPlanImage(image, doc.plan.fileName))
      setProject(doc)
      URL.revokeObjectURL(saved.thumbnailUrl)
      setSaved(null)
      setPhase('flow')
      if (!doc.recognition) void reupload(image, doc.plan.fileName)
    } catch {
      setResumeError('저장된 평면도를 불러오지 못했어요. 새로 시작해 주세요.')
    } finally {
      setResumeBusy(false)
    }
  }

  async function startOver() {
    if (!saved) return
    setResumeBusy(true)
    setResumeError(null)
    try {
      await deleteProject(saved.data.project.id)
      URL.revokeObjectURL(saved.thumbnailUrl)
      setSaved(null)
      setPhase('flow')
    } catch {
      setResumeError('저장된 작업을 지우지 못했어요. 다시 시도해 주세요.')
    } finally {
      setResumeBusy(false)
    }
  }

  function startProject(image: PlanImage, uploadedId: string) {
    const doc = createProject({ fileName: image.name, width: image.width, height: image.height })
    // The document itself is saved by useAutosave; a failure shows up there too.
    saveProjectImage(doc.id, image.blob).catch(() => {})
    setPlanImage(image)
    setProject(doc)
    setImageId(uploadedId)
  }

  if (phase === 'landing') return <LandingPage onStart={() => void start()} />

  const layout = project?.recognition?.layout ?? null
  const showWorkspace = project?.step === 'workspace' && layout && planImage
  const setupStage = project && layout && planImage && isSetupStep(project.step) ? project.step : null
  const fullHeight = Boolean(showWorkspace || setupStage)
  const currentIndex = phase === 'resume' ? -1 : showWorkspace ? 3 : setupStage ? 2 : project ? 1 : 0

  let content
  if (phase === 'resume' && saved) {
    content = (
      <ResumePage
        project={saved.data.project}
        thumbnailUrl={saved.thumbnailUrl}
        busy={resumeBusy}
        error={resumeError}
        onContinue={() => void continueSaved()}
        onStartOver={() => void startOver()}
      />
    )
  } else if (showWorkspace) {
    content = (
      <WorkspacePage
        plan={planImage}
        project={project}
        layout={layout}
        warnings={project.recognition!.warnings}
        saveStatus={saveStatus}
        onChange={updateProject}
      />
    )
  } else if (setupStage && project && layout && planImage) {
    content = (
      <SetupPage
        plan={planImage}
        project={project}
        layout={layout}
        stage={setupStage}
        saveStatus={saveStatus}
        onChange={updateProject}
      />
    )
  } else if (project && planImage) {
    content = (
      <DiffuserPage
        plan={planImage}
        recognition={recognition}
        diffusers={project.diffusers}
        saveStatus={saveStatus}
        onChange={(diffusers: DiffuserDraft[]) => updateProject((p) => ({ ...p, diffusers }))}
        onRetryRecognition={() => (imageId ? liveRecognition.retry() : void reupload(planImage.blob, planImage.name))}
        onNext={() => {
          updateProject((p) => ({ ...p, step: 'thickness' }))
          window.scrollTo(0, 0)
        }}
      />
    )
  } else {
    content = <UploadPage onLoaded={startProject} />
  }

  return (
    <div className={`app${fullHeight ? ' app--fill' : ''}`}>
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

      <main className={`content${fullHeight ? ' content--fill' : ''}`}>{content}</main>
    </div>
  )
}
