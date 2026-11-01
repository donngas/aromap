import { useState } from 'react'
import { COVERAGE_THRESHOLD } from '../simulation/analysis.ts'
import { formatSimTime } from '../simulation/format.ts'
import { NO_SCENT_SPREAD, spreadGradient } from '../diffusers/scents.ts'

/** A scenario that has a result and can be compared. */
export interface ComparableScenario {
  id: string
  name: string
  hours: number
  /** Changed since its result was computed. */
  stale: boolean
}

/** The A/B comparison in progress: chosen scenarios and their coverage at the playback position. */
export interface CompareState {
  a: string
  b: string
  coverageA: number
  coverageB: number
}

interface AnalysisPanelProps {
  /** Coverage at the playback position, or null without a result. */
  coverage: number | null
  /** Playback position in seconds. */
  time: number | null
  running: boolean
  comparable: ComparableScenario[]
  compare: CompareState | null
  /** Scent families shown with their spread colours; one legend bar per scent. */
  scents: { label: string; color: string }[]
  onStartCompare: () => void
  onStopCompare: () => void
  onCompareChange: (side: 'a' | 'b', scenarioId: string) => void
  /** While comparing: whether both sides pan and zoom together. */
  linkedViews: boolean
  onLinkedViewsChange: (linked: boolean) => void
  /** Fits both sides to the whole plan again. */
  onFitViews: () => void
}

const percent = (share: number) => `${Math.round(share * 100)}%`

/** Contents of the "분석" window: coverage (or the A/B pair), legend and the compare switch. */
export function AnalysisPanel({
  coverage,
  time,
  running,
  comparable,
  compare,
  scents,
  onStartCompare,
  onStopCompare,
  onCompareChange,
  linkedViews,
  onLinkedViewsChange,
  onFitViews,
}: AnalysisPanelProps) {
  const [showInfo, setShowInfo] = useState(false)
  const canCompare = comparable.length >= 2

  const info = (
    <button
      type="button"
      className="ws-coverage__info"
      aria-expanded={showInfo}
      aria-label="확산 커버리지 설명"
      onClick={() => setShowInfo((s) => !s)}
    >
      i
    </button>
  )
  const explain = showInfo && (
    <p className="ws-coverage__explain">
      향 성분이 1㎡당 {COVERAGE_THRESHOLD} 상대 단위 이상 쌓인 실내 면적의 비율이에요. 배치안끼리 비교하기 위한
      상대적인 값이고, 실제로 느끼는 향의 세기와는 다를 수 있어요.
    </p>
  )

  return (
    <>
      {compare ? (
        <section className="ws-panel__section">
          <div className="ws-coverage__head">
            <h3 className="ws-panel__title">A/B 비교 · 확산 커버리지</h3>
            {info}
          </div>
          {(['a', 'b'] as const).map((side) => {
            const id = side === 'a' ? compare.a : compare.b
            const value = side === 'a' ? compare.coverageA : compare.coverageB
            const picked = comparable.find((c) => c.id === id)
            return (
              <div key={side} className="ws-ab">
                <span className={`ws-ab__badge ws-ab__badge--${side}`}>{side.toUpperCase()}</span>
                <div className="ws-ab__pick">
                  <select
                    aria-label={`${side.toUpperCase()} 배치안`}
                    value={id}
                    onChange={(event) => onCompareChange(side, event.target.value)}
                  >
                    {comparable.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  {picked && (
                    <span className="ws-ab__meta">
                      {picked.hours}시간{picked.stale ? ' · 결과 이후 변경됨' : ''}
                    </span>
                  )}
                </div>
                <span className="ws-ab__value">{percent(value)}</span>
              </div>
            )
          })}
          <p className="note">{compareSummary(compare, time)}</p>
          {explain}
        </section>
      ) : (
        <section className="ws-panel__section">
          <div className="ws-coverage">
            <div className="ws-coverage__head">
              <h3 className="ws-panel__title">확산 커버리지</h3>
              {info}
            </div>
            <p className="ws-coverage__value">{coverage === null ? '–' : percent(coverage)}</p>
            <p className="note">
              {coverage === null
                ? running
                  ? '계산이 끝나면 나타나요.'
                  : '시뮬레이션을 시작하면 나타나요.'
                : `${formatSimTime(time ?? 0)} 시점의 실내 면적 기준`}
            </p>
            {explain}
          </div>
        </section>
      )}

      <section className="ws-panel__section">
        <h3 className="ws-panel__title">향 농도</h3>
        <div className="ws-legend">
          {(scents.length > 0 ? scents : [{ label: '향', color: NO_SCENT_SPREAD }]).map((s) => (
            <div key={s.label} className="ws-legend__row">
              {scents.length > 0 && <span className="ws-legend__name">{s.label}</span>}
              <span className="ws-legend__ramp" style={{ background: spreadGradient(s.color) }} />
            </div>
          ))}
          <div className="ws-legend__labels">
            <span>낮음</span>
            <span>높음</span>
          </div>
        </div>
      </section>

      {compare && (
        <section className="ws-panel__section">
          <h3 className="ws-panel__title">화면 보기</h3>
          <label className="ws-switch">
            <span>두 화면 같이 움직이기</span>
            <input
              type="checkbox"
              role="switch"
              checked={linkedViews}
              onChange={(event) => onLinkedViewsChange(event.target.checked)}
            />
          </label>
          <p className="field__hint">
            {linkedViews
              ? '한쪽을 확대하거나 옮기면 다른 쪽도 똑같이 움직여요.'
              : '왼쪽과 오른쪽을 따로 확대하고 옮길 수 있어요.'}
          </p>
          <button type="button" className="ws-compare__toggle" onClick={onFitViews}>
            두 화면 처음 크기로
          </button>
        </section>
      )}

      <section className="ws-panel__section">
        {compare ? (
          <button type="button" className="button--primary ws-compare__toggle" onClick={onStopCompare}>
            비교 종료
          </button>
        ) : (
          <>
            <button type="button" className="ws-compare__toggle" disabled={!canCompare} onClick={onStartCompare}>
              A/B 비교
            </button>
            <p className="field__hint">
              {canCompare
                ? '시뮬레이션한 두 배치안을 왼쪽과 오른쪽에 나란히 보여 줘요. 비교하는 동안에는 편집할 수 없어요.'
                : '배치안 두 개 이상을 시뮬레이션하면 비교할 수 있어요.'}
            </p>
          </>
        )}
      </section>
    </>
  )
}

/** "12분 시점: B가 A보다 8%p 넓게 퍼졌어요" style summary. */
function compareSummary(compare: CompareState, time: number | null): string {
  const diff = Math.round((compare.coverageB - compare.coverageA) * 100)
  const when = `${formatSimTime(time ?? 0)} 시점`
  if (diff === 0) return `${when}: 두 배치안이 비슷하게 퍼졌어요.`
  return diff > 0 ? `${when}: B가 A보다 ${diff}%p 넓게 퍼졌어요.` : `${when}: A가 B보다 ${-diff}%p 넓게 퍼졌어요.`
}
