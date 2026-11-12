import { useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { TableauSheetFrame } from "@/tableau/TableauSheetFrame"
import type { TableauParameterInput } from "@/tableau/tableauTypes"

/** 창 안쪽 좌우 여백 (창 폭 = 시트 폭 + 양쪽 여백) */
const SIDE_PADDING = 24

/**
 * 인사이트 보고서 그래프 크게 보기.
 * - 보고서 칸에서는 시트가 패널 폭에 맞춰 줄어 보이므로(1440 틀에서 약 0.4~0.5배), 같은 시트를 설계 크기(1배)로 창에 띄운다.
 *   틀이 더 좁으면 TableauSheetFrame이 틀 폭에 맞춰 줄인다
 * - 창을 열 때 Tableau를 새로 띄운다 (보고서 칸의 Tableau는 옮길 수 없다). 매개변수(시군구 · 기간 · 행정동)는 보고서 칸과 같다
 * - 상담 창처럼 서비스 화면(.app-frame) 안을 덮는다. 닫기 버튼 · Esc · 바깥 누르기로 닫는다.
 *   그래프 안을 누른 뒤에는 키 입력이 Tableau(iframe)로 가서 Esc가 오지 않는다 (닫기 버튼 · 바깥 누르기는 된다)
 */
export function ReportGraphDialog({
  title,
  src,
  width,
  height,
  parameters,
  description,
  onClose,
}: {
  title: string
  src: string
  /** 시트 설계 크기 (도구 모음 제외) */
  width: number
  height: number
  parameters: TableauParameterInput[]
  /** 그래프 설명. 없으면 '설명 준비 중' */
  description: string | undefined
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  const frame = document.querySelector(".app-frame") ?? document.body
  return createPortal(
    <div className="dialog-backdrop report-zoom-backdrop" onClick={onClose}>
      <div
        className="dialog report-zoom-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-zoom-title"
        style={{ width: width + SIDE_PADDING * 2, paddingRight: SIDE_PADDING, paddingLeft: SIDE_PADDING }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="report-zoom-head">
          <h2 id="report-zoom-title">{title}</h2>
          <button ref={closeRef} type="button" className="report-zoom-close" aria-label="닫기" onClick={onClose}>
            ×
          </button>
        </div>
        <TableauSheetFrame
          src={src}
          label={title}
          parameters={parameters}
          openWidth={width}
          initialSize={{ width, height }}
          hideToolbar
          desktopLayout
        />
        {description ? (
          <p className="report-zoom-description">{description}</p>
        ) : (
          <p className="report-zoom-description risk-empty-text">설명을 준비 중입니다.</p>
        )}
      </div>
    </div>,
    frame,
  )
}
