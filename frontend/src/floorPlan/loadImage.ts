// Same media types as backend ReferenceImage; the backend re-checks the actual format.
export const ACCEPTED_PLAN_TYPES = ['image/png', 'image/jpeg', 'image/webp']

export interface PlanImage {
  /** Original file name, for display. */
  name: string
  /**
   * The backend-prepared PNG (EXIF orientation applied). Recognized geometry
   * uses its pixel coordinates, so this, not the original upload, is shown.
   */
  blob: Blob
  /** Object URL backing `image`; kept for the whole session since the plan is never replaced. */
  url: string
  image: HTMLImageElement
  width: number
  height: number
}

export function isAcceptedPlanFile(file: File): boolean {
  return ACCEPTED_PLAN_TYPES.includes(file.type)
}

export async function loadPlanImage(blob: Blob, name: string): Promise<PlanImage> {
  const url = URL.createObjectURL(blob)
  const image = new Image()
  image.src = url
  try {
    await image.decode()
  } catch {
    URL.revokeObjectURL(url)
    throw new Error('이미지를 읽을 수 없어요.')
  }
  return { name, blob, url, image, width: image.naturalWidth, height: image.naturalHeight }
}
