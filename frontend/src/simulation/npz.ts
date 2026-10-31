// Reader for the simulation field bundle: a NumPy NPZ archive (a ZIP of .npy
// files, written by np.savez_compressed). Only what that writer produces is
// supported: stored or deflated entries, optional ZIP64 sizes, little-endian
// float32/float64/bool arrays in C order.

export interface NpyArray {
  shape: number[]
  data: Float32Array | Float64Array | Uint8Array
}

const EOCD_SIGNATURE = 0x06054b50
const CENTRAL_SIGNATURE = 0x02014b50
const LOCAL_SIGNATURE = 0x04034b50
const ZIP64_EXTRA = 0x0001
const U32_MAX = 0xffffffff

export async function parseNpz(buffer: ArrayBuffer): Promise<Map<string, NpyArray>> {
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)

  // End of central directory: the last 22+ bytes, before an optional comment.
  let eocd = -1
  for (let i = buffer.byteLength - 22; i >= Math.max(0, buffer.byteLength - 22 - 0xffff); i--) {
    if (view.getUint32(i, true) === EOCD_SIGNATURE) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('Not a ZIP archive')
  const entries = view.getUint16(eocd + 10, true)
  let offset = view.getUint32(eocd + 16, true)

  const arrays = new Map<string, NpyArray>()
  for (let n = 0; n < entries; n++) {
    if (view.getUint32(offset, true) !== CENTRAL_SIGNATURE) throw new Error('Corrupt ZIP directory')
    const method = view.getUint16(offset + 10, true)
    let compressedSize = view.getUint32(offset + 20, true)
    let size = view.getUint32(offset + 24, true)
    const nameLength = view.getUint16(offset + 28, true)
    const extraLength = view.getUint16(offset + 30, true)
    const commentLength = view.getUint16(offset + 32, true)
    let localOffset = view.getUint32(offset + 42, true)
    const name = new TextDecoder().decode(bytes.subarray(offset + 46, offset + 46 + nameLength))

    // ZIP64 extra field: 64-bit values, present only for fields set to 0xFFFFFFFF.
    let extra = offset + 46 + nameLength
    const extraEnd = extra + extraLength
    while (extra + 4 <= extraEnd) {
      const id = view.getUint16(extra, true)
      const length = view.getUint16(extra + 2, true)
      if (id === ZIP64_EXTRA) {
        let p = extra + 4
        const next = () => {
          const value = Number(view.getBigUint64(p, true))
          p += 8
          return value
        }
        if (size === U32_MAX) size = next()
        if (compressedSize === U32_MAX) compressedSize = next()
        if (localOffset === U32_MAX) localOffset = next()
      }
      extra += 4 + length
    }
    offset = extraEnd + commentLength

    if (view.getUint32(localOffset, true) !== LOCAL_SIGNATURE) throw new Error('Corrupt ZIP entry')
    const dataStart = localOffset + 30 + view.getUint16(localOffset + 26, true) + view.getUint16(localOffset + 28, true)
    const raw = bytes.subarray(dataStart, dataStart + compressedSize)
    let content: Uint8Array
    if (method === 0) content = raw
    else if (method === 8) content = await inflate(raw)
    else throw new Error(`Unsupported ZIP compression ${method}`)
    if (content.byteLength !== size) throw new Error(`Size mismatch in ${name}`)

    arrays.set(name.replace(/\.npy$/, ''), parseNpy(content))
  }
  return arrays
}

async function inflate(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as Uint8Array<ArrayBuffer>]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

function parseNpy(content: Uint8Array): NpyArray {
  if (content[0] !== 0x93 || new TextDecoder().decode(content.subarray(1, 6)) !== 'NUMPY') {
    throw new Error('Not an NPY array')
  }
  const view = new DataView(content.buffer, content.byteOffset, content.byteLength)
  const major = content[6]
  const headerLength = major === 1 ? view.getUint16(8, true) : view.getUint32(8, true)
  const headerStart = major === 1 ? 10 : 12
  const header = new TextDecoder().decode(content.subarray(headerStart, headerStart + headerLength))

  const descr = /'descr':\s*'([^']+)'/.exec(header)?.[1]
  const fortran = /'fortran_order':\s*True/.test(header)
  const shapeText = /'shape':\s*\(([^)]*)\)/.exec(header)?.[1]
  if (!descr || shapeText === undefined) throw new Error('Unreadable NPY header')
  if (fortran) throw new Error('Fortran-ordered arrays are not supported')
  const shape = shapeText
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)

  // Copy so typed arrays start on an aligned offset of their own buffer.
  const body = content.slice(headerStart + headerLength)
  switch (descr) {
    case '<f4':
      return { shape, data: new Float32Array(body.buffer) }
    case '<f8':
      return { shape, data: new Float64Array(body.buffer) }
    case '|b1':
    case '|u1':
      return { shape, data: body }
    default:
      throw new Error(`Unsupported NPY dtype ${descr}`)
  }
}
