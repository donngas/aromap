import { DiffuserForm } from '../components/DiffuserForm.tsx'
import { validateDiffuser } from '../diffusers/emission.ts'
import type { DiffuserDraft } from '../diffusers/types.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'

interface DiffuserPageProps {
  plan: PlanImage
  diffusers: DiffuserDraft[]
  saved: boolean
  onChange: (diffusers: DiffuserDraft[]) => void
}

export function DiffuserPage({ plan, diffusers, saved, onChange }: DiffuserPageProps) {
  const invalidCount = diffusers.filter((d) => validateDiffuser(d).length > 0).length

  return (
    <div className="page">
      <h2>디퓨저 등록</h2>
      <p className="note">사용할 디퓨저 제품을 등록하세요. 개수와 위치는 다음 화면에서 정해요.</p>

      <div className="plan-summary">
        <img src={plan.url} alt="선택한 평면도" />
        <div>
          <p>{plan.file.name}</p>
          <p className="note">
            {plan.width}×{plan.height}px
          </p>
        </div>
      </div>

      <DiffuserForm diffusers={diffusers} onChange={onChange} />

      <footer className="page__footer">
        <p className="note">
          디퓨저 {diffusers.length}개{invalidCount > 0 && ` · 입력 필요 ${invalidCount}개`}
          {saved ? ' · 브라우저에 자동 저장됨' : ' · 저장할 수 없음 (브라우저 저장소 차단)'}
        </p>
        {/* Enabled once backend recognition is connected and the workspace exists. */}
        <button type="button" disabled title="백엔드 변환 연동 후 활성화">
          다음: 작업 공간
        </button>
      </footer>
    </div>
  )
}
