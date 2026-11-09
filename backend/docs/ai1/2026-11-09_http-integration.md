# AI-a 대화 패널 HTTP 연결 · 구현과 MR 인계

2026-11-09. 브랜치 `feat/be-agent-http`, 기준 develop `6cdf889`. Jira: 미지정.

## 1. 작업 ID · API ID

AI-a (계획 4-1 'AI-a 대화 패널 (BE)'), API-03 · API-03-S1 · API-03-S2, INT-01 · INT-02 · INT-07.

기준: AGENTS.md 4 · 8장, `docs/work-ref/미구현_기능_구현_계획.md` 4-1, `내부_연동_변경_계획.md` 1 · 2절. AI-b 보고서 작업은 포함하지 않는다.

- INT-01 전용 RunRequest: `{conversationId, messageId, context?}`. messageId는 커밋된 질문 행 ID다. API-03 응답은 기존 `{conversationId, questionId}`를 유지한다.
- INT-03 메서드/HTTP 호출을 제거했다. 새 행이 응답 없음 기준 동안 없으면 같은 질문을 한 번만 재요청한다. 재요청 실패나 최초 접수 응답 유실만으로 실패 행을 쓰지 않고, 질문 시각 + 실행 제한 + 여유 이후에만 대신 쓴다.
- 선택 context의 dongCode/month를 형식 검사하고 질문별 메모리에 보관한다. 질문/대화 DB에는 저장하지 않는다. 재요청 때 같은 값을 쓰고, 재시작 후에는 생략한다.
- 내부 Bearer 전용 보안 체인과 INT-07 수신을 추가했다. 커밋된 같은 대화의 AI 행인지 검사하고 204를 반환한다. 끝 행이면 해당 질문의 문맥/재요청/취소 대기 메모리를 정리한다.
- INT-02의 HTTP 응답을 기다릴 때도 INT-07을 처리할 수 있게 알림 정리에 대화 잠금을 요구하지 않는다. 취소 응답 유실 시 취소 대기 시각까지 AI 끝 행을 기다린다.

## 2. 계약과 달라진 점 · DTO · 오류 · docs/api 반영 요청

현재 계획 대비 차이: 없음. 공식 OpenAPI 2.3.3에 아직 없는 선택 context/내부 형식 변경은 계획과 이번 사용자 지시대로 구현했다. 공식 계약 파일은 수정하지 않았다.

인프라 대화가 openapi **2.3.4** · `ai-agent-panel.md` 초안에 반영할 내용:

1. API-03 입력: 기존 conversationId/question에 선택 `context` 객체 추가. 선택 dongCode는 숫자 10자리 문자열, month는 유효한 `YYYY-MM`(0000년 제외) 문자열이다. `{}`/필드 생략 허용, null 필드는 AI로 보낼 때 생략한다. 알 수 없는 필드/타입과 형식 오류는 400이다. 출력 questionId는 유지한다.
2. INT-01: POST `/internal/agent/runs`, `{conversationId, messageId, context?}`, 본문 없는 202. 같은 messageId는 202로 멱등 접수, 다른 활성 질문은 409. BE는 409 뒤 상태 조회를 하지 않는다. 문맥/질문 내용은 INT-01 응답 본문에서 읽지 않는다.
3. INT-02: POST `/internal/agent/runs/{conversationId}/cancel`, 본문 없는 202. 응답 대기는 HTTP 제한과 cancel-wait 중 짧은 시간이다. AI가 취소 처리 중 INT-07을 먼저 보내도 허용한다.
4. INT-07: POST `/api/internal/agent/notifications`, `{conversationId: UUID, messageId: 양의 int64 JSON 정수}`. messageId는 질문 행이 아니라 방금 커밋한 AI 행 ID다. 204 본문 없음, 입력 오류 400, 토큰 오류 401/403, 같은 대화의 AI 행이 아니면 404 NOT_FOUND. 중복/역순 알림에 의존하지 않으며 알림 이력은 저장하지 않는다.
5. INT-03 목록/상태 조회 형식을 제거하고, 1회 재요청/절대 시간 제한 복구 규칙으로 교체한다. 화면은 1초 조회를 유지한다.

