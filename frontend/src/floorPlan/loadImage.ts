// Same media types as backend ReferenceImage, so the file can be sent as-is.
export const ACCEPTED_PLAN_TYPES = ['image/png', 'image/jpeg', 'image/webp']

export interface PlanImage {
  /** Original upload, kept for sending to the backend. */
  file: File
  /** Object URL backing `image`; kept for the whole session since the plan is never replaced. */
  url: string
  image: HTMLImageElement
  width: number
  height: number
}

export async function loadPlanImage(file: File): Promise<PlanImage> {
  if (!ACCEPTED_PLAN_TYPES.includes(file.type)) {
    throw new Error('PNG, JPG, WebP 이미지만 올릴 수 있어요.')
  }
  const url = URL.createObjectURL(file)
  const image = new Image()
  image.src = url
  try {
    await image.decode()
  } catch {
    URL.revokeObjectURL(url)
    throw new Error('이미지를 읽을 수 없어요.')
  }
  return { file, url, image, width: image.naturalWidth, height: image.naturalHeight }
}
