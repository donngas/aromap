import { DiffuserForm } from '../components/DiffuserForm.tsx'
import { validateDiffuser } from '../diffusers/emission.ts'
import type { DiffuserDraft } from '../diffusers/types.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'
import type { RecognitionState } from '../floorPlan/useRecognition.ts'
import { SAVE_STATUS_TEXT, type SaveStatus } from '../project/useAutosave.ts'

interface DiffuserPageProps {
  plan: PlanImage
  recognition: RecognitionState
  diffusers: DiffuserDraft[]
  saveStatus: SaveStatus
  onChange: (diffusers: DiffuserDraft[]) => void
  onRetryRecognition: () => void
  onNext: () => void
}

export function DiffuserPage({
  plan,
  recognition,
  diffusers,
  saveStatus,
  onChange,
  onRetryRecognition,
  onNext,
}: DiffuserPageProps) {
  const invalidCount = diffusers.filter((d) => validateDiffuser(d).length > 0).length

  return (
    <div className="page">
      <h2>디퓨저 등록</h2>
      <p className="note">사용할 디퓨저 제품을 등록하세요. 개수와 위치는 다음 화면에서 정해요.</p>

      <div className="plan-summary">
        <img src={plan.url} alt="선택한 평면도" />
        <div>
          <p>{plan.name}</p>
          <p className="note" role="status">
            <RecognitionLabel state={recognition} />
          </p>
        </div>
        {recognition.status === 'failed' && (
          <button type="button" onClick={onRetryRecognition}>
            다시 분석
          </button>
        )}
      </div>

      <DiffuserForm diffusers={diffusers} onChange={onChange} />

      <footer className="page__footer">
        <p className="note">
          디퓨저 {diffusers.length}개{invalidCount > 0 && ` · 입력 필요 ${invalidCount}개`}
          {` · ${SAVE_STATUS_TEXT[saveStatus]}`}
        </p>
        <button type="button" disabled={recognition.status !== 'succeeded'} onClick={onNext}>
          다음: 공간 설정
        </button>
      </footer>
    </div>
  )
}

function RecognitionLabel({ state }: { state: RecognitionState }) {
  switch (state.status) {
    case 'succeeded': {
      const { walls, doors, windows } = state.draft.floor_plan.layout
      return (
        <>
          평면도 분석 완료 · 벽 {walls.length} · 문 {doors.length} · 창 {windows.length}
        </>
      )
    }
    case 'failed':
      return <span className="text-error">{state.message}</span>
    default:
      return <>평면도를 분석하고 있어요…</>
  }
}
