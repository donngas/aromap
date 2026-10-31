import { useState } from 'react'
import { ACCEPTED_PLAN_TYPES, loadPlanImage, type PlanImage } from '../floorPlan/loadImage.ts'

interface UploadPageProps {
  onLoaded: (plan: PlanImage) => void
}

export function UploadPage({ onLoaded }: UploadPageProps) {
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  async function open(file: File) {
    setError(null)
    try {
      onLoaded(await loadPlanImage(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="page page--narrow">
      <h2>평면도 올리기</h2>
      <p className="note">공간의 평면도 이미지를 올려 주세요. PNG, JPG, WebP 파일을 쓸 수 있어요.</p>

      <label
        className={`dropzone${dragOver ? ' dropzone--over' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragOver(false)
          const file = event.dataTransfer.files[0]
          if (file) void open(file)
        }}
      >
        <input
          type="file"
          accept={ACCEPTED_PLAN_TYPES.join(',')}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void open(file)
            event.target.value = ''
          }}
        />
        <span className="dropzone__button">이미지 선택</span>
        <span className="note">또는 여기로 파일을 끌어다 놓으세요</span>
      </label>

      {error && <p className="note note--error">{error}</p>}
    </div>
  )
}
