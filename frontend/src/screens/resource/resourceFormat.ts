// 복지자원 화면 표시 형식 (목록·상세 공통)

/** 2026-10-01, 2026-12-31 → 2026.10.01 ~ 2026.12.31 */
export function formatPeriod(start: string, end: string): string {
  return `${start.replace(/-/g, ".")} ~ ${end.replace(/-/g, ".")}`
}

/** 이용자 부담금: 0원이면 '무료', 그 밖에는 10,000원 */
export function formatFee(fee: number): string {
  return fee === 0 ? "무료" : `${fee.toLocaleString("ko-KR")}원`
}

/** 시군구 전체 자원(행정동 없음)은 '강남구 전체' */
export function formatRegion(sigunguName: string, dongName: string | null): string {
  return `${sigunguName} ${dongName ?? "전체"}`
}

/** 지원 연령: 청년, 중장년 / 무관 */
export function formatAgeGroups(groups: string[]): string {
  return groups.join(", ")
}

/** 담당자: 김지원 사회복지사 · 우리복지관 (V3-B), 탈퇴했으면 퇴사자 */
export function formatManager(manager: { name: string; title: string | null; orgName: string } | null): string {
  if (!manager) return "퇴사자"
  return `${[manager.name, manager.title].filter(Boolean).join(" ")} · ${manager.orgName}`
}
