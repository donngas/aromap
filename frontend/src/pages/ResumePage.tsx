import { useState } from 'react'
import type { ProjectDocument } from '../project/types.ts'

interface ResumePageProps {
  project: ProjectDocument
  thumbnailUrl: string
  busy: boolean
  error: string | null
  onContinue: () => void
  onStartOver: () => void
}

const dateFormat = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long', timeStyle: 'short' })

export function ResumePage({ project, thumbnailUrl, busy, error, onContinue, onStartOver }: ResumePageProps) {
  const [confirming, setConfirming] = useState(false)

  const progress = !project.recognition
    ? '평면도를 분석하는 중이었어요'
    : project.step === 'workspace'
      ? '작업 공간까지 진행했어요'
      : project.step === 'diffusers'
        ? '디퓨저를 등록하는 중이었어요'
        : '공간을 설정하는 중이었어요'

  return (
    <div className="page page--narrow">
      <h2>저장된 작업이 있어요</h2>
      <p className="note">이전에 하던 작업을 이어서 하거나, 새 평면도로 처음부터 시작할 수 있어요.</p>

      <div className="plan-summary">
        <img src={thumbnailUrl} alt="저장된 평면도" />
        <div>
          <p>{project.plan.fileName}</p>
          <p className="note">
            {progress} · 디퓨저 {project.diffusers.length}개 · 배치안 {project.scenarios.length}개
          </p>
          <p className="note">마지막 저장 {dateFormat.format(new Date(project.updatedAt))}</p>
        </div>
      </div>

      {confirming ? (
        <div className="confirm">
          <p>저장된 작업이 지워지고 되돌릴 수 없어요. 새로 시작할까요?</p>
          <div className="row">
            <button type="button" className="button--danger" disabled={busy} onClick={onStartOver}>
              지우고 새로 시작
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
              취소
            </button>
          </div>
        </div>
      ) : (
        <div className="row">
          <button type="button" className="button--primary" disabled={busy} onClick={onContinue}>
            {busy ? '불러오는 중…' : '이어서 하기'}
          </button>
          <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
            새로 시작
          </button>
        </div>
      )}

      {error && <p className="note note--error">{error}</p>}
    </div>
  )
}