새 업무 오류 코드를 추가하지 않았다. INVALID_JSON/VALIDATION_ERROR, UNAUTHENTICATED/FORBIDDEN, NOT_FOUND, 기존 실행/권한 오류를 재사용한다. AI_UNAVAILABLE은 AI-b 범위다.

## 3. 권한 · 잠금 · 설정

브라우저 세션/CSRF 체인은 그대로 두고, `/api/internal/**`(Security matcher `/internal/**`)에 우선순위 1의 stateless 체인을 추가했다. NullSecurityContextRepository를 사용하며 세션/CSRF 쿠키를 생성하지 않는다. 브라우저 인증으로 서비스 토큰을 대신할 수 없다.

| 설정 이름 | 환경변수 | fake | http |
|---|---|---|---|
| `eumi.internal.ai-token` | `EUMI_AI_TOKEN` | 선택. 없으면 해당 호출자 401 | 필수 |
| `eumi.internal.pipeline-token` | `EUMI_PIPELINE_TOKEN` | 선택. 없으면 해당 호출자 401 | 필수 |

두 토큰은 서로 달라야 한다. 공백/제어 문자/미해석 placeholder는 기동 실패다. 값은 코드/문서/로그/테스트에 넣지 않았고 테스트 토큰은 메모리에서 생성한다. 실제 AI 검사의 인증값은 로컬 설정에서 실행 환경으로만 읽었다. 토큰 비교는 MessageDigest.isEqual이다.

- 토큰 없음/잘못됨/중복 Authorization 헤더: 401. 파이프라인 토큰으로 INT-07 호출: 403. INT-07만 AI 권한으로 허용한다. INT-04/08 등 AI-b 경로는 아직 허용/구현하지 않았다.
- 운영 compose의 backend에 위 두 환경변수를 전달한다. AI의 SETTINGS_BACKEND_TOKEN과 backend의 EUMI_AI_TOKEN이 같아야 한다. 값은 보고에 남기지 않는다.
- 기존 EUMI_AI_MODE / AI_BASE_URL, EUMI_AI_HTTP_TIMEOUT(기본 3초), 시간 값 4개 이름은 유지한다. http는 실행 제한/여유/응답 없음/취소 대기를 모두 명시해야 하고 fake 개발 기본값은 유지한다. 운영 숫자는 인프라/AI 담당이 확정해 전달한다.
- 질문 저장 트랜잭션 커밋 뒤 AI를 호출한다. HTTP 대기 중 DB 트랜잭션/연결을 유지하지 않는다. 대화별 메모리 잠금으로 동시 조회의 재요청을 한 번으로 제한한다.
- INT-07의 행 검증은 읽기만 한다. 행의 question_id로만 정리하므로 이전 질문의 늦은 끝 알림이 다음 질문의 상태를 지우지 않는다. 알림 정리에는 HTTP 호출의 잠금을 잡지 않아 취소/알림 상호 대기를 피한다.

## 4. 실행한 검사와 결과

JDK 21.0.11 / Gradle Wrapper 9.8.2. 사용자가 준비한 로컬 PostgreSQL과 compose profile ai의 FastAPI를 사용했다. 에이전트가 docker compose를 실행하지 않았다.

| 구분 | 실제 실행 결과 |
|---|---|
| 전체 단위/MVC/설정/HTTP 대역 (`test`) | 143개 통과, 실패/오류/생략 0 |
| 실제 PostgreSQL/BE HTTP + 기존 fake/대화 기록/DB 경합 | AgentIntegrationTests, ConversationHistoryIntegrationTests, AgentWriterConcurrencyIntegrationTests 통과 |
| 실제 PostgreSQL/BE HTTP + AI 장애 mock | AgentRecoveryIntegrationTests 통과. 커밋 이후 호출, 조기 실패 방지, 절대 제한, 취소/동시 질문 확인 |
| 실제 PostgreSQL/BE/AI HTTP 클라이언트 + 로컬 HTTP 대역 | AgentHttpRecoveryIntegrationTests 4개 통과. 같은 문맥으로 재요청 정확히 1회, 최초/재접수 실패 뒤 대기, INT-07 권한/행 소속, 취소 대기 |
| 실제 FastAPI/호스트 BE 8080/PostgreSQL | AgentLiveAiIntegrationTests 2개 통과. INT-01 202, AI의 진행/끝 행 커밋 뒤 INT-07 204, INT-02 실제 취소와 끝 행 1개 |
| bootJar / git diff --check | 통과 |

