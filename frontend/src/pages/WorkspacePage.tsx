import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api/floorPlans.ts'
import { AnalysisPanel, type ScenarioComparison } from '../components/AnalysisPanel.tsx'
import { FloatingWindow } from '../components/FloatingWindow.tsx'
import { PlaybackBar } from '../components/PlaybackBar.tsx'
import { PlanViewer, type PlanDevice, type PlanGrid, type PlanMarker, type PlanOverlay } from '../components/PlanViewer.tsx'
import { DiffuserGlyph } from '../components/DiffuserGlyph.tsx'
import { ScenarioList } from '../components/ScenarioList.tsx'
import { hexToRgb, NO_SCENT_COLOR, scentColor, type Rgb } from '../diffusers/scents.ts'
import { TYPE_INFO, type DiffuserType } from '../diffusers/types.ts'
import { metersPerPixel, pointInDomain } from '../floorPlan/geometry.ts'
import type { Layout, PixelPoint } from '../floorPlan/layout.ts'
import { defaultWallThickness } from '../floorPlan/layoutStyle.ts'
import type { PlanImage } from '../floorPlan/loadImage.ts'
import {
  AIRFLOW_STRENGTHS,
  MAX_AIRFLOW_DEVICES,
  OUTDOOR_CONDITIONS,
  SIMULATION_HOURS,
  type AirflowDevice,
  type AirflowStrength,
  type OutdoorConditions,
  type ProjectDocument,
  type Scenario,
} from '../project/types.ts'
import type { SaveStatus } from '../project/useAutosave.ts'
import { coverageAt } from '../simulation/analysis.ts'
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
  openOpeningIds: ReadonlySet<string>
  indoor: { boundary: PixelPoint[]; holes: PixelPoint[][] }
  hours: number
  /** Scent colour of each result channel, in channel order. */
  channelColors: Rgb[]
  /** Scent families in the run, for the legend. */
  scents: { label: string; color: string }[]
}

/** What the next click on the plan places. */
type Placing = { kind: 'diffuser'; productId: string } | { kind: AirflowDevice['type'] }

/** Small popup beside a clicked diffuser or device, in workspace coordinates. */
type ItemMenu = { kind: 'diffuser' | 'device'; id: string; x: number; y: number }

const DEVICE_LABELS: Record<AirflowDevice['type'], string> = { fan: '선풍기', ac: '에어컨' }
const STRENGTH_LABELS: Record<AirflowStrength, string> = { low: '약', medium: '중', high: '강' }

/** Window width; on narrow screens the analysis window starts folded. */
const WINDOW_WIDTH = 280
const NARROW_SCREEN = 760

/** "5초 미만", "약 20초", "약 1분 10초"-style wording for an estimate. */
function formatEstimate(seconds: number): string {
  if (seconds < 5) return '5초 미만'
  const total = Math.round(seconds / 5) * 5
  return total < 60 ? `${total}초` : `${Math.floor(total / 60)}분${total % 60 ? ` ${total % 60}초` : ''}`
}

const OUTDOOR_LABELS: Record<OutdoorConditions, string> = { calm: '바람 없음', moderate: '약한 바람', breezy: '강한 바람' }

/** Eight directions the wind can blow toward, in degrees clockwise from the plan's right. */
const WIND_DIRECTIONS = [
  { degrees: 0, arrow: '→', label: '오른쪽으로' },
  { degrees: 45, arrow: '↘', label: '오른쪽 아래로' },
  { degrees: 90, arrow: '↓', label: '아래로' },
  { degrees: 135, arrow: '↙', label: '왼쪽 아래로' },
  { degrees: 180, arrow: '←', label: '왼쪽으로' },
  { degrees: 225, arrow: '↖', label: '왼쪽 위로' },
  { degrees: 270, arrow: '↑', label: '위로' },
  { degrees: 315, arrow: '↗', label: '오른쪽 위로' },
]

