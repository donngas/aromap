import { TYPE_INFO, type DiffuserDraft, type DiffuserType } from './types.ts'

// TODO: Provisional placeholders so "잘 모르겠어요" works end to end. Replace with
// values researched from real product specs; the source is not verified yet.
export const EXAMPLE_SPECS: Record<DiffuserType, { volume: number; durationDays: number }> = {
  reed: { volume: 200, durationDays: 60 },
  ultrasonic: { volume: 10, durationDays: 10 },
  nebulizer: { volume: 100, durationDays: 30 },
  candle: { volume: 200, durationDays: 10 },
}

export interface ConsumptionEstimate {
  perDay: number
  unit: 'ml' | 'g'
  /** Consumption while running, for timed types with daily hours set. */
  perOperatingHour: number | null
  fromExample: boolean
}

export function validateDiffuser(draft: DiffuserDraft): string[] {
  const errors: string[] = []
  if (!draft.name.trim()) errors.push('이름을 입력해 주세요.')
  if (!draft.usesExampleValues) {
    if (!(draft.volume !== null && draft.volume > 0)) errors.push('용량을 입력해 주세요.')
    if (!(draft.durationDays !== null && draft.durationDays > 0)) errors.push('사용 기간을 입력해 주세요.')
  }
  if (draft.dailyHours !== null && !(draft.dailyHours > 0 && draft.dailyHours <= 24)) {
    errors.push('하루 작동 시간은 0보다 크고 24 이하여야 해요.')
  }
  return errors
}

/**
 * Average consumption assuming a constant release over the stated duration.
 * Intensity is stored but not applied yet; how it scales the stated duration is
 * still to be agreed with the backend simulation.
 */
export function estimateConsumption(draft: DiffuserDraft): ConsumptionEstimate | null {
  if (validateDiffuser(draft).length > 0) return null
  const spec = draft.usesExampleValues
    ? EXAMPLE_SPECS[draft.type]
    : { volume: draft.volume!, durationDays: draft.durationDays! }
  const perDay = spec.volume / spec.durationDays
  const timed = TYPE_INFO[draft.type].timed && draft.dailyHours !== null
  return {
    perDay,
    unit: TYPE_INFO[draft.type].unit,
    perOperatingHour: timed ? perDay / draft.dailyHours! : null,
    fromExample: draft.usesExampleValues,
  }
}
