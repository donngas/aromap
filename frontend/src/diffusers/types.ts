// Raw user input for a diffuser product. Placements (position, count) are set
// later in the workspace; an API adapter maps this to ConsumerDiffuserDefinition.

export const DIFFUSER_TYPES = ['reed', 'ultrasonic', 'nebulizer', 'candle'] as const
export type DiffuserType = (typeof DIFFUSER_TYPES)[number]

export const INTENSITIES = ['low', 'mid', 'high'] as const
export type Intensity = (typeof INTENSITIES)[number]

export interface DiffuserDraft {
  id: string
  name: string
  type: DiffuserType
  /** ml for liquids, g for candles and wax. */
  volume: number | null
  durationDays: number | null
  /** Powered and burning types only; null means always on (24h). */
  dailyHours: number | null
  /** Powered types only. */
  intensity: Intensity | null
  scentFamily: string | null
  memo: string
  usesExampleValues: boolean
}

interface TypeInfo {
  label: string
  description: string
  unit: 'ml' | 'g'
  /** Runs only part of the day, so daily hours matter. */
  timed: boolean
  /** Electric devices with an intensity setting. */
  powered: boolean
}

export const TYPE_INFO: Record<DiffuserType, TypeInfo> = {
  reed: { label: '리드', description: '스틱으로 자연 확산', unit: 'ml', timed: false, powered: false },
  ultrasonic: { label: '초음파', description: '물과 섞어 가습하며 분사', unit: 'ml', timed: true, powered: true },
  nebulizer: { label: '네뷸라이저', description: '원액을 미세 분사', unit: 'ml', timed: true, powered: true },
  candle: { label: '향초·왁스', description: '태우거나 녹여서 발향', unit: 'g', timed: true, powered: false },
}

export const INTENSITY_LABELS: Record<Intensity, string> = { low: '약', mid: '중', high: '강' }

export const SCENT_FAMILIES = ['시트러스', '플로럴', '우디', '허브·그린', '머스크·파우더리', '스위트', '기타']

export function createDiffuser(type: DiffuserType, index: number): DiffuserDraft {
  return {
    id: crypto.randomUUID(),
    name: `디퓨저 ${index}`,
    type,
    volume: null,
    durationDays: null,
    dailyHours: null,
    intensity: TYPE_INFO[type].powered ? 'mid' : null,
    scentFamily: null,
    memo: '',
    usesExampleValues: false,
  }
}
