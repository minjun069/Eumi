import type { WithdrawalInfo } from "@/api/myApi"

// 회원 탈퇴의 인계 선택 (5.1.4 · FR-064). 사례자·진행 중 자원마다 넘겨받을 회원을 고른다.

/** 대상 ID(사례자 caseId · 자원 resourceId) → 넘겨받을 회원 memberId */
export type Picks = Record<number, number>

/** 다시 불러온 뒤 눈에 띄게 표시할 행: 새로 생긴 행 / 고른 사람이 무효가 되어 비운 행 */
export type RowMark = "new" | "cleared"
export type Marks = Record<number, RowMark>

type Rows = {
  picks: Picks
  marks: Marks
  /** 넘길 대상에서 빠져 목록에서 사라진 행 수 */
  removed: number
}

/** 다시 불러온 안내(409 등)에 지금 고른 값을 맞춘 결과 */
export type Reconciled = {
  cases: Rows
  resources: Rows
}

/** 넘겨받을 사람 표시: "이름 직함" (직함이 없으면 이름만) */
export function successorLabel(member: { name: string; title: string | null }): string {
  return [member.name, member.title].filter(Boolean).join(" ")
}

/** 고른 값 중 지금 넘겨받을 수 있는 회원인 것만 (선택 안 함 = undefined) */
export function validPick(picks: Picks, id: number, successorIds: ReadonlySet<number>): number | undefined {
  const picked = picks[id]
  return picked !== undefined && successorIds.has(picked) ? picked : undefined
}

function reconcileRows(
  previousIds: readonly number[],
  nextIds: readonly number[],
  picks: Picks,
  successorIds: ReadonlySet<number>,
): Rows {
  const before = new Set(previousIds)
  const after = new Set(nextIds)
  const kept: Picks = {}
  const marks: Marks = {}
  for (const id of nextIds) {
    if (!before.has(id)) {
      marks[id] = "new"
      continue
    }
    const picked = picks[id]
    if (picked === undefined) continue
    if (successorIds.has(picked)) kept[id] = picked
    else marks[id] = "cleared"
  }
  return { picks: kept, marks, removed: previousIds.filter((id) => !after.has(id)).length }
}

/**
 * 409 등으로 안내를 다시 받았을 때 유효한 선택만 남긴다.
 * - 아직 넘길 대상이고 고른 사람이 아직 넘겨받을 수 있는 회원이면 그대로 둔다
 * - 고른 사람이 탈퇴했거나 다른 기관으로 빠졌으면 비우고 'cleared'로 표시한다
 * - 새로 생긴 행은 비어 있고 'new'로 표시한다. 대상에서 빠진 행은 버리고 개수만 센다
 */
export function reconcilePicks(
  previous: WithdrawalInfo,
  next: WithdrawalInfo,
  casePicks: Picks,
  resourcePicks: Picks,
): Reconciled {
  const successorIds = new Set(next.successors.map((member) => member.memberId))
  return {
    cases: reconcileRows(
      previous.soleCases.map((item) => item.caseId),
      next.soleCases.map((item) => item.caseId),
      casePicks,
      successorIds,
    ),
    resources: reconcileRows(
      previous.ongoingResources.map((item) => item.resourceId),
      next.ongoingResources.map((item) => item.resourceId),
      resourcePicks,
      successorIds,
    ),
  }
}

/** 다시 불러온 결과를 사람이 읽는 안내 줄로 (바뀐 것이 없으면 빈 배열) */
export function describeReconciled({ cases, resources }: Reconciled): string[] {
  const count = (marks: Marks, mark: RowMark) => Object.values(marks).filter((value) => value === mark).length
  const lines: string[] = []
  const join = (caseCount: number, resourceCount: number) =>
    [caseCount > 0 ? `사례자 ${caseCount}명` : null, resourceCount > 0 ? `복지자원 ${resourceCount}개` : null]
      .filter(Boolean)
      .join(" · ")

  const added = join(count(cases.marks, "new"), count(resources.marks, "new"))
  if (added) lines.push(`새로 넘겨야 할 대상이 생겼습니다 (${added}). 넘겨받을 사람을 골라 주세요.`)
  const cleared = join(count(cases.marks, "cleared"), count(resources.marks, "cleared"))
  if (cleared) lines.push(`고른 사람이 더 이상 넘겨받을 수 없어 선택을 비웠습니다 (${cleared}). 다시 골라 주세요.`)
  const removed = join(cases.removed, resources.removed)
  if (removed) lines.push(`넘길 대상에서 빠진 항목은 목록에서 뺐습니다 (${removed}).`)
  return lines
}
