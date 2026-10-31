import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api/floorPlans.ts'
import { PlaybackBar } from '../components/PlaybackBar.tsx'
import { PlanViewer, type PlanGrid, type PlanMarker, type PlanOverlay } from '../components/PlanViewer.tsx'
import { ScenarioList } from '../components/ScenarioList.tsx'
import { TYPE_INFO } from '../diffusers/types.ts'
import { metersPerPixel, pointInDomain } from '../floorPlan/geometry.ts'
import type { Layout, PixelPoint } from '../floorPlan/layout.ts'
import { defaultWallThickness } from '../floorPlan/layoutStyle.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'
import { SIMULATION_HOURS, type ProjectDocument, type Scenario } from '../project/types.ts'
import type { SaveStatus } from '../project/useAutosave.ts'
import { buildCellMap, fieldMax, renderFrame } from '../simulation/heatmap.ts'
import { buildSimulationRequest, estimateRunSeconds, MAX_PLACEMENTS, MAX_RUN_SECONDS } from '../simulation/request.ts'
import { runSimulation, type RunPhase, type SimulationField } from '../simulation/run.ts'
import './WorkspacePage.css'

interface WorkspacePageProps {
  plan: PlanImage
  project: ProjectDocument
  layout: Layout
  saveStatus: SaveStatus
  onChange: (update: (project: ProjectDocument) => ProjectDocument) => void
}

/** A finished run of one scenario; results live only for this visit. */
interface ScenarioRun {
  field: SimulationField
  /** Configuration it was run with, to tell when the scenario has changed since. */
  key: string
  /** Scale at run time, for placing the grid on the plan. */
  mpp: number
  /** Doors and outline at run time; they decide which rooms the colour may fill. */
  openDoorIds: ReadonlySet<string>
  indoor: { boundary: PixelPoint[]; holes: PixelPoint[][] }
}

/** "5초 미만", "약 20초", "약 1분 10초"-style wording for an estimate. */
function formatEstimate(seconds: number): string {
  if (seconds < 5) return '5초 미만'
  const total = Math.round(seconds / 5) * 5
  return total < 60 ? `${total}초` : `${Math.floor(total / 60)}분${total % 60 ? ` ${total % 60}초` : ''}`
}

const PHASE_TEXT: Record<RunPhase, string> = {
  submitting: '요청을 보내는 중…',
  queued: '계산 순서를 기다리는 중…',
  running: '향이 퍼지는 모습을 계산하는 중…',
  downloading: '결과를 받는 중…',
}

/**
 * The plan fills the screen. A translucent panel on the left picks the
 * scenario, places diffusers and starts the simulation; results play back over
 * the plan with a bar at the bottom.
 */
