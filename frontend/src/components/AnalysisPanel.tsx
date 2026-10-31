import { useState } from 'react'
import { COVERAGE_THRESHOLD } from '../simulation/analysis.ts'
import { formatSimTime } from '../simulation/format.ts'
import { NO_SCENT_COLOR, scentGradient } from '../diffusers/scents.ts'

export interface ScenarioComparison {
  id: string
  name: string
  /** Coverage at the end of its run, 0–1. */
  coverage: number
  hours: number
  current: boolean
  stale: boolean
}

interface AnalysisPanelProps {
  /** Coverage at the playback position, or null without a result. */
  coverage: number | null
  /** Playback position in seconds. */
  time: number | null
  running: boolean
  comparisons: ScenarioComparison[]
  /** Scent families shown, each with its colour; one legend bar per scent. */
  scents: { label: string; color: string }[]
  onSelectScenario: (id: string) => void
}

const percent = (share: number) => `${Math.round(share * 100)}%`

/** Contents of the "분석" window: coverage, legend and scenario comparison. */
export function AnalysisPanel({
  coverage,
  time,
  running,
  comparisons,
  scents,
  onSelectScenario,
}: AnalysisPanelProps) {
  const [showInfo, setShowInfo] = useState(false)
  const [comparing, setComparing] = useState(false)
  const canCompare = comparisons.length >= 2

  return (
    <>
      <section className="ws-panel__section">
        <div className="ws-coverage">
          <div className="ws-coverage__head">
            <h3 className="ws-panel__title">확산 커버리지</h3>
            <button
              type="button"
              className="ws-coverage__info"
              aria-expanded={showInfo}
              aria-label="확산 커버리지 설명"
              onClick={() => setShowInfo((s) => !s)}
            >
              i
            </button>
          </div>
          <p className="ws-coverage__value">{coverage === null ? '–' : percent(coverage)}</p>
          <p className="note">
            {coverage === null
              ? running
                ? '계산이 끝나면 나타나요.'
                : '시뮬레이션을 시작하면 나타나요.'
              : `${formatSimTime(time ?? 0)} 시점의 실내 면적 기준`}
          </p>
          {showInfo && (
            <p className="ws-coverage__explain">
              향 성분이 1㎡당 {COVERAGE_THRESHOLD} 상대 단위 이상 쌓인 실내 면적의 비율이에요. 배치안끼리 비교하기 위한
              상대적인 값이고, 실제로 느끼는 향의 세기와는 다를 수 있어요.
            </p>
          )}
        </div>
      </section>

      <section className="ws-panel__section">
        <h3 className="ws-panel__title">향 농도</h3>
        <div className="ws-legend">
          {(scents.length > 0 ? scents : [{ label: '향', color: NO_SCENT_COLOR }]).map((s) => (
            <div key={s.label} className="ws-legend__row">
              {scents.length > 0 && <span className="ws-legend__name">{s.label}</span>}
              <span className="ws-legend__ramp" style={{ background: scentGradient(s.color) }} />
            </div>
          ))}
          <div className="ws-legend__labels">
            <span>낮음</span>
            <span>높음</span>
          </div>
        </div>
      </section>

      <section className="ws-panel__section">
        <button
          type="button"
          className="ws-compare__toggle"
          aria-expanded={comparing}
          disabled={!canCompare}
          onClick={() => setComparing((c) => !c)}
        >
          A/B 비교
        </button>
        {!canCompare && <p className="field__hint">배치안 두 개 이상을 시뮬레이션하면 비교할 수 있어요.</p>}
        {comparing && canCompare && (
          <ol className="ws-compare">
            {[...comparisons]
              .sort((a, b) => b.coverage - a.coverage)
              .map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    className={c.current ? 'is-current' : ''}
                    aria-current={c.current ? 'true' : undefined}
                    onClick={() => onSelectScenario(c.id)}
                  >
                    <span className="ws-compare__name">{c.name}</span>
                    <span className="ws-compare__meta">
                      {c.hours}시간{c.stale ? ' · 변경됨' : ''}
                    </span>
                    <span className="ws-compare__value">{percent(c.coverage)}</span>
                    <span className="ws-compare__bar" style={{ width: percent(c.coverage) }} aria-hidden="true" />
                  </button>
                </li>
              ))}
          </ol>
        )}
      </section>
    </>
  )
}
