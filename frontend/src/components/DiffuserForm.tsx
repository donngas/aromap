import { EXAMPLE_SPECS, estimateConsumption, validateDiffuser } from '../diffusers/emission.ts'
import {
  createDiffuser,
  DIFFUSER_TYPES,
  INTENSITIES,
  INTENSITY_LABELS,
  SCENT_FAMILIES,
  TYPE_INFO,
  type DiffuserDraft,
  type DiffuserType,
} from '../diffusers/types.ts'

interface DiffuserFormProps {
  diffusers: DiffuserDraft[]
  onChange: (diffusers: DiffuserDraft[]) => void
}

export function DiffuserForm({ diffusers, onChange }: DiffuserFormProps) {
  const update = (id: string, patch: Partial<DiffuserDraft>) =>
    onChange(diffusers.map((d) => (d.id === id ? { ...d, ...patch } : d)))

  const add = (type: DiffuserType, fromExample: boolean) => {
    const draft = createDiffuser(type, diffusers.length + 1)
    if (fromExample) {
      draft.name = `${TYPE_INFO[type].label} 예시`
      draft.usesExampleValues = true
    }
    onChange([...diffusers, draft])
  }

  return (
    <div className="diffusers">
      {diffusers.length === 0 && <p className="note">사용할 디퓨저 제품을 등록하세요. 개수와 위치는 다음 화면에서 정해요.</p>}
      {diffusers.map((d) => (
        <DiffuserCard
          key={d.id}
          draft={d}
          onChange={(patch) => update(d.id, patch)}
          onRemove={() => onChange(diffusers.filter((x) => x.id !== d.id))}
        />
      ))}
      <div className="row">
        <button type="button" onClick={() => add('reed', false)}>
          + 디퓨저 추가
        </button>
        <select
          value=""
          onChange={(event) => {
            if (event.target.value) add(event.target.value as DiffuserType, true)
          }}
        >
          <option value="">예시로 추가…</option>
          {DIFFUSER_TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_INFO[type].label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

interface DiffuserCardProps {
  draft: DiffuserDraft
  onChange: (patch: Partial<DiffuserDraft>) => void
  onRemove: () => void
}

function DiffuserCard({ draft, onChange, onRemove }: DiffuserCardProps) {
  const info = TYPE_INFO[draft.type]
  const example = EXAMPLE_SPECS[draft.type]
  const errors = validateDiffuser(draft)
  const estimate = estimateConsumption(draft)

  const changeType = (type: DiffuserType) =>
    onChange({
      type,
      intensity: TYPE_INFO[type].powered ? (draft.intensity ?? 'mid') : null,
      dailyHours: TYPE_INFO[type].timed ? draft.dailyHours : null,
    })

  return (
    <fieldset className="card">
      <div className="row row--between">
        <input
          className="card__name"
          aria-label="디퓨저 이름"
          value={draft.name}
          onChange={(event) => onChange({ name: event.target.value })}
        />
        <button type="button" onClick={onRemove}>
          삭제
        </button>
      </div>

      <div className="form-row">
        <span className="form-row__label">유형</span>
        <div className="choices">
          {DIFFUSER_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              className={draft.type === type ? 'is-selected' : ''}
              aria-pressed={draft.type === type}
              title={TYPE_INFO[type].description}
              onClick={() => changeType(type)}
            >
              {TYPE_INFO[type].label}
            </button>
          ))}
        </div>
      </div>

      <div className="form-row">
        <span className="form-row__label">용량</span>
        <NumberInput
          value={draft.usesExampleValues ? example.volume : draft.volume}
          disabled={draft.usesExampleValues}
          unit={info.unit}
          label="용량"
          onChange={(volume) => onChange({ volume })}
        />
      </div>
      <div className="form-row">
        <span className="form-row__label">사용 기간</span>
        <NumberInput
          value={draft.usesExampleValues ? example.durationDays : draft.durationDays}
          disabled={draft.usesExampleValues}
          unit="일"
          label="사용 기간"
          onChange={(durationDays) => onChange({ durationDays })}
        />
      </div>
      <label className="form-row form-row--check">
        <span className="form-row__label" />
        <span>
          <input
            type="checkbox"
            checked={draft.usesExampleValues}
            onChange={(event) => onChange({ usesExampleValues: event.target.checked })}
          />{' '}
          잘 모르겠어요 (예시값 사용)
        </span>
      </label>

      {info.powered && (
        <div className="form-row">
          <span className="form-row__label">강도</span>
          <div className="choices">
            {INTENSITIES.map((level) => (
              <button
                key={level}
                type="button"
                className={draft.intensity === level ? 'is-selected' : ''}
                aria-pressed={draft.intensity === level}
                onClick={() => onChange({ intensity: level })}
              >
                {INTENSITY_LABELS[level]}
              </button>
            ))}
          </div>
        </div>
      )}
      {info.timed && (
        <div className="form-row">
          <span className="form-row__label">하루 작동</span>
          <NumberInput
            value={draft.dailyHours}
            unit="시간"
            label="하루 작동 시간"
            placeholder="24"
            onChange={(dailyHours) => onChange({ dailyHours })}
          />
        </div>
      )}

      <div className="form-row">
        <span className="form-row__label">향 계열</span>
        <div className="choices">
          {SCENT_FAMILIES.map((family) => (
            <button
              key={family}
              type="button"
              className={draft.scentFamily === family ? 'is-selected' : ''}
              aria-pressed={draft.scentFamily === family}
              onClick={() => onChange({ scentFamily: draft.scentFamily === family ? null : family })}
            >
              {family}
            </button>
          ))}
        </div>
      </div>
      <div className="form-row">
        <span className="form-row__label">메모</span>
        <input
          className="grow"
          aria-label="메모"
          value={draft.memo}
          placeholder="선택"
          onChange={(event) => onChange({ memo: event.target.value })}
        />
      </div>

      {estimate ? (
        <p className="note">
          하루 약 {formatAmount(estimate.perDay)}
          {estimate.unit} 소모
          {estimate.perOperatingHour !== null &&
            ` · 작동 중 시간당 ${formatAmount(estimate.perOperatingHour)}${estimate.unit}`}
          {estimate.fromExample && ' (임시 예시값 기준)'}
        </p>
      ) : (
        <p className="note note--error">{errors[0]}</p>
      )}
    </fieldset>
  )
}

interface NumberInputProps {
  value: number | null
  unit: string
  label: string
  placeholder?: string
  disabled?: boolean
  onChange: (value: number | null) => void
}

function NumberInput({ value, unit, label, placeholder, disabled, onChange }: NumberInputProps) {
  return (
    <span className="number-input">
      <input
        type="number"
        min="0"
        step="any"
        aria-label={label}
        placeholder={placeholder}
        disabled={disabled}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}
      />
      {unit}
    </span>
  )
}

function formatAmount(value: number): string {
  return value >= 10 ? value.toFixed(0) : value >= 1 ? value.toFixed(1) : value.toFixed(2)
}
