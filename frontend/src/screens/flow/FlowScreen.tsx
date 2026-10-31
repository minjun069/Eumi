import { useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { addLogNote } from "@/devtools/apiLogStore"
import { devAuth } from "@/devtools/devAuth"
import { HOME_PATH } from "@/routes/paths"
import {
  AREA_COLORS,
  AREA_LABELS,
  FEATURE_NAMES,
  FLOW_EDGES,
  FLOW_FOOTNOTE,
  FLOW_NODES,
  FLOW_SVG_STYLE,
  OVERLAY_PARENTS,
  type FlowArea,
  type FlowEdge,
  type FlowNode,
  type FlowOpen,
} from "@/screens/flow/flowData"
import { sessionStore, useSession } from "@/session/sessionStore"
import { agentStore } from "@/stores/agentStore"
import { showToast } from "@/stores/toastStore"

const SVG_WIDTH = 1090
const SVG_HEIGHT = 950
const LEGEND_AREAS: FlowArea[] = ["auth", "risk", "case", "resource", "my", "common"]

/**
 * 화면 흐름도 (14단계, 개발용): 화면을 상자로, 화면 사이 이동을 기능 ID가 붙은 화살표로 그린다 (H1-A).
 * 상자를 누르면 오른쪽에 주소·기능 ID·그 화면이 부르는 API·이동을 보여 주고 '열기'로 그 화면으로 간다 (H2-A).
 * 'SVG로 저장'으로 흐름도만 파일로 받는다 (H8-B).
 */
export function FlowScreen() {
  const navigate = useNavigate()
  const session = useSession()
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const selected = FLOW_NODES.find((node) => node.id === selectedId) ?? null
  const related = useMemo(() => relatedIds(selectedId), [selectedId])

  const goBack = () => {
    if (window.history.length > 1) navigate(-1)
    else navigate(HOME_PATH)
  }

  const openScreen = (target: FlowOpen) => {
    const to = target.to()
    if (!to) {
      showToast("예시 대상을 찾지 못했습니다. 새로고침한 뒤 다시 열어 보세요.", "error")
      return
    }
    const loggedIn = sessionStore.getState().status !== "anonymous"
    if (target.member && !loggedIn) devAuth.switchMember(1)
    if (!target.member && loggedIn) {
      sessionStore.signOut()
      addLogNote("화면 흐름도: 계정 화면을 열려고 로그아웃 상태로 바꿈 (API 호출 아님)")
    }
    navigate(to)
    if (target.after === "openAgent") agentStore.open()
  }

  const saveSvg = () => {
    const svg = svgRef.current
    if (!svg) return
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.querySelectorAll(".is-selected, .is-active, .flow-dim").forEach((element) => {
      element.classList.remove("is-selected", "is-active", "flow-dim")
    })
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
    const background = document.createElementNS("http://www.w3.org/2000/svg", "rect")
    background.setAttribute("width", String(SVG_WIDTH))
    background.setAttribute("height", String(SVG_HEIGHT))
    background.setAttribute("fill", "#ffffff")
    clone.insertBefore(background, clone.firstChild?.nextSibling ?? null)
    const text = `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(clone)}`
    const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }))
    const link = document.createElement("a")
    link.href = url
    link.download = "이음이_화면흐름도.svg"
    document.body.append(link)
    link.click()
    link.remove()
    // 바로 지우면 브라우저가 파일 이름을 잃을 수 있어 조금 뒤에 지운다
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    addLogNote("화면 흐름도를 SVG 파일로 저장함")
  }

  return (
    <section className="flow-screen">
      <header className="flow-head">
        <button type="button" className="back-link" onClick={goBack}>
          &lt; 이전 화면으로
        </button>
        <h1 className="page-title">화면 흐름도</h1>
        <p className="page-desc">상자를 누르면 오른쪽에 그 화면의 기능 ID·API·이동이 나옵니다.</p>
        <button type="button" className="btn btn-outline btn-small flow-save" onClick={saveSvg}>
          SVG로 저장
        </button>
      </header>

      <svg
        ref={svgRef}
        className="flow-svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        width={SVG_WIDTH}
        height={SVG_HEIGHT}
        role="img"
        aria-label="이음이 화면 흐름도"
        onClick={() => setSelectedId(null)}
      >
        <style>{FLOW_SVG_STYLE}</style>
        <defs>
          <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="#6b7686" />
          </marker>
          <marker id="flow-arrow-thin" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="#b7bfcc" />
          </marker>
          <marker id="flow-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="#324085" />
          </marker>
        </defs>

        {Object.entries(OVERLAY_PARENTS).map(([childId, parentId]) => {
          const child = FLOW_NODES.find((node) => node.id === childId)
          const parent = FLOW_NODES.find((node) => node.id === parentId)
          if (!child || !parent) return null
          const x = child.x + child.w / 2
          return (
            <line
              key={childId}
              className={`flow-attach ${selectedId && !related.has(childId) ? "flow-dim" : ""}`}
              x1={x}
              y1={parent.y + parent.h}
              x2={x}
              y2={child.y}
            />
          )
        })}

        {FLOW_EDGES.map((edge) => (
          <EdgeView
            key={edge.id}
            edge={edge}
            active={selectedId !== null && (edge.from === selectedId || edge.to === selectedId)}
            dim={selectedId !== null && edge.from !== selectedId && edge.to !== selectedId}
          />
        ))}

        {FLOW_NODES.map((node) => (
          <NodeView
            key={node.id}
            node={node}
            selected={node.id === selectedId}
            dim={selectedId !== null && !related.has(node.id)}
            onSelect={() => setSelectedId(node.id === selectedId ? null : node.id)}
          />
        ))}

        <g transform="translate(20 924)">
          {LEGEND_AREAS.map((area, index) => (
            <g key={area} transform={`translate(${index * 112} 0)`}>
              <rect width="16" height="12" y="-6" rx="3" fill={AREA_COLORS[area].fill} stroke={AREA_COLORS[area].stroke} />
              <text className="flow-footnote" x="22" dominantBaseline="middle">
                {AREA_LABELS[area]}
              </text>
            </g>
          ))}
          <text className="flow-footnote" x="690" y="0" dominantBaseline="middle">
            점선 상자 = 화면 위에 뜨는 창 · 회색 화살표 = 메뉴바
          </text>
        </g>
        <text className="flow-footnote" x="20" y="944" dominantBaseline="middle">
          {FLOW_FOOTNOTE}
        </text>
      </svg>

      <aside className="flow-panel" aria-label="고른 화면 설명">
        {selected ? (
          <NodeDetail
            node={selected}
            loggedIn={session.status !== "anonymous"}
            onOpen={openScreen}
            onSelect={setSelectedId}
          />
        ) : (
          <FlowGuide />
        )}
      </aside>
    </section>
  )
}

