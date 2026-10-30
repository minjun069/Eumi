import { Link, useLocation, useParams } from "react-router"
import type { PlaceholderSpec } from "@/screens/placeholder/placeholders"
import { PATHS } from "@/routes/paths"

/**
 * 아직 만들지 않은 화면의 자리 표시.
 * fullFrame: 메뉴바 없이 1440×1024 전체를 쓰는 화면(회원가입, 비밀번호 찾기)
 */
export function PlaceholderScreen({
  spec,
  fullFrame = false,
}: {
  spec: PlaceholderSpec
  fullFrame?: boolean
}) {
  const location = useLocation()
  const params = useParams()
  // "*"는 최상위 연결(main.tsx의 path "*")이 붙이는 값이라 빼고 보여 준다
  const paramEntries = Object.entries(params).filter(([key]) => key !== "*")

  return (
    <section className={fullFrame ? "placeholder-full" : "screen"}>
      <h1 className="page-title">{spec.title}</h1>
      <div className="placeholder-card">
        <p className="placeholder-stage">{spec.stage}에서 만들 화면입니다.</p>
        {spec.note && <p className="placeholder-note">{spec.note}</p>}
        <dl className="placeholder-meta">
          <dt>기능</dt>
          <dd>
            <ul>
              {spec.features.map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
          </dd>
          <dt>주소</dt>
          <dd>
            <code>{location.pathname}</code>
            {paramEntries.length > 0 && (
              <span className="placeholder-params">
                {paramEntries
                  .map(([key, value]) => `${key} = ${value}`)
                  .join(", ")}
              </span>
            )}
          </dd>
        </dl>
        {spec.links && spec.links.length > 0 && (
          <div className="placeholder-links">
            {spec.links.map((link) => (
              <Link key={link.to} to={link.to}>
                {link.label} →
              </Link>
            ))}
          </div>
        )}
        {fullFrame && (
          <div className="placeholder-links">
            <Link to={PATHS.login}>← 로그인 화면으로</Link>
          </div>
        )}
      </div>
    </section>
  )
}
