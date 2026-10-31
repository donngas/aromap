/** "45초", "12분 30초", "2시간 15분": seconds are dropped once hours appear. */
export function formatSimTime(seconds: number): string {
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return m === 0 ? `${h}시간` : `${h}시간 ${m}분`
  if (m === 0) return `${s}초`
  return s === 0 ? `${m}분` : `${m}분 ${s}초`
}
