import { devAgent } from "@/devtools/devAgent"
import { exampleQuestions } from "@/mock/agent/agentExamples"
import { maskIdentity, type MaskResult } from "@/mock/agent/identityMask"
import type { AgentAskRequest, AgentBlock, AgentEvent, AgentScreen, CheckState, RecommendationCard } from "@/mock/api/agentApi"
import { AGENT_FAILED_MESSAGE } from "@/mock/api/agentApi"
import { requireCaseAccess } from "@/mock/api/caseApi"
import { serverNote } from "@/mock/api/core"
import { effectiveStatus } from "@/mock/api/resourceApi"
import { db } from "@/mock/db"
import type { AgeGroup, Member, WelfareResource } from "@/types/domain"
import { ageGroupOf, ageOn } from "@/utils/age"

// AI Agent 흉내 (서버 + AI 서버 쪽). 실제 AI가 아니라, 질문의 낱말로 할 일을 고르고 예시 데이터로 답을 만든다.
// AI가 쓰는 기능(도구)마다 '단계' 이벤트를 낸다. 단계 이름은 아래 목록에서만 쓴다.

const STEP_NAMES = {
  screen: "화면 정보 확인",
  analysis: "고립 위험 분석 결과 조회",
  report: "인사이트 보고서 조회",
  myCases: "담당 사례자 현황 조회 (신원 정보 제외)",
  caseInfo: "사례자 정보 확인 (신원 정보 제외)",
  needs: "상담 기록에서 필요한 지원 찾기",
  searchActive: "진행 중인 복지자원 검색",
  searchEnded: "종료된 복지자원까지 넓혀 검색",
  resource: "복지자원 정보 조회",
  answer: "답변 작성",
} as const

type StepKey = keyof typeof STEP_NAMES

/** 단계 이벤트를 모으고, 개발용 실패·시간 초과를 끼워 넣는다 */
class EventBuilder {
  events: AgentEvent[] = []
  private count = 0
  constructor(private fault: "error" | "timeout" | null) {}

  /** 단계 하나 (진행 중 → 완료). 실패·시간 초과 재현이면 두 번째 단계에서 멈추고 false */
  step(key: StepKey, detail: string | null = null): boolean {
    this.count += 1
    this.events.push({ event: "step", stepId: key, stepName: STEP_NAMES[key], status: "진행 중", detail: null })
    if (this.fault && this.count === 2) {
      if (this.fault === "error") {
        serverNote("AI 서버가 처리 중 오류를 냄 (개발용 재현) → error 이벤트를 보내고 끝냄")
        this.events.push({ event: "error", errorMessage: AGENT_FAILED_MESSAGE })
      } else {
        serverNote("AI 서버가 제한 시간 안에 답하지 않음 (개발용 재현) → 화면이 시간 초과로 처리")
      }
      return false
    }
    this.events.push({ event: "step", stepId: key, stepName: STEP_NAMES[key], status: "완료", detail })
    return true
  }

  answer(blocks: AgentBlock[]): AgentEvent[] {
    if (!this.step("answer")) return this.events
    this.events.push({ event: "answer", blocks })
    return this.events
  }
}

type Intent =
  | "district-summary"
  | "district-top"
  | "dong-explain"
  | "dong-targets"
  | "recommend"
  | "resource-fit"
  | "help"
  | "unknown"

function detectIntent(question: string, screen: AgentScreen): Intent {
  const has = (...words: string[]) => words.some((word) => question.includes(word))
  if (has("추천")) return "recommend"
  if (screen.screenType === "risk-district") {
    if (has("요약", "현황")) return "district-summary"
    if (has("오른", "올라", "증가", "가장")) return "district-top"
  }
  if (screen.screenType === "risk-dong") {
    if (has("원인", "이유", "설명", "왜")) return "dong-explain"
    if (has("먼저", "대상", "누구")) return "dong-targets"
  }
  if (screen.screenType === "resource-detail" && has("맞", "대상", "누구", "어떤")) return "resource-fit"
  if (has("무엇", "뭐", "할 수", "어떻게")) return "help"
  return "unknown"
}