/** 고른 상자와 화살표·창으로 이어진 상자 */
function relatedIds(selectedId: string | null): Set<string> {
  const ids = new Set<string>()
  if (!selectedId) return ids
  ids.add(selectedId)
  FLOW_EDGES.forEach((edge) => {
    if (edge.from === selectedId) ids.add(edge.to)
    if (edge.to === selectedId) ids.add(edge.from)
  })
  Object.entries(OVERLAY_PARENTS).forEach(([childId, parentId]) => {
    if (childId === selectedId) ids.add(parentId)
    if (parentId === selectedId) ids.add(childId)
  })
  return ids
}

function NodeView({
  node,
  selected,
  dim,
  onSelect,
}: {
  node: FlowNode
  selected: boolean
  dim: boolean
  onSelect: () => void
}) {
  const cx = node.x + node.w / 2
  const sub =
    node.kind === "common"
      ? node.id === "menu"
        ? "0.1.1 메뉴 이동 · 0.1.2 로그아웃 (로그인한 모든 화면)"
        : "헤더 AI 아이콘으로 어느 화면에서나 (0.2)"
      : node.kind === "screen"
        ? (node.boxPath ?? node.path)
        : undefined
  return (
    <g
      className={`flow-node area-${node.area} ${node.kind === "overlay" ? "is-overlay" : ""} ${selected ? "is-selected" : ""} ${dim ? "flow-dim" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${node.title} 상자`}
      aria-pressed={selected}
      onClick={(event) => {
        event.stopPropagation()
        onSelect()
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onSelect()
        }
      }}
      style={{ cursor: "pointer" }}
    >
      <rect x={node.x} y={node.y} width={node.w} height={node.h} />
      <text x={cx} y={sub && node.kind !== "overlay" ? node.y + node.h / 2 - 8 : node.y + node.h / 2}>
        {node.title}
      </text>
      {sub && node.kind !== "overlay" && (
        <text className="flow-path" x={cx} y={node.y + node.h / 2 + 11}>
          {sub}
        </text>
      )}
    </g>
  )
}

