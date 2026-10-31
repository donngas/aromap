import { PlanViewer } from '../components/PlanViewer.tsx'
import { ScenarioList } from '../components/ScenarioList.tsx'
import { metersPerPixel, polygonArea } from '../floorPlan/geometry.ts'
import type { Layout } from '../floorPlan/layout.ts'
import { defaultWallThickness, LAYOUT_STYLE } from '../floorPlan/layoutStyle.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'
import { SAVE_STATUS_TEXT, type SaveStatus } from '../project/useAutosave.ts'
import type { ProjectDocument } from '../project/types.ts'

interface WorkspacePageProps {
  plan: PlanImage
  project: ProjectDocument
  layout: Layout
  warnings: string[]
  saveStatus: SaveStatus
  onChange: (update: (project: ProjectDocument) => ProjectDocument) => void
}

const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 2 })

// Space is set up beforehand (thickness, scale, indoor outline); diffuser
// placement and simulation requests come next.
export function WorkspacePage({ plan, project, layout, warnings, saveStatus, onChange }: WorkspacePageProps) {
  const { walls, doors, windows } = layout
  const wallThickness = project.view.wallThickness ?? defaultWallThickness(plan.width, plan.height)
  const showImage = project.view.showImage
  const { calibration, indoor } = project
  const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null

  const setView = (patch: Partial<ProjectDocument['view']>) =>
    onChange((p) => ({ ...p, view: { ...p.view, ...patch } }))

  return (
    <div className="workspace">
      <aside className="workspace__panel">
        <h2>작업 공간</h2>
        <p className="note">평면도에서 인식한 벽과 문, 창이에요.</p>

        <ScenarioList project={project} onChange={onChange} />

        <dl className="stats">
          <dt>벽</dt>
          <dd>{walls.length}개</dd>
          <dt>문</dt>
          <dd>{doors.length}개</dd>
          <dt>창</dt>
          <dd>{windows.length}개</dd>
        </dl>

        <ul className="legend">
          <LegendItem color={LAYOUT_STYLE.wall.color} label="벽" />
          <LegendItem color={LAYOUT_STYLE.door.color} label="문" />
          <LegendItem color={LAYOUT_STYLE.window.color} label="창" />
        </ul>

        {mpp && indoor && (
          <dl className="stats">
            <dt>축척</dt>
            <dd>1m = {number.format(1 / mpp)}px</dd>
            <dt>실내 면적</dt>
            <dd>약 {number.format(polygonArea(indoor.boundary) * mpp * mpp)} ㎡</dd>
          </dl>
        )}
        <button type="button" className="link-button" onClick={() => onChange((p) => ({ ...p, step: 'thickness' }))}>
          공간 설정 다시 하기
        </button>

        <label className="check">
          <input
            type="checkbox"
            checked={showImage}
            onChange={(event) => setView({ showImage: event.target.checked })}
          />
          평면도 이미지 함께 보기
        </label>

        {warnings.length > 0 && (
          <div className="workspace__warnings">
            <p className="note">인식하면서 확인이 필요한 부분이 있었어요.</p>
            <ul>
              {warnings.map((warning) => (
                <li key={warning} className="note">
                  {warning}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="note workspace__save">{SAVE_STATUS_TEXT[saveStatus]}</p>
      </aside>

      <div className="workspace__stage">
        <PlanViewer
          image={plan.image}
          layout={layout}
          imageOpacity={showImage ? 0.45 : 0}
          wallThickness={wallThickness}
          polygon={indoor?.boundary ?? null}
        />
      </div>
    </div>
  )
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <li>
      <span className="legend__swatch" style={{ background: color }} />
      {label}
    </li>
  )
}