const PHASE_TEXT: Record<RunPhase, string> = {
  submitting: '요청을 보내는 중…',
  queued: '계산 순서를 기다리는 중…',
  running: '향이 퍼지는 모습을 계산하는 중…',
  downloading: '결과를 받는 중…',
}

/**
 * The plan fills the screen. Two movable, foldable windows float over it:
 * "작업" (left) picks the scenario, places diffusers and starts the
 * simulation; "분석" (right) reads the result. Results play back over the plan
 * with a bar at the bottom.
 */
export function WorkspacePage({ plan, project, layout, saveStatus, onChange }: WorkspacePageProps) {
  const scenario = project.scenarios.find((s) => s.id === project.activeScenarioId) ?? project.scenarios[0]
  const wallThickness = project.view.wallThickness ?? defaultWallThickness(plan.width, plan.height)
  const { indoor, diffusers } = project
  const products = useMemo(() => new Map(diffusers.map((d) => [d.id, d])), [diffusers])

  // The app header floats over the plan here; fitting keeps the plan below it.
  const [headerHeight] = useState(
    () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-h')) || 0,
  )
  // Starting window places, just below the header. Narrow screens: "분석"
  // starts folded near the bottom, above the playback bar.
  const [windowPlaces] = useState(() => {
    const narrow = window.innerWidth < NARROW_SCREEN
    const gap = narrow ? 12 : 16
    return {
      narrow,
      work: { x: gap, y: headerHeight + gap },
      analysis: { x: gap, y: narrow ? window.innerHeight - 150 : headerHeight + gap },
    }
  })
  const wsRef = useRef<HTMLDivElement>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [placing, setPlacing] = useState<Placing | null>(null)
  const [placeHint, setPlaceHint] = useState<string | null>(null)
  const [itemMenu, setItemMenu] = useState<ItemMenu | null>(null)

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
    setItemMenu(null)
  }

  const updateDevice = (id: string, patch: Partial<AirflowDevice>) =>
    updateScenario((s) => ({ ...s, airflow_devices: s.airflow_devices.map((d) => (d.id === id ? { ...d, ...patch } : d)) }))

  const removeDevice = (id: string) => {
    updateScenario((s) => ({ ...s, airflow_devices: s.airflow_devices.filter((d) => d.id !== id) }))
    if (selectedDeviceId === id) setSelectedDeviceId(null)
    setItemMenu(null)
  }

  const cancelPlacing = () => {
    setPlacing(null)
    setPlaceHint(null)
  }

  /** Picking a tool tile starts placing; picking the same tile again cancels. */
  const choose = (next: Placing) => {
    setItemMenu(null)
    setSelectedId(null)
    setSelectedDeviceId(null)
    setPlaceHint(null)
    setPlacing((current) => (current && sameTool(current, next) ? null : next))
  }

  const place = (position: PixelPoint) => {
    if (!placing) return
    if (indoor && !pointInDomain(position, indoor.boundary, indoor.holes)) {
      setPlaceHint('실내 영역 안을 클릭해 주세요.')
      return
    }
    const id = crypto.randomUUID()
    if (placing.kind === 'diffuser') {
      const productId = placing.productId
      updateScenario((s) => ({
        ...s,
        placements: [...s.placements, { id, definition_id: productId, position, strength_override: null, enabled: true }],
      }))
      setSelectedId(id)
    } else {
      // New devices blow to the right; drag the arrow to turn them.
      const device: AirflowDevice = { id, type: placing.kind, position, direction_degrees: 0, strength: 'medium' }
      updateScenario((s) => ({ ...s, airflow_devices: [...s.airflow_devices, device] }))
      setSelectedDeviceId(id)
    }
    cancelPlacing()
  }

  // Delete removes the selected diffuser or device; Escape leaves placing mode.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return
      if (event.key === 'Escape') {
        setPlacing(null)
        setPlaceHint(null)
        setItemMenu(null)
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedId || selectedDeviceId)) {
        setItemMenu(null)
        onChange((p) => ({
          ...p,
          scenarios: p.scenarios.map((s) =>
            s.id === p.activeScenarioId
              ? {
                  ...s,
                  placements: s.placements.filter((pl) => pl.id !== selectedId),
                  airflow_devices: s.airflow_devices.filter((d) => d.id !== selectedDeviceId),
                }
              : s,
          ),
        }))
        setSelectedId(null)
        setSelectedDeviceId(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, selectedDeviceId, onChange])

  /** Opens the popup for a clicked diffuser or device beside the pointer. */
  const openMenu = (kind: ItemMenu['kind'], id: string, client: { x: number; y: number }) => {
    const box = wsRef.current?.getBoundingClientRect()
    if (box) setItemMenu({ kind, id, x: client.x - box.left, y: client.y - box.top })
  }

  const openOpeningIds = useMemo(
    () => new Set(scenario.opening_states.filter((s) => s.is_open).map((s) => s.opening_id)),
    [scenario.opening_states],
  )
  const toggleOpening = (openingId: string) =>
    updateScenario((s) => {
      const others = s.opening_states.filter((o) => o.opening_id !== openingId)
      return openOpeningIds.has(openingId) ? { ...s, opening_states: others } : { ...s, opening_states: [...others, { opening_id: openingId, is_open: true }] }
    })

  /** Type and scent colour of a placed product; a deleted product shows as a plain reed. */
  const look = (definitionId: string): { type: DiffuserType; color: string } => {
    const d = products.get(definitionId)
    return d ? { type: d.type, color: scentColor(d.scentFamily) } : { type: 'reed', color: NO_SCENT_COLOR }
  }

  const markers = useMemo<PlanMarker[]>(
    () =>
      scenario.placements.map((p, i) => {
        const d = products.get(p.definition_id)
        return {
          id: p.id,
          position: p.position,
          label: String(i + 1),
          type: d?.type ?? 'reed',
          color: d ? scentColor(d.scentFamily) : NO_SCENT_COLOR,
        }
      }),
    [scenario.placements, products],
  )
  const devices = useMemo<PlanDevice[]>(
    () =>
      scenario.airflow_devices.map((d) => ({ id: d.id, kind: d.type, position: d.position, direction: d.direction_degrees })),
    [scenario.airflow_devices],
  )
  /** "선풍기 1", "에어컨 2": devices numbered within their type. */
  const deviceLabels = useMemo(() => {
    const counts = { fan: 0, ac: 0 }
    return new Map(scenario.airflow_devices.map((d) => [d.id, `${DEVICE_LABELS[d.type]} ${++counts[d.type]}`]))
  }, [scenario.airflow_devices])

  /** Distinct scents among the placed diffusers, in placing order. */
  const scentsOf = (placements: Scenario['placements']) => {
    const seen = new Map<string, string>()
    for (const p of placements) {
      const family = products.get(p.definition_id)?.scentFamily
      const label = family ?? '향 미선택'
      if (!seen.has(label)) seen.set(label, scentColor(family ?? null))
    }
    return [...seen].map(([label, color]) => ({ label, color }))
  }

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
    // Colours as placed now, so later edits don't recolour this result.
    const colorOf = new Map(scenario.placements.map((p) => [p.id, hexToRgb(look(p.definition_id).color)]))
    const snapshot = {
      openOpeningIds,
      indoor: { boundary: indoor!.boundary, holes: indoor!.holes },
      hours: project.simulationHours,
      scents: scentsOf(scenario.placements.filter((p) => p.enabled)),
    }
    const controller = new AbortController()
    abortRef.current = controller
    setRunError(null)
    setPlaying(false)
    setJob({ scenarioId, phase: 'submitting' })
    runSimulation(request, (phase) => setJob({ scenarioId, phase }), controller.signal)
      .then((field) => {
        const channelColors = field.placementIds.map((id) => colorOf.get(id) ?? hexToRgb(NO_SCENT_COLOR))
        setRuns((prev) => ({ ...prev, [scenarioId]: { field, key, mpp, channelColors, ...snapshot } }))
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
            openOpeningIds: run.openOpeningIds,
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
      source: renderFrame(run.field, cellMap, shownFrame, channelIndex, max, run.channelColors),
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

  // Analysis: coverage follows playback.
  const coverage = useMemo(() => (run ? coverageAt(run.field, shownFrame) : null), [run, shownFrame])
  const comparisons = useMemo<ScenarioComparison[]>(
    () =>
      project.scenarios.flatMap((s) => {
        const r = runs[s.id]
        if (!r) return []
        const current = buildSimulationRequest(project, s)
        return [
          {
            id: s.id,
            name: s.name,
            coverage: coverageAt(r.field, r.field.times.length - 1),
            hours: r.hours,
            current: s.id === scenario.id,
            stale: !current.ok || current.key !== r.key,
          },
        ]
      }),
    [project, runs, scenario.id],
  )

  const productName = (definitionId: string) => {
    const d = products.get(definitionId)
    return d ? d.name.trim() || TYPE_INFO[d.type].label : '지워진 제품'
  }

  return (
    <div ref={wsRef} className="ws">
      <PlanViewer
        image={plan.image}
        layout={layout}
        imageOpacity={0.45}
        paper={project.view.showImage}
        grid={grid}
        wallThickness={wallThickness}
        overlay={overlay}
        markers={markers}
        devices={devices}
        selectedMarkerId={selectedId}
        onMarkerSelect={placing ? undefined : setSelectedId}
        onMarkerMove={placing ? undefined : (id, position) =>
          updateScenario((s) => ({ ...s, placements: s.placements.map((p) => (p.id === id ? { ...p, position } : p)) }))
        }
        onMarkerClick={(id, client) => openMenu('diffuser', id, client)}
        selectedDeviceId={selectedDeviceId}
        onDeviceSelect={placing ? undefined : setSelectedDeviceId}
        onDeviceMove={placing ? undefined : (id, position) => updateDevice(id, { position })}
        onDeviceRotate={placing ? undefined : (id, direction) => updateDevice(id, { direction_degrees: direction })}
        onDeviceClick={(id, client) => openMenu('device', id, client)}
        onInteract={() => setItemMenu(null)}
        onPlanClick={placing ? place : undefined}
        openOpeningIds={openOpeningIds}
        onOpeningToggle={toggleOpening}
        fitInsetTop={headerHeight}
        fitButton={false}
      />

      <FloatingWindow
        title="작업"
        anchor="left"
        initialX={windowPlaces.work.x}
        initialY={windowPlaces.work.y}
        width={WINDOW_WIDTH}
        minY={headerHeight + 4}
        className="ws-panel"
      >
        <section className="ws-panel__section">
          <h3 className="ws-panel__title">배치안</h3>
          <ScenarioList project={project} onChange={onChange} />
        </section>

        <section className="ws-panel__section">
          <h3 className="ws-panel__title">배치 도구</h3>

          <div className="ws-tools__group">
            <span className="ws-tools__label">
              디퓨저 <span className="ws-panel__count">{scenario.placements.length} / {MAX_PLACEMENTS}</span>
            </span>
            {diffusers.length === 0 ? (
              <>
                <p className="note">등록한 디퓨저 제품이 없어요.</p>
                <button type="button" onClick={() => onChange((p) => ({ ...p, step: 'diffusers' }))}>
                  디퓨저 제품 등록하기
                </button>
              </>
            ) : (
              <ul className="ws-tools">
                {diffusers.map((d) => {
                  const active = placing?.kind === 'diffuser' && placing.productId === d.id
                  return (
                    <li key={d.id}>
                      <button
                        type="button"
                        className={`ws-tool${active ? ' is-active' : ''}`}
                        aria-pressed={active}
                        disabled={!active && scenario.placements.length >= MAX_PLACEMENTS}
                        onClick={() => choose({ kind: 'diffuser', productId: d.id })}
                      >
                        <span className="ws-tool__glyph">
                          <DiffuserGlyph type={d.type} color={scentColor(d.scentFamily)} size={28} />
                        </span>
                        <span className="ws-tool__text">
                          <span className="ws-tool__name">{d.name.trim() || TYPE_INFO[d.type].label}</span>
                          <span className="ws-tool__type">
                            {TYPE_INFO[d.type].label}
                            {d.scentFamily ? ` · ${d.scentFamily}` : ''}
                          </span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="ws-tools__group">
            <span className="ws-tools__label">
              공기 기기{' '}
              <span className="ws-panel__count">
                {scenario.airflow_devices.length} / {MAX_AIRFLOW_DEVICES}
              </span>
            </span>
            <ul className="ws-tools ws-tools--pair">
              {(['fan', 'ac'] as const).map((kind) => {
                const active = placing?.kind === kind
                return (
                  <li key={kind}>
                    <button
                      type="button"
                      className={`ws-tool${active ? ' is-active' : ''}`}
                      aria-pressed={active}
                      disabled={!active && scenario.airflow_devices.length >= MAX_AIRFLOW_DEVICES}
                      onClick={() => choose({ kind })}
                    >
                      <span className="ws-tool__glyph ws-tool__glyph--device">
                        {kind === 'fan' ? <FanIcon /> : <AcIcon />}
                      </span>
                      <span className="ws-tool__name">{DEVICE_LABELS[kind]}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>

          <p className="field__hint">
            {placing
              ? '평면도에서 놓을 곳을 클릭하세요. 다시 누르면 취소돼요.'
              : '고른 뒤 평면도를 클릭해 놓아요. 놓은 것은 끌어서 옮기고, 클릭하면 옵션이 나와요. 바람 방향은 화살표 끝을 끌어서 바꿔요.'}
          </p>
        </section>

        <section className="ws-panel__section">
          <h3 className="ws-panel__title">바깥 날씨</h3>
          <div className="ws-segment" role="radiogroup" aria-label="바깥 날씨">
            {OUTDOOR_CONDITIONS.map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={project.outdoor.conditions === c}
                className={project.outdoor.conditions === c ? 'is-selected' : ''}
                disabled={running}
                onClick={() => onChange((p) => ({ ...p, outdoor: { ...p.outdoor, conditions: c } }))}
              >
                {OUTDOOR_LABELS[c]}
              </button>
            ))}
          </div>
          {project.outdoor.conditions !== 'calm' && (
            <div className="ws-wind">
              <span className="ws-duration__label" id="ws-wind-label">
                바람이 부는 방향
              </span>
              <div className="ws-wind__dirs" role="radiogroup" aria-labelledby="ws-wind-label">
                {WIND_DIRECTIONS.map(({ degrees, arrow, label }) => (
                  <button
                    key={degrees}
                    type="button"
                    role="radio"
                    aria-checked={project.outdoor.wind_direction_degrees === degrees}
                    aria-label={label}
                    title={label}
                    className={project.outdoor.wind_direction_degrees === degrees ? 'is-selected' : ''}
                    disabled={running}
                    onClick={() =>
                      onChange((p) => ({ ...p, outdoor: { ...p.outdoor, wind_direction_degrees: degrees } }))
                    }
                  >
                    {arrow}
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="field__hint">
            바깥 공기는 열린 문과 창문으로 드나들어요. 평면도에서 문이나 창문을 클릭하면 열고 닫을 수 있어요.
          </p>
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

        <section className="ws-panel__section">
          <label className="ws-switch">
            <span>평면도 보이기</span>
            <input
              type="checkbox"
              role="switch"
              checked={project.view.showImage}
              onChange={(event) => onChange((p) => ({ ...p, view: { ...p.view, showImage: event.target.checked } }))}
            />
          </label>
        </section>
      </FloatingWindow>

      <FloatingWindow
        title="분석"
        anchor="right"
        initialX={windowPlaces.analysis.x}
        initialY={windowPlaces.analysis.y}
        width={WINDOW_WIDTH}
        minY={headerHeight + 4}
        initialCollapsed={windowPlaces.narrow}
        className="ws-panel ws-analysis"
      >
        <AnalysisPanel
          coverage={coverage}
          time={run ? (run.field.times[shownFrame] ?? 0) : null}
          running={running && job.scenarioId === scenario.id}
          comparisons={comparisons}
          scents={run ? run.scents : scentsOf(scenario.placements)}
          onSelectScenario={(id) => onChange((p) => ({ ...p, activeScenarioId: id }))}
        />
      </FloatingWindow>

      {itemMenu?.kind === 'diffuser' && scenario.placements.some((p) => p.id === itemMenu.id) && (
        <div className="ws-marker-menu" style={{ left: itemMenu.x + 14, top: itemMenu.y + 10 }}>
          <span className="ws-marker-menu__name">
            {productName(scenario.placements.find((p) => p.id === itemMenu.id)!.definition_id)}
          </span>
          <button type="button" className="ws-marker-menu__delete" onClick={() => removePlacement(itemMenu.id)}>
            <TrashIcon />
            삭제
          </button>
        </div>
      )}

      {itemMenu?.kind === 'device' &&
        (() => {
          const device = scenario.airflow_devices.find((d) => d.id === itemMenu.id)
          if (!device) return null
          return (
            <div className="ws-marker-menu" style={{ left: itemMenu.x + 14, top: itemMenu.y + 10 }}>
              <span className="ws-marker-menu__name">{deviceLabels.get(device.id)}</span>
              <div className="ws-marker-menu__strength" role="radiogroup" aria-label="세기">
                {AIRFLOW_STRENGTHS.map((strength) => (
                  <button
                    key={strength}
                    type="button"
                    role="radio"
                    aria-checked={device.strength === strength}
                    className={device.strength === strength ? 'is-selected' : ''}
                    onClick={() => updateDevice(device.id, { strength })}
                  >
                    {STRENGTH_LABELS[strength]}
                  </button>
                ))}
              </div>
              <button type="button" className="ws-marker-menu__delete" onClick={() => removeDevice(device.id)}>
                <TrashIcon />
                삭제
              </button>
            </div>
          )
        })()}

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

function sameTool(a: Placing, b: Placing): boolean {
  if (a.kind === 'diffuser' && b.kind === 'diffuser') return a.productId === b.productId
  return a.kind === b.kind
}

/** A fan: three blades around a hub, on a stand. */
function FanIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="12" cy="10" r="8" />
      <circle cx="12" cy="10" r="1.4" />
      <path d="M12 8.6c-.5-2.4.3-4.4 2.2-4.6 1.4.1 1.8 1.6.6 2.9L12 8.6ZM13.3 10.6c2.3.8 3.6 2.5 2.8 4.2-.7 1.2-2.2.9-2.8-.7l0-3.5ZM10.7 10.6c-1.8 1.6-3.9 1.9-4.9.3-.6-1.2.4-2.4 2.1-2.2l2.8 1.9Z" strokeLinejoin="round" />
      <path d="M12 18v3M8.5 21h7" strokeLinecap="round" />
    </svg>
  )
}

/** A wall-mounted air conditioner with airflow lines. */
function AcIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <rect x="2.5" y="4" width="19" height="8.5" rx="2" />
      <path d="M5.5 9.5h13" strokeLinecap="round" />
      <path d="M7 15.5c0 1.5-1 2-1 3.5M12 15.5v4M17 15.5c0 1.5 1 2 1 3.5" strokeLinecap="round" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M2 3.5h10M5.5 3.5V2h3v1.5M3.5 3.5l.6 8.5h5.8l.6-8.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