function EdgeView({ edge, active, dim }: { edge: FlowEdge; active: boolean; dim: boolean }) {
  const d = edge.points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`).join(" ")
  const marker = active ? "flow-arrow-active" : edge.thin ? "flow-arrow-thin" : "flow-arrow"
  return (
    <g className={`flow-edge ${edge.thin ? "is-thin" : ""} ${active ? "is-active" : ""} ${dim ? "flow-dim" : ""}`}>
      <path d={d} markerEnd={`url(#${marker})`} markerStart={edge.both ? `url(#${marker})` : undefined} />
      {edge.jump && (
        <rect
          className="flow-jump"
          x={edge.at[0] - edge.label.length * 5.4}
          y={edge.at[1] - 11}
          width={edge.label.length * 10.8}
          height={22}
          rx={11}
        />
      )}
      <text
        x={edge.at[0]}
        y={edge.at[1]}
        transform={edge.vertical ? `rotate(-90 ${edge.at[0]} ${edge.at[1]})` : undefined}
      >
        {edge.label}
      </text>
    </g>
  )
}

function NodeDetail({
  node,
  loggedIn,
  onOpen,
  onSelect,
}: {
  node: FlowNode
  loggedIn: boolean
  onOpen: (target: FlowOpen) => void
  onSelect: (id: string) => void
}) {
  const titleOf = (id: string) => FLOW_NODES.find((item) => item.id === id)?.title ?? id
  const incoming = FLOW_EDGES.filter((edge) => edge.to === node.id || (edge.both && edge.from === node.id))
  const outgoing = FLOW_EDGES.filter((edge) => edge.from === node.id || (edge.both && edge.to === node.id))
  const other = (edge: FlowEdge, side: "in" | "out") =>
    side === "in" ? (edge.to === node.id ? edge.from : edge.to) : edge.from === node.id ? edge.to : edge.from
  const parent = OVERLAY_PARENTS[node.id]
  const children = Object.entries(OVERLAY_PARENTS)
    .filter(([, parentId]) => parentId === node.id)
    .map(([childId]) => childId)

  return (
    <div className="flow-detail">
      <span className={`flow-area-chip area-${node.area}`}>
        {AREA_LABELS[node.area]}
        {node.kind === "overlay" ? " · 화면 위 창" : node.kind === "common" ? " · 공통" : ""}
      </span>
      <h2>{node.title}</h2>
      {node.path && <p className="flow-detail-path">{node.path}</p>}
      {node.note && <p className="flow-detail-note">{node.note}</p>}

      {node.opens && (
        <div className="flow-open">
          {node.opens.map((target) => (
            <button key={target.label} type="button" className="btn btn-primary btn-small" onClick={() => onOpen(target)}>
              {target.label}
              {target.member && !loggedIn ? " (김지원으로 로그인)" : ""}
              {!target.member && loggedIn ? " (로그아웃하고 열기)" : ""}
            </button>
          ))}
        </div>
      )}

      <h3>기능 ID</h3>
      <ul className="flow-list">
        {node.features.map((id) => (
          <li key={id}>
            <b>{id}</b> {FEATURE_NAMES[id] ?? ""}
          </li>
        ))}
      </ul>

      <h3>
        부르는 API <span>{node.apis.length}개</span>
      </h3>
      <ul className="flow-list flow-api-list">
        {node.apis.map((api) => {
          const [id, ...name] = api.split(" ")
          return (
            <li key={api}>
              <b>{id}</b> {name.join(" ")}
            </li>
          )
        })}
      </ul>

      {(parent || children.length > 0) && (
        <>
          <h3>화면 위 창</h3>
          <ul className="flow-list flow-links">
            {parent && (
              <li>
                <button type="button" className="link-button" onClick={() => onSelect(parent)}>
                  {titleOf(parent)}
                </button>{" "}
                위에 뜸
              </li>
            )}
            {children.map((childId) => (
              <li key={childId}>
                <button type="button" className="link-button" onClick={() => onSelect(childId)}>
                  {titleOf(childId)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>들어오는 이동</h3>
      <EdgeList edges={incoming} side="in" other={other} titleOf={titleOf} onSelect={onSelect} />
      <h3>나가는 이동</h3>
      <EdgeList edges={outgoing} side="out" other={other} titleOf={titleOf} onSelect={onSelect} />
    </div>
  )
}

function EdgeList({
  edges,
  side,
  other,
  titleOf,
  onSelect,
}: {
  edges: FlowEdge[]
  side: "in" | "out"
  other: (edge: FlowEdge, side: "in" | "out") => string
  titleOf: (id: string) => string
  onSelect: (id: string) => void
}) {
  if (edges.length === 0) return <p className="flow-none">없음</p>
  return (
    <ul className="flow-list flow-links">
      {edges.map((edge) => {
        const target = other(edge, side)
        return (
          <li key={`${edge.id}-${side}`}>
            {side === "in" ? "← " : "→ "}
            <button type="button" className="link-button" onClick={() => onSelect(target)}>
              {titleOf(target)}
            </button>
            <span className="flow-edge-label">{edge.label}</span>
          </li>
        )
      })}
    </ul>
  )
}

function FlowGuide() {
  const screens = FLOW_NODES.filter((node) => node.kind === "screen").length
  const apis = new Set(FLOW_NODES.flatMap((node) => node.apis.map((api) => api.replace(/^[\d.]+ /, "")))).size
  return (
    <div className="flow-detail">
      <h2>보는 방법</h2>
      <ul className="flow-list">
        <li>상자 = 화면 {screens}개 (등록·수정은 한 상자로 묶음), 점선 상자 = 화면 위에 뜨는 창, 노란 상자 = 모든 화면에 붙는 메뉴바·AI 패널</li>
        <li>화살표 = 화면 사이 이동. 글자는 기능 ID와 동작 (양쪽 화살표는 오가는 이동)</li>
        <li>상자를 누르면 이어진 상자·화살표만 진하게 보이고, 여기에 기능 ID·부르는 API·이동이 나옵니다.</li>
        <li>'열기'는 예시 대상으로 그 화면을 엽니다. 로그인하지 않았으면 김지원으로 로그인하고, 계정 화면은 로그아웃하고 엽니다.</li>
        <li>부르는 API는 서로 다른 이름 기준 {apis}개입니다. 지역·담당자 목록은 여러 화면이 함께 쓰고, 기능 ID는 부르는 화면의 것입니다.</li>
      </ul>
      <h3>함께 볼 문서</h3>
      <ul className="flow-list">
        <li>API 초안.md — 전체 API의 요청·응답·실패 사유·서버 처리</li>
        <li>프로토타입_제작.md — 단계별로 정한 것과 기능명세서 반영 항목</li>
      </ul>
    </div>
  )
}