export function WorkspacePage({ plan, project, layout, saveStatus, onChange }: WorkspacePageProps) {
  const scenario = project.scenarios.find((s) => s.id === project.activeScenarioId) ?? project.scenarios[0]
  const wallThickness = project.view.wallThickness ?? defaultWallThickness(plan.width, plan.height)
  const { indoor, diffusers } = project
  const products = useMemo(() => new Map(diffusers.map((d) => [d.id, d])), [diffusers])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [choosingProduct, setChoosingProduct] = useState(false)
  const [placing, setPlacing] = useState<string | null>(null)
  const [placeHint, setPlaceHint] = useState<string | null>(null)

  const [runs, setRuns] = useState<Record<string, ScenarioRun>>({})
  const [job, setJob] = useState<{ scenarioId: string; phase: RunPhase } | null>(null)
  const [runError, setRunError] = useState<{ scenarioId: string; messages: string[] } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => abortRef.current?.abort(), [])

  const [showResult, setShowResult] = useState(true)
  const [frame, setFrame] = useState(0)
  // Mirrors `frame` for the playback loop, which outlives single renders.
  const frameRef = useRef(0)
  const goToFrame = (f: number) => {
    frameRef.current = f
    setFrame(f)
  }
  const [playing, setPlaying] = useState(false)
  const [channelPlacementId, setChannelPlacementId] = useState<string | null>(null)

  const updateScenario = (update: (s: Scenario) => Scenario) =>
    onChange((p) => ({ ...p, scenarios: p.scenarios.map((s) => (s.id === p.activeScenarioId ? update(s) : s)) }))

  const removePlacement = (id: string) => {
    updateScenario((s) => ({ ...s, placements: s.placements.filter((p) => p.id !== id) }))
    if (selectedId === id) setSelectedId(null)
  }

  const cancelPlacing = () => {
    setPlacing(null)
    setChoosingProduct(false)
    setPlaceHint(null)
  }

  const place = (position: PixelPoint) => {
    if (!placing) return
    if (indoor && !pointInDomain(position, indoor.boundary, indoor.holes)) {
      setPlaceHint('실내 영역 안을 클릭해 주세요.')
      return
    }
    const id = crypto.randomUUID()
    updateScenario((s) => ({
      ...s,
      placements: [...s.placements, { id, definition_id: placing, position, strength_override: null, enabled: true }],
    }))
    setSelectedId(id)
    cancelPlacing()
  }

  // Delete removes the selected diffuser; Escape leaves placing mode.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return
      if (event.key === 'Escape') {
        setPlacing(null)
        setChoosingProduct(false)
        setPlaceHint(null)
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedId) {
        onChange((p) => ({
          ...p,
          scenarios: p.scenarios.map((s) =>
            s.id === p.activeScenarioId ? { ...s, placements: s.placements.filter((pl) => pl.id !== selectedId) } : s,
          ),
        }))
        setSelectedId(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, onChange])

  const openDoorIds = useMemo(
    () => new Set(scenario.opening_states.filter((s) => s.is_open).map((s) => s.opening_id)),
    [scenario.opening_states],
  )
  const toggleDoor = (doorId: string) =>
    updateScenario((s) => {
      const others = s.opening_states.filter((o) => o.opening_id !== doorId)
      return openDoorIds.has(doorId) ? { ...s, opening_states: others } : { ...s, opening_states: [...others, { opening_id: doorId, is_open: true }] }
    })

  const markers = useMemo<PlanMarker[]>(
    () => scenario.placements.map((p, i) => ({ id: p.id, position: p.position, label: String(i + 1) })),
    [scenario.placements],
  )

  const build = useMemo(() => buildSimulationRequest(project, scenario), [project, scenario])
  const estimate = estimateRunSeconds(project, scenario)
  const run = runs[scenario.id] ?? null
  const running = job !== null
  const stale = run !== null && (!build.ok || build.key !== run.key)
  const errorForScenario = runError?.scenarioId === scenario.id ? runError.messages : null

  const start = () => {
    if (!build.ok) {
      setRunError({ scenarioId: scenario.id, messages: build.problems })
      return
    }
    const scenarioId = scenario.id
    const { request, key } = build
    const mpp = metersPerPixel(project.calibration!.start, project.calibration!.end, project.calibration!.distance_m)!
    const snapshot = { openDoorIds, indoor: { boundary: indoor!.boundary, holes: indoor!.holes } }
    const controller = new AbortController()
    abortRef.current = controller
    setRunError(null)
    setPlaying(false)
    setJob({ scenarioId, phase: 'submitting' })
    runSimulation(request, (phase) => setJob({ scenarioId, phase }), controller.signal)
      .then((field) => {
        setRuns((prev) => ({ ...prev, [scenarioId]: { field, key, mpp, ...snapshot } }))
        setShowResult(true)
        setChannelPlacementId(null)
        goToFrame(0)
        setPlaying(true)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const message = error instanceof ApiError ? error.message : '시뮬레이션을 계산하지 못했어요.'
        setRunError({ scenarioId, messages: [message] })
      })
      .finally(() => {
        if (!controller.signal.aborted) setJob(null)
      })
  }

  // Playback: the whole run takes about 12 seconds whatever its length.
  const frameCount = run?.field.times.length ?? 0
  const shownFrame = Math.min(frame, Math.max(0, frameCount - 1))
  useEffect(() => {
    if (!playing || frameCount < 2) return
    const perFrameMs = 12000 / (frameCount - 1)
    let last = performance.now()
    let carry = 0
    let handle = requestAnimationFrame(function step(now) {
      carry += now - last
      last = now
      const advance = Math.floor(carry / perFrameMs)
      if (advance > 0) {
        carry -= advance * perFrameMs
        const next = Math.min(frameCount - 1, frameRef.current + advance)
        frameRef.current = next
        setFrame(next)
        if (next === frameCount - 1) {
          setPlaying(false)
          return
        }
      }
      handle = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(handle)
  }, [playing, frameCount])

  const channel = run && channelPlacementId ? run.field.placementIds.indexOf(channelPlacementId) : -1
  const channelIndex = channel >= 0 ? channel : null
  const max = useMemo(() => (run ? fieldMax(run.field, channelIndex) : 0), [run, channelIndex])
  // Which cell each plan pixel shows; built once per run.
  const cellMap = useMemo(
    () =>
      run
        ? buildCellMap({
            layout,
            openDoorIds: run.openDoorIds,
            boundary: run.indoor.boundary,
            holes: run.indoor.holes,
            field: run.field,
            mpp: run.mpp,
          })
        : null,
    [run, layout],
  )
  const overlay = useMemo<PlanOverlay | null>(() => {
    if (!run || !cellMap || !showResult) return null
    return {
      source: renderFrame(run.field, cellMap, shownFrame, channelIndex, max),
      x: 0,
      y: 0,
      width: layout.width_px,
      height: layout.height_px,
    }
  }, [run, cellMap, showResult, shownFrame, channelIndex, max, layout])

  // Background grid: 1 m lines (quarter lines when zoomed in, matching the
  // 25 cm cells), aligned with the simulation grid at the outline's corner.
  const calibration = project.calibration
  const grid = useMemo<PlanGrid | null>(() => {
    const mpp = calibration ? metersPerPixel(calibration.start, calibration.end, calibration.distance_m) : null
    if (!mpp) return null
    const points = indoor?.boundary ?? []
    return {
      spacing: 1 / mpp,
      originX: points.length ? Math.min(...points.map((p) => p.x)) : 0,
      originY: points.length ? Math.min(...points.map((p) => p.y)) : 0,
    }
  }, [calibration, indoor])

  const productName = (definitionId: string) => {
    const d = products.get(definitionId)
    return d ? d.name.trim() || TYPE_INFO[d.type].label : '지워진 제품'
  }

  return (
    <div className="ws">
      <PlanViewer
        image={plan.image}
        layout={layout}
        imageOpacity={0.45}
        paper={project.view.showImage}
        grid={grid}
        wallThickness={wallThickness}
        overlay={overlay}
        markers={markers}
        selectedMarkerId={selectedId}
        onMarkerSelect={placing ? undefined : setSelectedId}
        onMarkerMove={placing ? undefined : (id, position) =>
          updateScenario((s) => ({ ...s, placements: s.placements.map((p) => (p.id === id ? { ...p, position } : p)) }))
        }
        onPlanClick={placing ? place : undefined}
        openDoorIds={openDoorIds}
        onDoorToggle={toggleDoor}
        toolbar={
          <>
            <button
              type="button"
              onClick={() => onChange((p) => ({ ...p, view: { ...p.view, showImage: !p.view.showImage } }))}
            >
              {project.view.showImage ? '평면도 숨기기' : '평면도 보이기'}
            </button>
            <button type="button" onClick={() => onChange((p) => ({ ...p, step: 'thickness' }))}>
              공간 설정
            </button>
          </>
        }
      />

      <aside className="ws-panel" aria-label="작업 패널">
        <section className="ws-panel__section">
          <h2 className="ws-panel__title">배치안</h2>
          <ScenarioList project={project} onChange={onChange} />
        </section>

        <section className="ws-panel__section">
          <h2 className="ws-panel__title">
            디퓨저 <span className="ws-panel__count">{scenario.placements.length} / {MAX_PLACEMENTS}</span>
          </h2>
          {scenario.placements.length > 0 && (
            <ol className="ws-placements">
              {scenario.placements.map((p, i) => (
                <li key={p.id} className={p.id === selectedId ? 'is-selected' : ''}>
                  <button type="button" className="ws-placements__item" onClick={() => setSelectedId(p.id)}>
                    <span className="ws-placements__number">{i + 1}</span>
                    <span className="ws-placements__name">{productName(p.definition_id)}</span>
                  </button>
                  <button
                    type="button"
                    className="ws-placements__remove"
                    aria-label={`${i + 1}번 디퓨저 빼기`}
                    onClick={() => removePlacement(p.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ol>
          )}

          {diffusers.length === 0 ? (
            <>
              <p className="note">등록한 디퓨저 제품이 없어요.</p>
              <button type="button" onClick={() => onChange((p) => ({ ...p, step: 'diffusers' }))}>
                디퓨저 제품 등록하기
              </button>
            </>
          ) : placing ? (
            <div className="ws-placing">
              <p className="note">평면도에서 {productName(placing)}을(를) 놓을 곳을 클릭하세요.</p>
              <button type="button" onClick={cancelPlacing}>
                취소
              </button>
            </div>
          ) : choosingProduct ? (
            <div className="ws-products">
              <p className="note">어떤 디퓨저를 놓을까요?</p>
              {diffusers.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => {
                    setChoosingProduct(false)
                    setPlacing(d.id)
                    setSelectedId(null)
                  }}
                >
                  <span>{d.name.trim() || TYPE_INFO[d.type].label}</span>
                  <span className="ws-products__type">{TYPE_INFO[d.type].label}</span>
                </button>
              ))}
              <button type="button" className="link-button" onClick={() => setChoosingProduct(false)}>
                취소
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="ws-panel__add"
              disabled={scenario.placements.length >= MAX_PLACEMENTS}
              onClick={() => setChoosingProduct(true)}
            >
              + 디퓨저 추가하기
            </button>
          )}
        </section>

        <section className="ws-panel__section">
          <div className="ws-duration">
            <span className="ws-duration__label" id="ws-duration-label">
              시뮬레이션 시간
            </span>
            <div className="ws-duration__choices" role="radiogroup" aria-labelledby="ws-duration-label">
              {SIMULATION_HOURS.map((h) => (
                <button
                  key={h}
                  type="button"
                  role="radio"
                  aria-checked={project.simulationHours === h}
                  aria-label={`${h}시간`}
                  className={project.simulationHours === h ? 'is-selected' : ''}
                  disabled={running}
                  onClick={() => onChange((p) => ({ ...p, simulationHours: h }))}
                >
                  {h}
                </button>
              ))}
              <span className="ws-duration__unit">시간</span>
            </div>
            {estimate !== null && scenario.placements.length > 0 && (
              <p className={`note${estimate > MAX_RUN_SECONDS * 0.8 ? ' note--error' : ''}`}>
                {estimate > MAX_RUN_SECONDS * 0.8
                  ? `예상 계산 시간이 ${MAX_RUN_SECONDS}초에 가까워 중간에 멈출 수 있어요. 시간을 줄여 주세요.`
                  : `예상 계산 시간 약 ${formatEstimate(estimate)}`}
              </p>
            )}
          </div>
          <button type="button" className="button--primary ws-panel__start" disabled={running} onClick={start}>
            {running ? PHASE_TEXT[job.phase] : run && !stale ? '시뮬레이션 다시 하기' : '시뮬레이션 시작하기'}
          </button>
          {running && job.scenarioId !== scenario.id && (
            <p className="note">다른 배치안을 계산하고 있어요.</p>
          )}
          {errorForScenario?.map((message) => (
            <p key={message} className="note note--error">
              {message}
            </p>
          ))}
          {saveStatus === 'failed' && <p className="note note--error">이 브라우저에 저장하지 못했어요.</p>}
        </section>
      </aside>

      {(placing || placeHint) && (
        <p className="ws-hint" role="status">
          {placeHint ?? '놓을 곳을 클릭하세요 · Esc로 취소'}
        </p>
      )}

      {run && (
        <PlaybackBar
          times={run.field.times}
          frame={shownFrame}
          playing={playing}
          visible={showResult}
          stale={stale}
          channels={run.field.placementIds.map((id) => {
            const index = scenario.placements.findIndex((p) => p.id === id)
            return { id, label: index >= 0 ? `${index + 1}번 · ${productName(scenario.placements[index].definition_id)}` : '지운 디퓨저' }
          })}
          channel={channelIndex !== null ? channelPlacementId : null}
          onFrame={(f) => {
            setPlaying(false)
            goToFrame(f)
          }}
          onPlay={() => {
            goToFrame(shownFrame >= frameCount - 1 ? 0 : shownFrame)
            setShowResult(true)
            setPlaying(true)
          }}
          onPause={() => setPlaying(false)}
          onChannel={setChannelPlacementId}
          onVisible={(visible) => {
            setShowResult(visible)
            if (!visible) setPlaying(false)
          }}
        />
      )}
    </div>
  )
}
