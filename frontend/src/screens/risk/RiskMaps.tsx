import { BOUNDARY_ATTRIBUTION } from "@/mock/tableau/gangnamBoundaries"
import { GRID_SIZE_METERS, type GridCell, type GridLevel, type MapTile, type StageCounts } from "@/mock/tableau/tableauViews"
import { GRID_LEVELS, STAGE_COLORS, STAGE_LABELS, STAGE_TEXT, STAGES } from "@/screens/risk/riskStyle"
import { boundsOf, labelPoint, makeProjector, polygonsToPath, type Polygon } from "@/utils/geo"

// 고립 위험 탐색의 지도 2개 (Tableau ①·⑥을 흉내 낸 예시 그림). 행정동 경계는 실제 경계 데이터.

/** ① 시군구 위험도 지도: 실제 행정동 경계 + 단계 색 + 범례(단계별 행정동 수). 동을 누르면 선택 */
export function DistrictMap({
  tiles,
  counts,
  onSelect,
}: {
  tiles: MapTile[]
  counts: StageCounts
  onSelect: (tile: MapTile) => void
}) {
  const shapes = tiles.filter((tile) => tile.polygons.length > 0)
  const projector = makeProjector(boundsOf(shapes.flatMap((tile) => tile.polygons)), 440, 400)

  return (
    <div className="risk-map">
      <div>
        <svg
          className="district-map"
          viewBox={`0 0 ${projector.width} ${projector.height}`}
          width={projector.width}
          height={projector.height}
          role="group"
          aria-label="행정동별 고립 위험도 지도"
        >
          {shapes.map((tile) => (
            <path
              key={tile.dongCode}
              className="district-shape"
              d={polygonsToPath(tile.polygons, projector.point)}
              fill={STAGE_COLORS[tile.stage]}
              role="button"
              tabIndex={0}
              aria-label={`${tile.dongName} ${tile.stage}단계`}
              onClick={() => onSelect(tile)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSelect(tile)
              }}
            >
              <title>{`${tile.dongName} ${tile.stage}단계 (${tile.score.toFixed(1)}점)`}</title>
            </path>
          ))}
          {shapes.map((tile) => {
            const [x, y] = projector.point(labelPoint(tile.polygons))
            return (
              <text
                key={tile.dongCode}
                className="district-label"
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={STAGE_TEXT[tile.stage]}
              >
                {tile.dongName}
              </text>
            )
          })}
        </svg>
        <p className="map-attribution">{BOUNDARY_ATTRIBUTION}</p>
      </div>
      <div className="risk-legend" aria-label="위험도 단계">
        <strong>위험도 단계</strong>
        {STAGES.map((stage) => (
          <div key={stage} className="risk-legend-row">
            <i style={{ background: STAGE_COLORS[stage] }} />
            <span>
              {stage}단계 {STAGE_LABELS[stage]}
            </span>
            <em>{counts[stage]}개</em>
          </div>
        ))}
      </div>
    </div>
  )
}

const GRID_COLORS = Object.fromEntries(GRID_LEVELS.map((item) => [item.level, item.color])) as Record<GridLevel, string>

/** ⑥ 읍면동 격자 지도: 동 경계 안의 100m 격자별 행동 이상 3단계 */
export function DongGridMap({
  polygons,
  cells,
  counts,
}: {
  polygons: Polygon[]
  cells: GridCell[]
  counts: Record<GridLevel, number>
}) {
  const projector = makeProjector(boundsOf(polygons), 340, 340, 10)
  const size = GRID_SIZE_METERS * projector.scale

  return (
    <div className="risk-map">
      <div>
        <svg
          className="grid-map"
          viewBox={`0 0 ${projector.width} ${projector.height}`}
          width={projector.width}
          height={projector.height}
          role="img"
          aria-label={`격자 ${cells.length}칸의 행동 이상 위험도`}
        >
          {cells.map((cell) => {
            const [x, y] = projector.point([cell.x, cell.y + GRID_SIZE_METERS])
            return (
              <rect
                key={`${cell.x},${cell.y}`}
                className={`grid-cell grid-${cell.level}`}
                x={x}
                y={y}
                width={size}
                height={size}
                fill={GRID_COLORS[cell.level]}
              />
            )
          })}
          <path d={polygonsToPath(polygons, projector.point)} fill="none" stroke="#243247" strokeWidth={1.5} />
        </svg>
        <p className="map-attribution">{BOUNDARY_ATTRIBUTION}</p>
      </div>
      <div className="risk-legend" aria-label="행동 이상 위험도 수준">
        <strong>행동 이상 위험도</strong>
        {[...GRID_LEVELS].reverse().map((item) => (
          <div key={item.level} className="risk-legend-row">
            <i style={{ background: item.color }} />
            <span>{item.label}</span>
            <em>{counts[item.level]}칸</em>
          </div>
        ))}
        <p className="legend-note">한 칸 = {GRID_SIZE_METERS}m × {GRID_SIZE_METERS}m</p>
      </div>
    </div>
  )
}