실제 FastAPI 검사에서 일반 질문은 AI가 `진행` 뒤 `실패` 행을 커밋하고 INT-07을 보냈으며, 취소 질문은 AI의 `취소` 행과 INT-07을 확인했다. 모델의 정상 답변/GMS 호환성 검증을 통과했다고 해석하지 않는다. AI 무응답/접수 실패는 실제 HTTP 대역으로 만들었고 실제 AI 컨테이너를 중단시키지 않았다.

주요 실행 명령(backend 폴더):

```powershell
.\gradlew.bat test --console=plain
.\gradlew.bat integrationTest --tests com.eumi.backend.AgentIntegrationTests --tests com.eumi.backend.AgentRecoveryIntegrationTests --tests com.eumi.backend.AgentHttpRecoveryIntegrationTests --tests com.eumi.backend.AgentWriterConcurrencyIntegrationTests --tests com.eumi.backend.ConversationHistoryIntegrationTests bootJar --console=plain
# 로컬 토큰을 실행 환경에 준비하고 EUMI_VERIFY_LIVE_AI=true인 경우에만 다음 검사를 실행한다.
.\gradlew.bat integrationTest --tests com.eumi.backend.AgentLiveAiIntegrationTests --console=plain
```

실제 AI 검사는 8080 포트가 비어 있어야 한다. 다른 backend를 임의로 중단하지 않는다. 테스트는 자신이 생성한 회원/기관/대화/세션만 정리하며, AI 질문/인증정보 원문은 결과 기록에 넣지 않는다. 테스트용 8080 서버는 검사 뒤 종료했다. 선별 실행 시 integrationTest XML은 마지막 선택 클래스 결과로 바뀌므로 위 검사들을 구분한다.

기존 fake의 진행/완료/취소 동작은 유지했다. 이전 INT-03/즉시 시작 실패를 전제한 테스트만 새 복구 계약으로 바꿨고, fake 실행 중 상태 검사는 HTTP 상태 조회가 아닌 fake 전용 isRunning으로 옮겼다.

## 5. 남은 것 · 리뷰 요청

- **Claude Code 리뷰 필수.** 커밋/병합 전에 전용 INT-01 DTO, 커밋 이후 호출, 재요청 실패 시 조기 끝 행 금지, 질문별 문맥/늦은 알림 분리, 내부/브라우저 보안 경계, 취소 중 알림 처리와 메모리 정리를 검토한다. 이 작업에서 외부 리뷰 완료로 표시하지 않았다.
- 인프라 대화: 2절의 OpenAPI 2.3.4/ai-agent-panel.md 초안과 위 환경변수 전달을 AI-a MR에 맞춘다. fake 유지로 먼저 배포하고, GMS/시간 값 준비와 AI-a 확인 뒤 http 전환한다.
- AI 담당: 실제 검사는 연결/실패/취소 경로를 확인했다. 모델/GMS 정상 응답은 별도 확인한다. 현재 AI의 notify 함수는 최대 두 번 전송하는 구현이고 변경 계획은 INT-07 재시도 없음이므로 이 차이를 맞춰야 한다. BE는 중복을 허용한다. AI 파일은 수정하지 않았다.
- FE 담당: context 전송/기준 표시와 artifacts 출력은 FE MR 범위다. 기존 질문 응답 questionId는 유지한다.
- 다음은 AI-b다. INT-04/05/08, API-11/12 전환, AI_UNAVAILABLE, 보고서 2단계 DB는 아직 구현하지 않았다. 그 뒤 순서 A3 → M3 → B1 → C4 → A2를 유지한다.
- docs/api · db/migration · infra · frontend · ai와 Git 이력/브랜치는 수정하지 않았다. 운영 배포/운영 http 전환도 하지 않았다.

제안 커밋 제목: `feat: [BE] AI 대화 패널 HTTP 연동`

MR 설명은 이 문서 1~5절을 사용한다.

Jira: <이슈 키>
