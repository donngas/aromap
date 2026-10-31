import { formatSimTime as formatTime } from '../simulation/format.ts'

interface PlaybackBarProps {
  /** Sample times in seconds. */
  times: number[]
  frame: number
  playing: boolean
  /** Whether the field is drawn over the plan. */
  visible: boolean
  /** The scenario changed after this result was computed. */
  stale: boolean
  /** Placement channels, in result order. */
  channels: { id: string; label: string }[]
  /** Highlighted placement, or null for all of them together. */
  channel: string | null
  onFrame: (frame: number) => void
  onPlay: () => void
  onPause: () => void
  onChannel: (placementId: string | null) => void
  onVisible: (visible: boolean) => void
}

/** Plays a simulation result back over the plan. */
export function PlaybackBar({
  times,
  frame,
  playing,
  visible,
  stale,
  channels,
  channel,
  onFrame,
  onPlay,
  onPause,
  onChannel,
  onVisible,
}: PlaybackBarProps) {
  const end = times[times.length - 1] ?? 0

  if (!visible) {
    return (
      <div className="playback playback--collapsed">
        <button type="button" onClick={() => onVisible(true)}>
          시뮬레이션 결과 보기
        </button>
      </div>
    )
  }

  return (
    <div className="playback" role="group" aria-label="시뮬레이션 재생">
      {stale && <p className="playback__stale">배치가 바뀌었어요. 다시 시작하면 새 배치로 계산해요.</p>}
      <div className="playback__row">
        <button
          type="button"
          className="playback__play"
          aria-label={playing ? '일시 정지' : '재생'}
          onClick={playing ? onPause : onPlay}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <input
          type="range"
          className="playback__slider"
          aria-label="시간"
          min={0}
          max={Math.max(0, times.length - 1)}
          value={frame}
          onChange={(event) => onFrame(Number(event.target.value))}
        />
        <span className="playback__time">
          {formatTime(times[frame] ?? 0)} <span className="playback__end">/ {formatTime(end)}</span>
        </span>
      </div>
      <div className="playback__row playback__row--meta">
        {channels.length > 1 && (
          <select aria-label="보여 줄 디퓨저" value={channel ?? ''} onChange={(event) => onChannel(event.target.value || null)}>
            <option value="">모든 디퓨저</option>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        )}
        <button type="button" className="link-button" onClick={() => onVisible(false)}>
          결과 숨기기
        </button>
      </div>
    </div>
  )
}