const monthText = (month: string) => `${month.slice(0, 4)}년 ${Number(month.slice(5))}월`
const signed = (value: number, digits = 1) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`
const dongNameOf = (dongCode: string) => db.dongs.find((item) => item.dongCode === dongCode)?.dongName ?? ""
const sigunguNameOf = (sigunguCode: string) => db.sigungus.find((item) => item.sigunguCode === sigunguCode)?.sigunguName ?? ""

export function respond(member: Member, request: AgentAskRequest): AgentEvent[] {
  const question = request.question.trim()
  const screen = request.screen
  const builder = new EventBuilder(devAgent.takeFault())
  const intent = detectIntent(question, screen)
  serverNote(`질문과 화면 정보(${screen.screenType})로 할 일을 고름: ${intent}`)

  switch (intent) {
    case "district-summary":
      return districtSummary(builder, screen)
    case "district-top":
      return districtTop(builder, screen)
    case "dong-explain":
      return dongExplain(builder, screen)
    case "dong-targets":
      return dongTargets(builder, member, screen)
    case "recommend":
      return recommend(builder, member, screen)
    case "resource-fit":
      return resourceFit(builder, screen)
    case "help":
      return help(builder, screen)
    case "unknown":
      if (!builder.step("screen")) return builder.events
      return builder.answer([
        { kind: "text", text: "프로토타입에서는 화면별 예시 질문에만 답할 수 있어요. 아래 질문을 눌러 보세요." },
        { kind: "list", items: exampleQuestions(screen) },
      ])
  }
}

// ── 고립 위험 탐색 ──

function rowsOf(sigunguCode: string, month: string) {
  return db.dongMonthlyAnalyses
    .filter((item) => item.month === month && item.dongCode.startsWith(sigunguCode))
    .map((item) => ({ ...item, dongName: dongNameOf(item.dongCode) }))
}

function districtSummary(builder: EventBuilder, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "risk-district") return builder.events
  if (!builder.step("screen", `${sigunguNameOf(screen.sigunguCode)} · ${screen.from} ~ ${screen.to}`)) return builder.events
  const rows = rowsOf(screen.sigunguCode, screen.to)
  serverNote(`분석 결과(시군구=${screen.sigunguCode}, 기준 월=${screen.to})를 조회해 AI에 넘김`)
  if (!builder.step("analysis", `행정동 ${rows.length}개 · ${monthText(screen.to)}`)) return builder.events
  const name = sigunguNameOf(screen.sigunguCode)
  if (rows.length === 0) return builder.answer([{ kind: "text", text: `${name}에는 적재된 분석 결과가 없어요.` }])
  const names = (list: typeof rows) => list.map((item) => item.dongName).join(", ") || "없음"
  const background = rows.filter((item) => item.backgroundStage >= 4)
  const behavior = rows.filter((item) => item.behaviorStage >= 4)
  const increased = rows.filter((item) => (item.behaviorChange ?? 0) > 0)
  const top = [...rows].sort((a, b) => b.behaviorScore - a.behaviorScore)[0]
  const items = [
    `배경 취약성 4·5단계: ${background.length}개 동 (${names(background)})`,
    `행동 이상 4·5단계: ${behavior.length}개 동 (${names(behavior)})`,
    rows.some((item) => item.behaviorChange === null)
      ? "첫 적재 월이라 전월과 비교한 변화는 없어요."
      : `전월보다 행동 이상 점수가 오른 동: ${increased.length}개`,
    `행동 이상 점수가 가장 높은 동: ${top.dongName} (${top.behaviorScore.toFixed(1)}점, ${top.behaviorStage}단계)`,
  ]
  return builder.answer([
    { kind: "text", text: `**${name} ${monthText(screen.to)}** 고립 위험 현황을 요약했어요.` },
    { kind: "list", items },
    { kind: "text", text: "지도에서 동을 누르면 그 동의 인사이트 보고서를 볼 수 있어요." },
  ])
}

function districtTop(builder: EventBuilder, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "risk-district") return builder.events
  if (!builder.step("screen", `${sigunguNameOf(screen.sigunguCode)} · 기준 월 ${screen.to}`)) return builder.events
  const rows = rowsOf(screen.sigunguCode, screen.to)
  serverNote(`분석 결과의 전월 대비 행동 이상 변화(시군구=${screen.sigunguCode}, 기준 월=${screen.to})를 조회함`)
  if (!builder.step("analysis", `행정동 ${rows.length}개`)) return builder.events
  if (rows.length === 0 || rows.some((item) => item.behaviorChange === null)) {
    return builder.answer([{ kind: "text", text: "첫 적재 월이라 전월과 비교한 변화가 없어요. 기간의 마지막 월을 바꿔 보세요." }])
  }
  const sorted = [...rows].sort((a, b) => (b.behaviorChange ?? 0) - (a.behaviorChange ?? 0))
  const [first, ...rest] = sorted
  return builder.answer([
    {
      kind: "text",
      text: `${monthText(screen.to)} 행동 이상 점수가 가장 많이 오른 동은 **${first.dongName}(${signed(first.behaviorChange ?? 0)}점)**이에요.`,
    },
    {
      kind: "list",
      items: rest.slice(0, 2).map((item) => `${item.dongName}: ${signed(item.behaviorChange ?? 0)}점 (지금 ${item.behaviorStage}단계)`),
    },
    { kind: "text", text: `지도에서 ${first.dongName}을 누르면 원인을 설명한 인사이트 보고서를 볼 수 있어요.` },
  ])
}

function reportOf(dongCode: string, month: string) {
  return db.insightReports.find((item) => item.dongCode === dongCode && item.month === month) ?? null
}

function dongExplain(builder: EventBuilder, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "risk-dong") return builder.events
  const dongName = dongNameOf(screen.dongCode)
  if (!builder.step("screen", `${dongName} · ${monthText(screen.month)}`)) return builder.events
  const report = reportOf(screen.dongCode, screen.month)
  serverNote(`저장된 인사이트 보고서(행정동=${screen.dongCode}, 기준 월=${screen.month})를 조회해 AI에 넘김`)
  if (!builder.step("report", report ? "보고서 있음" : "보고서 없음")) return builder.events
  if (!report) return builder.answer([{ kind: "text", text: "이 달의 인사이트 보고서가 아직 없어 원인을 설명할 수 없어요." }])
  const factors = report.sections
    .flatMap((section) => section.blocks)
    .flatMap((block) => (block.kind === "chart" && block.chart.type === "factors" ? block.chart.items : []))
  if (factors.length === 0) {
    const row = db.dongMonthlyAnalyses.find((item) => item.dongCode === screen.dongCode && item.month === screen.month)
    return builder.answer([
      {
        kind: "text",
        text: `${monthText(screen.month)}은 첫 적재 월이라 전월과 비교한 원인 분석이 없어요. 이 달 행동 이상 점수는 **${row?.behaviorScore.toFixed(1)}점(${row?.behaviorStage}단계)**이에요.`,
      },
    ])
  }
  const main = factors.slice(0, 3)
  const plain =
    screen.dongCode === "1168066000" && screen.month === "2025-12"
      ? "쉽게 말해, 12월 들어 **주말에 동네 활동이 크게 줄었고** 요일마다 생활 리듬이 비슷하게 굳어졌어요. 한파와 연말 영향으로 가족 단위 외출이 줄어든 것이 가장 큰 이유로 보여요."
      : `쉽게 말해, **'${main[0].label}'** 쪽 변화가 점수에 가장 크게 영향을 줬어요.`
  return builder.answer([
    { kind: "text", text: report.headline },
    { kind: "text", text: "점수를 가장 많이 바꾼 요인은 다음과 같아요." },
    { kind: "list", items: main.map((item) => `${item.label} (${signed(item.value, 2)})`) },
    { kind: "text", text: plain },
  ])
}

function myCasesIn(member: Member, dongCode: string) {
  const mine = new Set(db.caseManagers.filter((item) => item.memberId === member.memberId).map((item) => item.caseId))
  return db.cases.filter((item) => item.orgId === member.orgId && mine.has(item.caseId) && item.dongCode === dongCode)
}

function dongTargets(builder: EventBuilder, member: Member, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "risk-dong") return builder.events
  const dongName = dongNameOf(screen.dongCode)
  if (!builder.step("screen", `${dongName} · ${monthText(screen.month)}`)) return builder.events
  const report = reportOf(screen.dongCode, screen.month)
  if (!builder.step("report", report ? "보고서 있음" : "보고서 없음")) return builder.events
  const cases = myCasesIn(member, screen.dongCode)
  const byAge = new Map<AgeGroup, number>()
  cases.forEach((item) => {
    const group = ageGroupOf(ageOn(item.birthDate))
    byAge.set(group, (byAge.get(group) ?? 0) + 1)
  })
  serverNote("이 동의 담당 사례자는 연령대별 인원만 세어 AI에 넘김 (이름·관리번호·생년월일은 넘기지 않음)")
  if (!builder.step("myCases", `${cases.length}명`)) return builder.events
  const actions = report?.sections
    .filter((section) => section.question?.includes("조치"))
    .flatMap((section) => section.blocks)
    .flatMap((block) => (block.kind === "bullets" ? block.items.map((item) => `${item.label}: ${item.text}`) : []))
  const ages = [...byAge.entries()].map(([group, count]) => `${group} ${count}명`).join(", ")
  return builder.answer([
    { kind: "text", text: `**${dongName}**에서 먼저 살펴볼 대상을 보고서의 조치 제안으로 정리했어요.` },
    { kind: "list", items: actions && actions.length > 0 ? actions : ["이 달 보고서에 조치 제안이 없어요."] },
    {
      kind: "text",
      text:
        cases.length > 0
          ? `이 동에 내가 담당하는 사례자는 **${cases.length}명**이에요 (${ages}). '사례자 탐색'에서 이 동으로 찾아볼 수 있어요.`
          : "이 동에 내가 담당하는 사례자는 없어요.",
    },
  ])
}

// ── 사례자 맞춤 복지자원 추천 (0.2.3) ──

const NEED_RULES: { need: string; consult: string[]; resource: string[] }[] = [
  { need: "식사 지원", consult: ["식사", "끼니", "반찬", "도시락"], resource: ["식사", "반찬", "급식", "도시락", "요리", "끼니"] },
  {
    need: "관계·정서 지원",
    consult: ["외로", "말벗", "외출", "교류", "안부", "우울"],
    resource: ["말벗", "안부", "이웃", "모임", "산책", "교류", "고독", "정서"],
  },
  { need: "주거 지원", consult: ["주거", "집 안", "정리", "난방"], resource: ["주거", "난방", "집 안"] },
  { need: "건강 지원", consult: ["건강", "병원", "거동", "혈압"], resource: ["건강", "체조", "걷기", "목욕", "치매", "혈압"] },
]

/** 상담 내용의 이름 가리기: 사례자 이름 + '성씨로 시작하는 2~3글자 + 씨/님' + 관리번호 */
function maskNames(text: string, caseName: string): MaskResult {
  return maskIdentity(text, [caseName])
}

function recommend(builder: EventBuilder, member: Member, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "case-detail") {
    if (!builder.step("screen")) return builder.events
    return builder.answer([{ kind: "text", text: "맞춤 복지자원 추천은 사례자 상세 화면에서 요청해 주세요." }])
  }
  const record = requireCaseAccess(member, screen.caseId)
  const ageGroup = ageGroupOf(ageOn(record.birthDate))
  const dongName = dongNameOf(record.dongCode)
  const sigunguCode = record.dongCode.slice(0, 5)
  const sigunguName = sigunguNameOf(sigunguCode)
  const profile = `${ageGroup} · ${record.gender} · ${sigunguName} ${dongName}`
  if (!builder.step("caseInfo", profile)) return builder.events

  const consultations = db.consultations.filter((item) => item.caseId === record.caseId)
  let maskedCount = 0
  const maskedContents = consultations.map((item) => {
    const result = maskNames(item.content, record.name)
    maskedCount += result.count
    return result.text
  })
  serverNote(
    `AI에 넘긴 사례자 정보: 연령대 ${ageGroup}, 성별 ${record.gender}, 지역 ${sigunguName} ${dongName}, 상담 ${consultations.length}건. 이름·관리번호·생년월일은 넘기지 않음`,
  )
  if (maskedCount > 0) {
    const example = maskedContents.find((text) => text.includes("○○○")) ?? ""
    serverNote(`상담 내용에 적힌 이름 ${maskedCount}곳을 가려서 넘김. 예: "${example}"`)
  }
  const needCounts = NEED_RULES.map((rule) => ({
    ...rule,
    count: maskedContents.filter((text) => rule.consult.some((word) => text.includes(word))).length,
  })).filter((rule) => rule.count > 0)
  const needs = needCounts.map((rule) => rule.need)
  if (!builder.step("needs", needs.length > 0 ? `${needs.join(" · ")} (상담 ${consultations.length}건)` : `찾지 못함 (상담 ${consultations.length}건)`)) {
    return builder.events
  }

  const eligible = db.resources.filter(
    (resource) =>
      resource.deletedAt === null &&
      (resource.dongCode === record.dongCode || (resource.dongCode === null && resource.sigunguCode === sigunguCode)) &&
      (resource.supportAgeGroups.includes(ageGroup) || resource.supportAgeGroups.includes("무관")) &&
      (resource.supportGender === record.gender || resource.supportGender === "무관"),
  )
  const textOf = (resource: WelfareResource) => `${resource.resourceName} ${resource.target} ${resource.supportContent ?? ""}`
  const matchedNeeds = (resource: WelfareResource) =>
    needCounts.filter((rule) => rule.resource.some((word) => textOf(resource).includes(word)))
  const candidates = (status: "진행 중" | "종료") =>
    eligible.filter((resource) => effectiveStatus(resource) === status && (needs.length === 0 || matchedNeeds(resource).length > 0))

  serverNote("복지자원 검색: 지역(같은 동 또는 시군구 전체)·지원 연령·지원 성별이 맞고, 상담에서 찾은 지원과 겹치는 자원")
  let found = candidates("진행 중")
  if (!builder.step("searchActive", `맞는 자원 ${found.length}개`)) return builder.events
  let expanded = false
  if (found.length === 0) {
    expanded = true
    found = candidates("종료")
    serverNote("진행 중인 자원에서 찾지 못해 종료된 자원까지 넓혀 찾음 (0.2.3)")
    if (!builder.step("searchEnded", `맞는 자원 ${found.length}개`)) return builder.events
  }

  if (found.length === 0) {
    return builder.answer([
      {
        kind: "text",
        text: `조건에 맞는 복지자원을 찾지 못했어요. (필요한 지원: ${needs.join(", ") || "찾지 못함"} / 지역: ${sigunguName} ${dongName} / ${ageGroup} · ${record.gender})`,
      },
      { kind: "text", text: "복지자원 조회에서 지역이나 조건을 바꿔 찾아보세요." },
    ])
  }

  // 점수: 겹치는 지원(상담에서 자주 나온 지원일수록 높게) + 같은 동이면 더함. 이미 고른 자원의 지원은 절반으로 줄여 고르게 고른다
  const weight = new Map(needCounts.map((rule) => [rule.need, rule.count]))
  const picked: WelfareResource[] = []
  const pool = [...found]
  while (picked.length < 3 && pool.length > 0) {
    const scored = pool
      .map((resource) => ({
        resource,
        score:
          matchedNeeds(resource).reduce((sum, rule) => sum + (weight.get(rule.need) ?? 0), 0) +
          (resource.dongCode === record.dongCode ? 1.5 : 0.5),
      }))
      .sort((a, b) => b.score - a.score || Number(b.resource.dongCode !== null) - Number(a.resource.dongCode !== null) || a.resource.resourceId - b.resource.resourceId)
    const best = scored[0].resource
    picked.push(best)
    pool.splice(pool.indexOf(best), 1)
    matchedNeeds(best).forEach((rule) => weight.set(rule.need, (weight.get(rule.need) ?? 0) / 2))
  }

  const cards = picked.map((resource, index) => cardOf(resource, index + 1, record.dongCode, ageGroup, needs, matchedNeeds(resource).map((rule) => rule.need), consultations.length))
  const intro = expanded
    ? "진행 중인 자원 중에는 맞는 것이 없어 **종료된 자원까지 넓혀** 찾았어요. 다시 운영하는지 먼저 확인하세요."
    : needs.length === 0
      ? "상담 기록에서 필요한 지원을 찾지 못해 **지역·연령·성별**로만 찾았어요."
      : `상담 기록과 기본 정보를 바탕으로 **진행 중인 자원 ${cards.length}개**를 추천해요.`
  return builder.answer([
    { kind: "text", text: intro },
    { kind: "resourceCards", expanded, cards },
  ])
}

function cardOf(
  resource: WelfareResource,
  rank: number,
  caseDongCode: string,
  ageGroup: AgeGroup,
  needs: string[],
  matched: string[],
  consultationCount: number,
): RecommendationCard {
  const status = effectiveStatus(resource)
  const sameDong = resource.dongCode === caseDongCode
  const region = resource.dongCode ? dongNameOf(resource.dongCode) : `${sigunguNameOf(resource.sigunguCode)} 전체`
  const fee = resource.fee === 0 ? "무료" : `${resource.fee.toLocaleString("ko-KR")}원`
  const unmatched = needs.filter((need) => !matched.includes(need))
  const checks: RecommendationCard["checks"] = [
    { label: `${region} 지원`, state: "met", note: sameDong ? "같은 동 — 자료상 확인" : "시군구 전체 대상 — 자료상 확인" },
    {
      label: resource.supportAgeGroups.includes("무관") ? "연령 제한 없음" : `${ageGroup} 대상`,
      state: "met",
      note: "자료상 확인",
    },
    ...matched.map((need) => ({ label: need, state: "met" as CheckState, note: "자료상 확인" })),
    ...unmatched.map((need) => ({ label: need, state: "unmet" as CheckState, note: "이 자원에는 없음" })),
    status === "진행 중"
      ? { label: "운영 상태", state: "met", note: "진행 중" }
      : { label: "운영 상태", state: "unmet", note: "종료 — 다시 운영하는지 확인 필요" },
    resource.actualParticipants === null
      ? { label: "정원 여유", state: "unknown", note: "참여 인원 정보 없음 — 기관 확인 필요" }
      : resource.actualParticipants >= resource.capacity
        ? { label: "정원 여유", state: "unknown", note: `정원이 찼을 수 있음 (${resource.actualParticipants}/${resource.capacity}명) — 기관 확인 필요` }
        : { label: "정원 여유", state: "met", note: `여유 있음 (${resource.actualParticipants}/${resource.capacity}명)` },
    { label: "세부 신청 자격", state: "unknown", note: "기관 확인 필요" },
  ]
  const reason = [
    matched.length > 0 ? `상담에서 확인한 '${matched.join(", ")}'에 맞는 자원이에요.` : "지역·연령·성별 조건이 맞는 자원이에요.",
    sameDong ? `같은 동(${region})에서 운영해요.` : `${region} 주민이 이용할 수 있어요.`,
    status === "종료" ? "다만 지금은 종료된 자원이라 다시 운영하는지 확인이 필요해요." : "",
    unmatched.length > 0 ? `'${unmatched.join(", ")}'은 다른 자원으로 함께 살펴보세요.` : "",
  ]
    .filter(Boolean)
    .join(" ")
  return {
    rank,
    resourceId: resource.resourceId,
    resourceName: resource.resourceName,
    operatingOrgName: resource.operatingOrgName,
    status,
    tags: [region, ...(matched.length > 0 ? [matched[0]] : []), fee],
    reason,
    checks,
    beforeUse: [
      `신청 방법: ${resource.applyMethod ?? "기관에 문의"}`,
      `이용자 부담금: ${fee}`,
      `운영 기간: ${resource.periodStart.replace(/-/g, ".")} ~ ${resource.periodEnd.replace(/-/g, ".")}`,
    ],
    evidence: `상담 기록 ${consultationCount}건 · 기본 정보(연령대·성별·지역) · 복지자원 등록 정보`,
  }
}

// ── 그 밖의 화면 ──

function resourceFit(builder: EventBuilder, screen: AgentScreen): AgentEvent[] {
  if (screen.screenType !== "resource-detail") return builder.events
  const resource = db.resources.find((item) => item.resourceId === screen.resourceId && item.deletedAt === null)
  serverNote(`복지자원(${screen.resourceId}) 등록 정보를 조회해 AI에 넘김`)
  if (!builder.step("resource", resource?.resourceName ?? "찾지 못함")) return builder.events
  if (!resource) return builder.answer([{ kind: "text", text: "이 복지자원을 찾지 못했어요." }])
  const region = resource.dongCode ? `${sigunguNameOf(resource.sigunguCode)} ${dongNameOf(resource.dongCode)}` : `${sigunguNameOf(resource.sigunguCode)} 전체`
  return builder.answer([
    { kind: "text", text: `**${resource.resourceName}**은 '${resource.target}'을 위한 자원이에요.` },
    {
      kind: "list",
      items: [
        `지원 연령: ${resource.supportAgeGroups.join(", ")} · 지원 성별: ${resource.supportGender}`,
        `지역: ${region}`,
        `상태: ${effectiveStatus(resource)}${resource.actualParticipants !== null ? ` · 정원 ${resource.capacity}명 중 ${resource.actualParticipants}명 참여 중` : ` · 정원 ${resource.capacity}명`}`,
      ],
    },
    { kind: "text", text: "사례자 상세 화면에서 'AI 맞춤 자원 추천'을 누르면 사례자에게 맞는 자원을 찾아 드려요." },
  ])
}

const PATH_HELP: { prefix: string; text: string }[] = [
  { prefix: "/resources/new", text: "복지자원을 등록하는 화면이에요. 위쪽 'PDF로 자동 입력'으로 안내문을 올리면 양식을 채워 드려요." },
  { prefix: "/resources", text: "복지자원을 지역·연령·성별·정원·담당자로 찾을 수 있어요. 다른 기관의 자원도 함께 보여요." },
  { prefix: "/cases/new", text: "새 사례자를 등록하는 화면이에요. 같은 이름·생년월일의 사례자가 있으면 알려 드려요." },
  { prefix: "/cases", text: "내가 담당하는 사례자를 찾는 화면이에요. 사례자 상세에서 'AI 맞춤 자원 추천'을 받을 수 있어요." },
  { prefix: "/my", text: "내 정보와 AI 대화 기록을 관리하는 화면이에요." },
]

function help(builder: EventBuilder, screen: AgentScreen): AgentEvent[] {
  if (!builder.step("screen")) return builder.events
  const path = screen.screenType === "other" ? screen.path : ""
  const text =
    screen.screenType === "risk-district" || screen.screenType === "risk-dong"
      ? "고립 위험 탐색 화면이에요. 지도와 그래프로 행정동별 고립 위험을 보고, 동을 누르면 인사이트 보고서를 볼 수 있어요."
      : screen.screenType === "case-detail"
        ? "사례자 정보와 상담 기록을 보는 화면이에요. 'AI 맞춤 자원 추천'으로 맞는 복지자원을 찾을 수 있어요."
        : (PATH_HELP.find((item) => path.startsWith(item.prefix))?.text ?? "이 화면에 대한 안내가 아직 없어요.")
  return builder.answer([{ kind: "text", text }])
}
