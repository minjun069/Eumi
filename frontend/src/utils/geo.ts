// 지도 그리기용 간단한 좌표 계산 (경위도 → 미터, 점이 다각형 안에 있는지, 이름 놓을 자리)
// 강남구처럼 좁은 지역에서만 쓰므로, 기준 위도에서 위경도 1도의 길이로 단순 환산한다.

export type LonLat = [number, number]
/** 다각형 = 바깥 고리 + 구멍 고리들 */
export type Polygon = LonLat[][]

const REFERENCE_LATITUDE = 37.5
const METERS_PER_LON = 111320 * Math.cos((REFERENCE_LATITUDE * Math.PI) / 180)
const METERS_PER_LAT = 110540

/** 경위도 → 동쪽·북쪽 방향 미터 */
export function toMeters([lon, lat]: LonLat): [number, number] {
  return [lon * METERS_PER_LON, lat * METERS_PER_LAT]
}

/** 미터 → 경위도 */
export function toLonLat([x, y]: [number, number]): LonLat {
  return [x / METERS_PER_LON, y / METERS_PER_LAT]
}

/** 점이 다각형(구멍 포함) 안에 있는지 */
export function insidePolygon(point: LonLat, polygon: Polygon): boolean {
  const [x, y] = point
  let inside = false
  for (const ring of polygon) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [xi, yi] = ring[i]
      const [xj, yj] = ring[j]
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
    }
  }
  return inside
}

/** 여러 다각형의 미터 좌표 범위 */
export function boundsOf(polygons: Polygon[]) {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const polygon of polygons) {
    for (const point of polygon[0]) {
      const [x, y] = toMeters(point)
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  return { minX, minY, maxX, maxY }
}

function ringArea(ring: [number, number][]): number {
  let area = 0
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    area += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1]
  }
  return Math.abs(area) / 2
}

function segmentDistance(px: number, py: number, [ax, ay]: [number, number], [bx, by]: [number, number]): number {
  const dx = bx - ax
  const dy = by - ay
  const lengthSquared = dx * dx + dy * dy
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

/** 글자는 옆으로 길어서, 가로 여유를 세로보다 2.5배 중요하게 본다 */
const LABEL_ASPECT = 2.5

/**
 * 동 이름을 놓을 자리(미터 좌표): 가장 큰 다각형 안에서 경계와 가장 먼 점.
 * 가로 길이를 줄여서 거리를 재므로, 가로로 넓은 곳이 뽑힌다. 넓은 격자에서 찾고 주변을 두 번 더 좁혀 찾는다.
 */
export function labelPoint(polygons: Polygon[]): [number, number] {
  const largest = polygons
    .map((polygon) => polygon.map((ring) => ring.map(toMeters)))
    .reduce((best, rings) => (ringArea(rings[0]) > ringArea(best[0]) ? rings : best))
  const squeezed = largest.map((ring) => ring.map(([x, y]): [number, number] => [x / LABEL_ASPECT, y]))
  const lonLatRings = largest.map((ring) => ring.map(toLonLat))
  const score = (x: number, y: number) => {
    if (!insidePolygon(toLonLat([x, y]), lonLatRings)) return -Infinity
    let nearest = Infinity
    for (const ring of squeezed) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
        nearest = Math.min(nearest, segmentDistance(x / LABEL_ASPECT, y, ring[j], ring[i]))
      }
    }
    return nearest
  }
  const xs = largest[0].map((point) => point[0])
  const ys = largest[0].map((point) => point[1])
  let best = { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2, score: -Infinity }
  let stepX = (Math.max(...xs) - Math.min(...xs)) / 24
  let stepY = (Math.max(...ys) - Math.min(...ys)) / 24
  let centerX = best.x
  let centerY = best.y
  for (let round = 0; round < 3; round += 1) {
    for (let ix = -12; ix <= 12; ix += 1) {
      for (let iy = -12; iy <= 12; iy += 1) {
        const x = centerX + ix * stepX
        const y = centerY + iy * stepY
        const value = score(x, y)
        if (value > best.score) best = { x, y, score: value }
      }
    }
    centerX = best.x
    centerY = best.y
    stepX /= 6
    stepY /= 6
  }
  return [best.x, best.y]
}

/** 미터 좌표 → SVG 좌표 변환기 (북쪽이 위, 폭에 맞춰 줄임) */
export function makeProjector(bounds: ReturnType<typeof boundsOf>, width: number, maxHeight: number, padding = 6) {
  const spanX = bounds.maxX - bounds.minX
  const spanY = bounds.maxY - bounds.minY
  const scale = Math.min((width - padding * 2) / spanX, (maxHeight - padding * 2) / spanY)
  const height = spanY * scale + padding * 2
  const offsetX = (width - spanX * scale) / 2
  return {
    scale,
    width,
    height,
    point: ([x, y]: [number, number]): [number, number] => [
      offsetX + (x - bounds.minX) * scale,
      padding + (bounds.maxY - y) * scale,
    ],
  }
}

/** 다각형들 → SVG path 문자열 */
export function polygonsToPath(polygons: Polygon[], project: (point: [number, number]) => [number, number]): string {
  return polygons
    .flatMap((polygon) =>
      polygon.map(
        (ring) =>
          ring
            .map((point, index) => {
              const [x, y] = project(toMeters(point))
              return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
            })
            .join("") + "Z",
      ),
    )
    .join("")
}
