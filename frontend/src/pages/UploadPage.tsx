import { useState } from 'react'
import { fetchPreparedImage, uploadPlanImage } from '../api/floorPlans.ts'
import { ACCEPTED_PLAN_TYPES, isAcceptedPlanFile, loadPlanImage, type PlanImage } from '../floorPlan/loadImage.ts'

interface UploadPageProps {
  /** Called with the backend-prepared image and its upload id, which recognition uses. */
  onLoaded: (plan: PlanImage, imageId: string) => void
}

/**
 * Sample plans (frontend/public/examples) so visitors can try the service
 * without a plan of their own. Picking one uploads it like a chosen file;
 * nothing is recognized in advance.
 */
const EXAMPLES = [
  { file: 'bakery-cafe.png', title: '베이커리 카페', note: '주방·화장실이 있는 매장' },
  { file: 'porch-house.png', title: '단층 주택', note: '방 2개·거실·현관 포치' },
  { file: 'colored-home.png', title: '컬러 주택 도면', note: '방 3개·치수 표기' },
  { file: 'two-room-apartment.webp', title: '투룸 아파트', note: '간단한 스케치 도면' },
] as const

const exampleUrl = (file: string) => `${import.meta.env.BASE_URL}examples/${file}`

export function UploadPage({ onLoaded }: UploadPageProps) {
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  /** Example being loaded, to show progress on its card. */
  const [pickedExample, setPickedExample] = useState<string | null>(null)

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
      setPickedExample(null)
    }
  }

  /** Loads a sample plan and continues exactly as if it had been chosen as a file. */
  async function openExample(example: (typeof EXAMPLES)[number]) {
    if (uploading) return
    setError(null)
    setPickedExample(example.file)
    try {
      const response = await fetch(exampleUrl(example.file))
      if (!response.ok) throw new Error()
      const blob = await response.blob()
      await open(new File([blob], example.file, { type: blob.type }))
    } catch {
      setError('예시 평면도를 불러오지 못했어요. 다시 시도해 주세요.')
      setPickedExample(null)
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
        <span className="dropzone__button">{uploading && !pickedExample ? '올리는 중…' : '이미지 선택'}</span>
        <span className="note">또는 여기로 파일을 끌어다 놓으세요</span>
      </label>

      <section className="examples" aria-labelledby="examples-title">
        <h3 id="examples-title" className="examples__title">
          평면도가 없다면 예시로 시작해 보세요
        </h3>
        <ul className="examples__list">
          {EXAMPLES.map((example) => {
            const loading = pickedExample === example.file
            return (
              <li key={example.file}>
                <button
                  type="button"
                  className={`examples__item${loading ? ' is-loading' : ''}`}
                  disabled={uploading || pickedExample !== null}
                  aria-busy={loading}
                  onClick={() => void openExample(example)}
                >
                  <img src={exampleUrl(example.file)} alt="" loading="lazy" />
                  <span className="examples__name">{example.title}</span>
                  <span className="examples__note">{loading ? '불러오는 중…' : example.note}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      {error && <p className="note note--error">{error}</p>}
    </div>
  )
}
