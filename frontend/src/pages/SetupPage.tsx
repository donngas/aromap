import { useMemo, useState } from 'react'
import { PlanViewer } from '../components/PlanViewer.tsx'
import { WallThicknessField } from '../components/WallThicknessField.tsx'
import { metersPerPixel, polygonArea, suggestIndoorBoundary, wallLength } from '../floorPlan/geometry.ts'
import type { Layout, PixelPoint } from '../floorPlan/layout.ts'
import { defaultWallThickness, maxWallThickness } from '../floorPlan/layoutStyle.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'
import { SETUP_STEPS, type ProjectDocument, type ProjectStep, type SetupStep } from '../project/types.ts'
import { SAVE_STATUS_TEXT, type SaveStatus } from '../project/useAutosave.ts'

interface SetupPageProps {
  plan: PlanImage
  project: ProjectDocument
  layout: Layout
  stage: SetupStep
  saveStatus: SaveStatus
  onChange: (update: (project: ProjectDocument) => ProjectDocument) => void
}

const STAGE_LABELS: Record<SetupStep, string> = {
  thickness: '벽 두께',
  calibration: '실측',
  indoor: '실내 영역',
}

const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 2 })

/** Space setup, in order: wall thickness, scale from one wall, indoor outline. */
export function SetupPage({ plan, project, layout, stage, saveStatus, onChange }: SetupPageProps) {
  const defaultThickness = defaultWallThickness(plan.width, plan.height)
  const wallThickness = project.view.wallThickness ?? defaultThickness
  const stageIndex = SETUP_STEPS.indexOf(stage)

  const [selectedWallId, setSelectedWallId] = useState<string | null>(project.calibration?.wall_id ?? null)
  const [distanceInput, setDistanceInput] = useState(project.calibration ? String(project.calibration.distance_m) : '')
  const selectedWall = layout.walls.find((w) => w.id === selectedWallId) ?? null
  const calibration = project.calibration
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null

  const suggested = useMemo(() => suggestIndoorBoundary(layout), [layout])
  const outline = project.indoor?.boundary ?? suggested

  const goTo = (step: ProjectStep) => onChange((p) => ({ ...p, step }))

  const setCalibration = (wallId: string | null, distanceText: string) => {
    const wall = layout.walls.find((w) => w.id === wallId)
    const distanceM = Number(distanceText)
    onChange((p) => ({
      ...p,
      calibration:
        wall && distanceText.trim() !== '' && distanceM > 0
          ? { wall_id: wall.id, start: wall.start, end: wall.end, distance_m: distanceM }
          : null,
    }))
  }

  const setOutline = (points: PixelPoint[]) =>
    onChange((p) => ({ ...p, indoor: { boundary: points, holes: p.indoor?.holes ?? [] } }))

  const next = () => {
    if (stage === 'thickness') goTo('calibration')
    else if (stage === 'calibration') goTo('indoor')
    else onChange((p) => ({ ...p, indoor: p.indoor ?? { boundary: suggested, holes: [] }, step: 'workspace' }))
  }
  const previous = () => goTo(stageIndex === 0 ? 'diffusers' : SETUP_STEPS[stageIndex - 1])
  const canContinue = stage !== 'calibration' || calibration !== null

  return (
    <div className="workspace">
      <aside className="workspace__panel">
        <h2>공간 설정</h2>
        <ol className="setup-steps">
          {SETUP_STEPS.map((s, i) => (
            <li key={s} className={i === stageIndex ? 'is-current' : i < stageIndex ? 'is-done' : ''}>
              <span className="setup-steps__number">{i + 1}</span>
              {STAGE_LABELS[s]}
            </li>
          ))}
        </ol>

        {stage === 'thickness' && (
          <>
            <p className="note">인식한 벽이 실제 도면처럼 보이도록 두께를 맞춰 주세요.</p>
            <WallThicknessField
              value={wallThickness}
              defaultValue={defaultThickness}
              max={maxWallThickness(plan.width, plan.height)}
              onChange={(value) => onChange((p) => ({ ...p, view: { ...p.view, wallThickness: value } }))}
            />
          </>
        )}

        {stage === 'calibration' && (
          <>
            <p className="note">실제 길이를 알고 있는 벽 하나를 평면도에서 클릭하고, 그 길이를 입력해 주세요.</p>
            {selectedWall ? (
              <div className="field">
                <span className="field__head">선택한 벽 · 이미지에서 {number.format(wallLength(selectedWall))}px</span>
                <div className="field__row">
                  <span className="number-input">
                    <input
                      type="number"
                      min="0"
                      step="any"
                      aria-label="선택한 벽의 실제 길이"
                      placeholder="실제 길이"
                      value={distanceInput}
                      autoFocus
                      onChange={(event) => {
                        setDistanceInput(event.target.value)
                        setCalibration(selectedWallId, event.target.value)
                      }}
                    />
                    m
                  </span>
                </div>
              </div>
            ) : (
              <p className="note note--hint">아직 선택한 벽이 없어요.</p>
            )}
            {mpp ? (
              <dl className="stats">
                <dt>축척</dt>
                <dd>1m = {number.format(1 / mpp)}px</dd>
                <dt>평면도 크기</dt>
                <dd>
                  약 {number.format(plan.width * mpp)} × {number.format(plan.height * mpp)} m
                </dd>
              </dl>
            ) : (
              selectedWall && <p className="field__hint">길이를 입력하면 축척이 정해져요.</p>
            )}
          </>
        )}

        {stage === 'indoor' && (
          <>
            <p className="note">
              초록색 영역이 실내예요. 꼭짓점을 끌어 실제 실내 모양에 맞춰 주세요. 변 가운데의 작은 점을 끌면
              꼭짓점이 추가되고, 꼭짓점을 두 번 클릭하면 지워져요.
            </p>
            {mpp && (
              <dl className="stats">
                <dt>실내 면적</dt>
                <dd>약 {number.format(polygonArea(outline) * mpp * mpp)} ㎡</dd>
                <dt>꼭짓점</dt>
                <dd>{outline.length}개</dd>
              </dl>
            )}
            <button type="button" className="link-button" disabled={!project.indoor} onClick={() => onChange((p) => ({ ...p, indoor: null }))}>
              처음 제안된 모양으로 되돌리기
            </button>
          </>
        )}

        <label className="check">
          <input
            type="checkbox"
            checked={project.view.showImage}
            onChange={(event) => onChange((p) => ({ ...p, view: { ...p.view, showImage: event.target.checked } }))}
          />
          평면도 이미지 함께 보기
        </label>

        <div className="setup-nav">
          <div className="row">
            <button type="button" onClick={previous}>
              이전
            </button>
            <button type="button" className="button--primary" disabled={!canContinue} onClick={next}>
              {stage === 'indoor' ? '작업 공간으로' : `다음: ${STAGE_LABELS[SETUP_STEPS[stageIndex + 1]]}`}
            </button>
          </div>
          <p className="note">{SAVE_STATUS_TEXT[saveStatus]}</p>
        </div>
      </aside>

      <div className="workspace__stage">
        <PlanViewer
          image={plan.image}
          layout={layout}
          imageOpacity={project.view.showImage ? 0.45 : 0}
          wallThickness={wallThickness}
          selectedWallId={stage === 'calibration' ? selectedWallId : null}
          onWallSelect={
            stage === 'calibration'
              ? (id) => {
                  if (id === selectedWallId) return
                  // A different wall needs its own length.
                  setSelectedWallId(id)
                  setDistanceInput('')
                  setCalibration(null, '')
                }
              : undefined
          }
          polygon={stage === 'indoor' ? outline : null}
          onPolygonChange={stage === 'indoor' ? setOutline : undefined}
        />
      </div>
    </div>
  )
}
