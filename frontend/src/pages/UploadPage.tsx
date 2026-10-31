import { useState } from 'react'
import { fetchPreparedImage, uploadPlanImage } from '../api/floorPlans.ts'
import { ACCEPTED_PLAN_TYPES, isAcceptedPlanFile, loadPlanImage, type PlanImage } from '../floorPlan/loadImage.ts'

interface UploadPageProps {
  /** Called with the backend-prepared image and its upload id, which recognition uses. */
  onLoaded: (plan: PlanImage, imageId: string) => void
}

export function UploadPage({ onLoaded }: UploadPageProps) {
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)

  async function open(file: File) {
    if (uploading) return
    setError(null)
    if (!isAcceptedPlanFile(file)) {
      setError('PNG, JPG, WebP 이미지만 올릴 수 있어요.')
      return
    }
    setUploading(true)
    try {
      const uploaded = await uploadPlanImage(file)
      // Show the prepared image: recognized coordinates refer to it, not to the original file.
      const prepared = await fetchPreparedImage(uploaded.image_url)
      onLoaded(await loadPlanImage(prepared, file.name), uploaded.image_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setUploading(false)
    }
  }

  return (
    <div className="page page--narrow">
      <h2>평면도 올리기</h2>
      <p className="note">공간의 평면도 이미지를 올려 주세요. PNG, JPG, WebP 파일을 쓸 수 있어요.</p>

      <label
        className={`dropzone${dragOver ? ' dropzone--over' : ''}${uploading ? ' dropzone--busy' : ''}`}
        aria-busy={uploading}
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
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void open(file)
            event.target.value = ''
          }}
        />
        <span className="dropzone__button">{uploading ? '올리는 중…' : '이미지 선택'}</span>
        <span className="note">또는 여기로 파일을 끌어다 놓으세요</span>
      </label>

      {error && <p className="note note--error">{error}</p>}
    </div>
  )
}
