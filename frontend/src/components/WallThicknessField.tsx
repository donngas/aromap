import { useState } from 'react'

interface WallThicknessFieldProps {
  /** Current thickness in image pixels. */
  value: number
  defaultValue: number
  max: number
  /** Receives null when the value equals the default, so the default can follow the image. */
  onChange: (value: number | null) => void
}

export function WallThicknessField({ value, defaultValue, max, onChange }: WallThicknessFieldProps) {
  // Keeps an empty or partial number field editable without snapping the drawing.
  const [input, setInput] = useState(String(value))

  const commit = (next: number) => onChange(next === defaultValue ? null : next)
  const apply = (raw: number) => {
    const clamped = Math.min(max, Math.max(1, Math.round(raw)))
    commit(clamped)
    setInput(String(clamped))
  }

  return (
    <div className="field">
      <div className="field__head">
        <label htmlFor="wall-thickness">벽 두께</label>
        <button type="button" className="link-button" disabled={value === defaultValue} onClick={() => apply(defaultValue)}>
          기본값
        </button>
      </div>
      <div className="field__row">
        <input
          type="range"
          aria-label="벽 두께 슬라이더"
          min={1}
          max={max}
          step={1}
          value={value}
          onChange={(event) => apply(Number(event.target.value))}
        />
        <span className="number-input">
          <input
            id="wall-thickness"
            type="number"
            min={1}
            max={max}
            step={1}
            value={input}
            onChange={(event) => {
              setInput(event.target.value)
              const next = Number(event.target.value)
              if (event.target.value !== '' && next >= 1) commit(Math.min(max, Math.round(next)))
            }}
            onBlur={() => apply(Number(input) || defaultValue)}
          />
          px
        </span>
      </div>
      <p className="field__hint">화면에 보이는 두께만 바뀌고, 향 확산 계산에는 쓰이지 않아요.</p>
    </div>
  )
}
