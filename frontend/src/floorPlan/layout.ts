// Mirrors backend/app/floor_plans/models.py. Geometry is in pixels of the
// backend-prepared image: top-left origin, x rightward, y downward.

export interface PixelPoint {
  x: number
  y: number
}

/** Zero-thickness segment, split at every crossing and T-junction. */
export interface Wall {
  id: string
  start: PixelPoint
  end: PixelPoint
}

/** Opening along one wall; the wall itself still spans it. */
export interface Opening {
  id: string
  wall_id: string
  start: PixelPoint
  end: PixelPoint
}

export interface RoomLabel {
  id: string
  name: string
  position: PixelPoint
}

export interface ScaleCalibration {
  start: PixelPoint
  end: PixelPoint
  distance_m: number
}

/** Recognition's estimate of the indoor footprint; closing edges are implicit. */
export interface IndoorDomain {
  boundary: PixelPoint[]
  holes: PixelPoint[][]
}

export interface Layout {
  id: string
  revision: number
  width_px: number
  height_px: number
  walls: Wall[]
  doors: Opening[]
  windows: Opening[]
  room_labels: RoomLabel[]
  calibration: ScaleCalibration | null
  /** Null when recognition could not close the outer walls; absent in projects saved before it existed. */
  indoor_domain?: IndoorDomain | null
}

export interface RecognitionDraft {
  floor_plan: { layout: Layout; reference_image: null }
  warnings: string[]
}
