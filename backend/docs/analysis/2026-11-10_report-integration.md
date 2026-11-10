# AI-b 보고서 연결 · 구현과 MR 인계

2026-11-10. 브랜치 `feat/be-insight-report`, 기준 origin/develop `de4dc12` (문서 2.4.0 병합 포함), 리뷰 후속 작업 시작 `3f05963`, 코드 후속 커밋 `65290d0`. Jira: S15P31B201-237 (BE·AI 연결).

## 1. 작업 ID · API ID · 바뀐 파일

AI-b (계획 4-1), INT-04·05·08, API-11·12.

기준은 사용자의 11/10 2차 지시와 리뷰 후속 요청 1~4번, 이 clone의 확정 OpenAPI 2.4.0과 `docs/api/insight-report.md` 4·5·8·9절, AGENTS.md 4·8장이다. 문서 2.4.0이 포함된 `de4dc12` 위로 rebase한 HEAD `3f05963`을 시작 전 확인했고, 이 clone의 docs/api와 대조했다.

- 참조 위치: 이 clone의 `docs/api/` (`de4dc12`).
- OpenAPI 2.4.0 SHA-256: `53598a75139e8124d2dd1089b6222ee4dec2c5c2bac7934e6425c7b902c98c4a`.
- insight-report.md SHA-256: `629759d16f5be46bfb80fcf62f0ba763bf2a0f75667658fb0abb7f5e6846b422`.

| 파일 (backend 아래) | 변경 |
|---|---|
| `analysis/ReportDtos`, `ReportIntegrationController`, `ReportIntegrationService` | INT-04 접수와 INT-08 로그 전용 수신 |
| `analysis/ReportGenerationClient` | fake 무전송, HTTP INT-05 202 접수·제한 시간·503 매핑 |
| `analysis/AnalysisController`, `AnalysisDtos`, `AnalysisRepository`, `AnalysisService` | API-11·12 새 칸, 버전 일치와 허용 시트 검사 |
| `internal/InternalSecurityConfiguration`, `common/error/ErrorCode` | INT-04 PIPELINE·INT-08 AI 권한, AI_UNAVAILABLE(503) |
| `analysis/SavedReportReader` | 삭제. 예전 summary_lines·보고서 JSON 읽기를 제거 |
| `ReportIntegrationWebTests`, `ReportGenerationClientTests`, `ReportHttpIntegrationTests`, `ReportFakeIntegrationTests`, `support/ReportAiStub` | MVC·loopback HTTP·실제 DB/8080 검사 추가 |
| `AnalysisServiceTests`, `AnalysisIntegrationTests`, `AgentNotificationWebTests` | 새 보고서 계약과 허용 경로 반영. 예전 SavedReportReaderTests·JSON fixture 삭제 |
| `README.md`, `docs/analysis/` | 실행·검증·인계 기록 |

표의 Java 경로는 `src/main/java/com/eumi/backend/`, 테스트는 `src/test/java/com/eumi/backend/` 기준이다. 삭제한 JSON은 `src/test/resources/analysis/report.json`이다. 마이그레이션·seed·infra·AI·FE·docs/api는 바꾸지 않았다.

리뷰 후속 변경은 네 파일로 제한했다. `AnalysisController`의 API-11·12 month 패턴을 계약대로 복원하고, `AnalysisIntegrationTests`에 0000-01의 404 확인 두 건을 더했다. `ReportHttpIntegrationTests`는 `ReportGenerationClient` spy로 generate 시점의 트랜잭션·DB 연결 보유 여부를 기록한 뒤 실제 ReportAiStub 호출을 잇는다. assert는 HTTP 호출 후 테스트 본문에서 수행하며 기존 호출 횟수·본문 확인을 유지한다. 나머지 한 파일은 이 인계 문서다. 로그 항목·INT-04·08 DTO·권한과 다른 동작은 바꾸지 않았다.

## 2. 계약과 달라진 점 · DTO · 오류

**계약과 달라진 점:** INT-04·08 month는 0000년을 VALIDATION_ERROR 400으로 거절한다. insight-report.md 4절은 YYYY-MM만 적고 있으며, 이 제약은 AI valid_month·ScreenContext와 같은 규칙으로 유지했다. API-11·12 month는 OpenAPI의 `[0-9]{4}-(0[1-9]|1[0-2])` 패턴으로 복원했다.

INT-08 requestId는 문자열로 받아 `local-1`도 허용한다. 알 수 없는 필드·타입 오류는 INVALID_JSON 400, 필수 누락·값 제약 위반은 VALIDATION_ERROR 400이다.

**로그에 적용한 사용자 지시:** 확정 문서의 INT-08 설명에는 저장 수·실패 동 로그가 있지만, 이번 2차 지시의 "requestId · month · targetCount · 상태 코드만"을 우선했다. pipelineRunId/reason/savedCount/failedDongCodes·동 코드·예외 종류를 로그에서 제거했다. API 본문은 그대로 검사한다. 문서나 DB 파일은 고치지 않았다.

- INT-04 `POST /api/internal/analysis/pipeline-completions`: `{month, pipelineRunId?, reason?}`. 필수 month는 유효한 YYYY-MM(0000 제외), pipelineRunId는 앞뒤 공백 제거 후 코드 포인트 1~200자, reason은 FULL·RESULT_RELOAD·ANALYSIS_RELOAD이며 생략/null은 FULL이다. 알 수 없는 필드·JSON 타입은 INVALID_JSON 400, 값의 제약 위반은 VALIDATION_ERROR 400이다.
- 결과가 없는 월은 NOT_FOUND 404. fake는 INT-05를 보내거나 보고서를 만들지 않고 202 `{month,targetCount}`를 돌려준다. http는 AI가 제한 시간 안에 202로 접수해야 같은 202를 돌려준다. 연결 실패·시간 초과·다른 응답 상태는 AI_UNAVAILABLE 503이다.
- INT-05 `POST {AI_BASE_URL}/internal/insight-reports/runs`: `{requestId,month,dongCodes}`. 해당 월 region_result의 모든 adm_cd10을 중복 없이 정렬한다. requestId는 INT-04 응답 X-Request-Id/meta.requestId와 같은 서버 생성 UUID다. 인증 헤더·BE 재시도·응답 본문 해석은 없다.
- INT-08 `POST /api/internal/analysis/insight-report-completions`: `{requestId,month,savedCount,failedDongCodes}` → 204, 본문 없음. requestId는 필수 문자열이며 UUID 형식을 요구하지 않고 숫자/객체/배열/boolean의 문자열 변환도 허용하지 않는다. savedCount는 0 이상 JSON 정수, failedDongCodes는 10자리 문자열 배열이다. 알림은 로그만 남기며 이력·생성 상태·보고서를 DB에 쓰지 않는다. 같은 알림을 두 번 보내도 각각 204다.
- API-11: `insight.summary=[quick_insight]` 한 원소로 반환한다. 줄바꿈을 보존한다. quick_insight가 NULL이면 옛 insight_generated_at이 있어도 insight=null이다.
- API-12: `report={quickInsight,graphs:[{sheet,description} 3개],generatedAt}` 또는 null. graph_1~3의 순서를 유지한다. JOIN에서 result_updated_at=region_result.updated_at인 보고서만 읽는다. 결과 행 없음은 404, 미생성·옛 결과·옛 형식은 report=null이다. EmbedDetailV01~V08 밖의 시트가 하나라도 있으면 report=null과 WARN이다. 점수/퀵 인사이트 조회는 유지한다.
- 운영 조회 SQL은 새 칸과 v_region_insight의 quick_insight·insight_generated_at만 사용한다. 예전 summary_lines/report 칸에 의존하지 않는다. 테스트도 SELECT *를 제거하고 필요한 새 칸을 명시했다. 삭제 예정 칸을 직접 쓰는 legacy DB fixture를 제거했으며, 옛 결과 버전 null은 실제 DB에서, quickInsight=null/옛 생성 시각과 보고서 불일치 null은 칸 이름에 의존하지 않는 service fixture로 검사한다. 글자 수·시트 중복 등 AI 저장 검사는 AI/DB 책임이며 별도의 BE 저장 API는 없다.

**2.4.0 대조 완료**: INT-04·05·08 요청/응답/오류와 권한, API-11 summary 매핑, API-12 report 스키마·버전 일치·허용 시트 밖 null/WARN, AI_UNAVAILABLE 503. 예전 INT-05 targets/resultUpdatedAt·accepted 응답과 API-12 headline/sections는 폐기했다. INT-06은 추가하지 않았다.

## 3. 권한 · 잠금 · 운영 설정

- 내부 경로는 기존 stateless Bearer 체인만 사용하며 브라우저 세션·CSRF를 요구하거나 생성하지 않는다. 토큰 없음/틀림은 401, AI 토큰으로 INT-04 또는 파이프라인 토큰으로 INT-08은 403이다. INT-07 AI 권한은 유지한다.
- API-11·12는 기존 A1 로그인 세션이 필요하다. 로그인 회원은 전체 지역 조회 가능, 임시 비밀번호 제한은 403, 미인증/탈퇴는 401이다.
- INT-04의 목록 SELECT는 읽기 트랜잭션 안에서 끝내고, DB 연결/트랜잭션을 보유하지 않은 채 INT-05를 호출한다. 행 잠금·생성 상태 잠금·중복 접수 차단은 추가하지 않았다. 같은 월을 다시 보내는 것은 계약대로 새 생성 요청이다.
- INT-04 로그: requestId, month, targetCount, status(202/404/503). INT-08 로그: requestId, month, status=204. 알림의 문자열 requestId에 있는 제어/줄 분리 문자는 치환한다. API-12 시트 오류는 정적 경고 문구와 requestId, month, status=200만 남긴다. 토큰·본문·보고서 글·SQL·예외 원문은 남기지 않는다.

| 설정 이름 | 환경변수 | fake | http |
|---|---|---|---|
| `eumi.internal.ai-token` | `EUMI_AI_TOKEN` | 기동 시 선택. INT-07·08 호출에는 필요, 없으면 401 | 기동 시 필수 |
| `eumi.internal.pipeline-token` | `EUMI_PIPELINE_TOKEN` | 기동 시 선택. INT-04 호출에는 필요, 없으면 401 | 기동 시 필수 |
| `eumi.ai.mode` | `EUMI_AI_MODE` | fake 지정 | http 지정 |
| `eumi.ai.base-url` | `AI_BASE_URL` | 보고서 전송 안 함 | 내부 AI 주소 |
| `eumi.ai.http-timeout` | `EUMI_AI_HTTP_TIMEOUT` | 보고서 전송 안 함 | 기존 기본 3초, 응답 전체의 제한 시간 |

새 운영 환경변수는 없다. 두 내부 토큰은 서로 다른 값으로 전달하며 AI 쪽 backend 토큰과 EUMI_AI_TOKEN을 맞춘다. 기존 HTTP 모드의 실행 제한·여유·무응답·취소 대기 명시 설정도 그대로 필요하다. 토큰/비밀번호 원문은 이 기록에 넣지 않는다.

## 4. 실행한 검사와 결과

JDK 21.0.11 · Gradle 9.8.2. 사용자가 준비한 공용 로컬 PostgreSQL을 사용했다. Docker Compose·마이그레이션 실행은 하지 않았다.

### 이번 리뷰 후속 검사 (rebase 후 3f05963 + 현재 변경)

모든 시각은 2026-11-10 KST다. 클래스별 시각은 각 실행 직후 XML에서 읽은 suite 시작 시각이다. 아래 모든 클래스는 실패·오류·생략 0이다.

| 실행 | 시작~종료 | 결과 |
|---|---|---|
| `test` (DB 없는 단위·MVC·설정·HTTP 대역) | 10:37:11~10:37:29 | 21클래스 152개 통과 |
| 지정한 `integrationTest` 5클래스 (실제 PostgreSQL·BE HTTP, AI는 fake/mock/HTTP 대역) | 10:38:30~10:39:02 | 47개 통과 |
| `ReportFakeIntegrationTests` (실제 PostgreSQL·8080·합성 보고서 fixture) | 10:39:43~10:39:55 | 4개 통과. 빈 8080과 테스트용 DB 계정 환경 확인 후 실행 |
| `git diff --check` | 10:40:45 | 통과 |

단위·fixture·mock 검사:

| 클래스 | 개수 | 시작 시각 |
|---|---|---|
| AgentDiagnosticsTests | 2 | 10:37:27 |
| AgentConfigurationTests | 27 | 10:37:15 |
| AgentLifecycleTests | 5 | 10:37:16 |
| AgentNotificationWebTests | 4 | 10:37:17 |
| AgentProductionConfigurationTests | 6 | 10:37:21 |
| AnalysisServiceTests | 15 | 10:37:21 |
| CaseValidationTests | 5 | 10:37:21 |
| FoundationConfigurationTests | 4 | 10:37:21 |
| FoundationWebTests | 10 | 10:37:21 |
| HttpAgentClientTests | 5 | 10:37:22 |
| InternalApiPropertiesTests | 2 | 10:37:24 |
| MailServiceTests | 1 | 10:37:24 |
| MyPatchTests | 14 | 10:37:24 |
| PasswordChangeRequestTests | 8 | 10:37:24 |
| PasswordEncoderTests | 6 | 10:37:24 |
| ProductionConfigurationTests | 14 | 10:37:26 |
| ProductionCsrfCookieTests | 1 | 10:37:26 |
| ReferenceDataServiceTests | 4 | 10:37:26 |
| ReportGenerationClientTests | 9 | 10:37:27 |
| ReportIntegrationWebTests | 7 | 10:37:27 |
| ResourceValidationTests | 3 | 10:37:27 |

실제 DB·BE HTTP 검사 (AI 생성 자체는 검사하지 않음):

| 클래스 | 개수 | 시작 시각 |
|---|---|---|
| AgentHttpRecoveryIntegrationTests | 4 | 10:38:32 |
| AgentIntegrationTests | 7 | 10:38:41 |
| AgentRecoveryIntegrationTests | 9 | 10:38:48 |
| AnalysisIntegrationTests | 18 | 10:38:53 |
| ReportHttpIntegrationTests | 9 | 10:38:59 |
| ReportFakeIntegrationTests | 4 | 10:39:46 |

API-11·12의 month=0000-01 두 요청은 실제 HTTP에서 NOT_FOUND 404였고, 기존 형식 오류 400 검사도 통과했다. INT-05 generate 순간에는 활성 트랜잭션과 DataSource에 연결된 자원이 모두 없었으며, 기존 9개 보고서 HTTP 검사의 요청 본문·호출 횟수도 통과했다.

선별 실행 직후마다 클래스별 수·시각을 기록했다. 마지막 integrationTest XML에는 ReportFakeIntegrationTests 4개만 남아 있으며, 앞선 47개 실행 결과와 혼동하지 않는다. 검사 원본 요약은 로컬 build/ai-b-review-follow-up-checks.json에도 남겼다(빌드 산출물, 커밋 대상 아님).

이번에는 bootJar·별도 bootRun/curl을 다시 실행하지 않았다. 실제 AI/GMS, 2단계 V 파일 적용 DB, 새 형식 seed 적용 후 조회, 브라우저/Tableau·운영 배포는 미실행이다. EUMI_VERIFY_LIVE_AI는 설정하지 않았다.

### 리베이스 전 구현 검증 기록 (이전 실행)

아래 표와 10:07 별도 bootRun/curl 응답은 이전 구현 때 실행한 기록이다. 이번 후속 검사 결과는 위 표로 구분한다.

| 구분 | 결과 |
|---|---|
| 전체 단위/MVC/설정/HTTP 클라이언트 대역 (`test`) | 152개 통과, 실패·오류·생략 0 |
| `ReportIntegrationWebTests` | 토큰 401/403, JSON 타입/필드 400, 값 400, 404/503, requestId 일치, 문자열 local-1 중복 완료 204, 최소 로그 항목/로그 줄 주입 방지 |
| `ReportGenerationClientTests` | 실제 loopback HTTP로 빈 202, 본문 3필드·인증 헤더 없음, fake 무전송, 비202·느린 본문·연결 실패 503, 재시도 없음 |
| 실제 PostgreSQL + BE HTTP + AI HTTP 대역 (`ReportHttpIntegrationTests`) | 9개 통과. 전체 동 목록·정렬·requestId·202/503/400/401/403/404, INT-08 중복 204 확인 |
| 실제 PostgreSQL + 호스트 BE 8080 + fake (`ReportFakeIntegrationTests`) | 4개 통과. fake 접수→테스트가 AI 계정으로 새 칸 저장→완료 204→로그인 API-11·12 조회, 옛 결과 버전/미생성 null, 허용 밖 시트 null/WARN, 401/403/404 |
| 실제 PostgreSQL + 기존 분석 HTTP (`AnalysisIntegrationTests`) | 18개 통과 |
| 기존 AI-a fake/복구/HTTP 대역 회귀 | AgentIntegrationTests 7개, AgentRecoveryIntegrationTests 9개, AgentHttpRecoveryIntegrationTests 4개 통과 |
| `bootJar` / `git diff --check` | 통과 |
| 별도 bootRun 8080 + curl + fake | 아래 6회 실제 호출 확인. 실제 응답 본문 기록 |

fake 8080 검사는 실제 AI 생성 결과 검사가 아니다. 검사용 회원·기관·세션과 미사용 과거 월의 결과/보고서를 만들고 소유한 행만 정리했다. 앱 계정은 보고서를 읽기만 하고 테스트 fixture 저장은 pipeline/AI DB 계정으로 분리했다. 비밀번호는 로컬 설정에서 실행 환경으로만 읽었으며 소스/문서에 기록하지 않았다. AI 대상 URL은 테스트가 만든 loopback 서버로 고정했다. 테스트용 8080 서버는 검사 후 종료한다.

Git Bash에서 backend 폴더 기준 재현 명령:

```bash
./gradlew.bat test --console=plain
./gradlew.bat integrationTest --tests '*AnalysisIntegrationTests' --tests '*ReportHttpIntegrationTests' --tests '*AgentIntegrationTests' --tests '*AgentRecoveryIntegrationTests' --tests '*AgentHttpRecoveryIntegrationTests' --console=plain
# 공용 로컬 테스트 DB의 EUMI_TEST_PIPELINE_PASSWORD/EUMI_TEST_AI_PASSWORD를
# 안전한 실행 환경으로 준비한 경우에만 실행. 필요하면 DB_PASSWORD도 준비한다.
EUMI_REPORT_FIXTURES=true ./gradlew.bat integrationTest --tests '*ReportFakeIntegrationTests' --console=plain
```

8080은 비어 있어야 한다. fixture 검사는 현재 1단계 스키마에서 실행했다. backend/src의 코드·테스트·fixture에서 삭제 예정 칸/옛 reader 참조는 0건이며, 해당 테이블/뷰의 SELECT *도 없다. 2단계 실제 DB·실제 FastAPI/GMS 생성·브라우저/Tableau·운영 배포 검사는 수행하지 않았다. 선별 실행하면 integrationTest XML은 마지막 선택 클래스 결과로 바뀐다.

## 5. 남은 것 · MR 초안

- 김민재: `de4dc12` 위로 rebase한 `3f05963`에서 시작한 코드 후속 수정은 `65290d0`에 커밋됐다. `3f05963` 본문에도 이슈 키는 있었으나 `Jira:` 형식이 아니었고, `65290d0` 본문에는 `Jira: S15P31B201-237`이 기재돼 있다. 이번 문서 정정의 커밋·push·MR 갱신은 김민재가 진행한다. 에이전트는 git 쓰기를 실행하지 않았다.
- 인프라: 이 BE MR 병합 뒤 2단계 V 파일·새 칸 seed를 별도 제공. summary_lines 등 칸을 지우기 전에 v_region_insight를 재생성해야 한다. quick_insight·insight_generated_at 칸 이름과 result_updated_at=region_result.updated_at 일치 조건을 유지한다. BE의 예전 칸 의존성은 제거했다. 2단계 적용 DB에서의 검사는 해당 시점에 한다.
- 새 형식 seed가 들어오면 AnalysisIntegrationTests에 보고서가 있는 경로의 내용 비교를 보강한다. 현재 seed를 사용하는 검사는 옛 형식/null 경로를 확인하며, 새 칸의 정상 응답은 별도 ReportFakeIntegrationTests의 합성 보고서로 검사한다.
- INT-08 requestId에는 길이 상한이 없다. 계약이 필수 문자열만 정하므로 제한을 도입하려면 계약 합의가 먼저다. 이번에는 바꾸지 않는다.
- AI 담당 변경 전 실제 AI에 INT-04를 보내지 않는다. 현재 검사는 실제 모델 생성과 무관하며 http 모드 검사는 전부 테스트용 AI 서버를 사용했다.
- FE: API-12 quickInsight/graphs/generatedAt과 API-11 단일 summary를 사용한다. report=null 준비 중 안내와 시트 이름 그대로의 Tableau 연결을 확인한다.

MR 제목 제안: `feat: [BE] 인사이트 보고서 연결 (INT-04 · 05 · 08, API-11 · 12 새 형식)`.

코드 후속 커밋 완료: `65290d0` · `fix: [BE] AI-b 조회 계약과 호출 경계 검사 보완`.

추가 커밋도 본문 끝에 `Jira: S15P31B201-237`을 적는다. git 작업은 김민재가 진행한다.

아래는 저장소 MR 템플릿에 넣을 초안이다.

### Jira

S15P31B201-237

### 변경 내용

- AI-b INT-04(PIPELINE) 접수, INT-05 새 본문/202 접수/503 처리, INT-08(AI) 로그 전용 204 수신.
- API-11 퀵 인사이트 단일 요약, API-12 그래프 3칸 형식과 버전 일치·허용 시트 검사. 예전 SavedReportReader/summary_lines·JSON 보고서 읽기 제거.
- 바뀐 파일 목록과 DTO·환경변수·권한/잠금은 이 문서 1~3절. INT-04·08의 0000년 거절은 AI valid_month·ScreenContext 규칙대로 유지한다. 로그는 11/10 2차 지시의 4개 항목만 남긴다. INT-08 requestId 문자열 허용, 삭제 예정 칸을 쓰는 fixture와 SELECT * 제거.
- 리뷰 후속: API-11·12 month 패턴 복원과 0000-01의 404 검사, INT-05 호출 시 트랜잭션·DB 연결 미보유 회귀 검사, rebase 후 기준·검증·인프라 인계 기록 갱신.

### 확인 방법

1. 공용 로컬 DB를 준비하고 backend에서 `./gradlew.bat test --console=plain`.
2. `./gradlew.bat integrationTest --tests '*AnalysisIntegrationTests' --tests '*ReportHttpIntegrationTests' --tests '*AgentIntegrationTests' --tests '*AgentRecoveryIntegrationTests' --tests '*AgentHttpRecoveryIntegrationTests' --console=plain`: 실제 PostgreSQL/BE HTTP와 fake/mock/테스트용 AI 서버로 확인.
3. 테스트용 DB 계정 환경과 빈 8080을 준비한 뒤 `EUMI_REPORT_FIXTURES=true ./gradlew.bat integrationTest --tests '*ReportFakeIntegrationTests' --console=plain`: fake 접수·새 형식 저장 조회·권한 거절·미생성/옛 결과 버전/시트 오류 확인. 테스트가 소유한 fixture를 정리한다.
4. 이번 후속 결과: 단위/MVC/HTTP 대역 152개(10:37), 실제 DB/HTTP 5클래스 47개(10:38~10:39), 8080 fake fixture 4개(10:39) 통과. 클래스별 수와 시작 시각은 4절에 기록했다. 실제 AI는 호출하지 않았다. bootJar·별도 bootRun/curl은 이번에 재실행하지 않았고, 2단계 DB·브라우저 확인은 미실행이다.

#### 별도 bootRun · 8080 curl 실제 결과

2026-11-10 10:07 KST. 테스트용 임의 월이 아닌 공용 DB의 2025-12를 조회했다. Git Bash에서 bootRun으로 실행한 fake 서버에 curl로 호출했다. 내부 토큰은 사용자가 지정한 로컬 기본값을 실행 환경에서만 준비했고, 원문을 파일·보고에 넣지 않았다. 검사 후 이 작업이 띄운 서버만 종료했다.

재현은 로컬 토큰과 DB 환경을 준비한 뒤 backend에서 수행한다. 값은 아래 명령에 직접 적지 않는다.

```bash
EUMI_AI_MODE=fake ./gradlew bootRun
```

별도 Git Bash에서:

```bash
curl -i -X POST http://localhost:8080/api/internal/analysis/pipeline-completions \
  -H "Authorization: Bearer $EUMI_PIPELINE_TOKEN" -H 'Content-Type: application/json' -d '{"month":"2025-12"}'
# AI 토큰, 토큰 없음, month=2024-01로 각각 반복한다.
curl -i -X POST http://localhost:8080/api/internal/analysis/insight-report-completions \
  -H "Authorization: Bearer $EUMI_AI_TOKEN" -H 'Content-Type: application/json' \
  -d '{"requestId":"local-1","month":"2025-12","savedCount":0,"failedDongCodes":[]}'
```

| 호출 | 상태 코드 | 결과 |
|---|---|---|
| INT-04 PIPELINE, month=2025-12 | 202 | month=2025-12, targetCount=47 |
| INT-04 AI 토큰, 같은 월 | 403 | FORBIDDEN |
| INT-04 토큰 없음, 같은 월 | 401 | UNAUTHENTICATED |
| INT-04 PIPELINE, month=2024-01 | 404 | NOT_FOUND |
| INT-08 AI 토큰, requestId=local-1, savedCount=0, failedDongCodes=[] | 204 | 본문 없음 |
| 같은 INT-08 알림 재전송 | 204 | 본문 없음 |

실제 202 응답 본문:

```json
{"success":true,"data":{"month":"2025-12","targetCount":47},"meta":{"requestId":"8932767b-7488-4815-9e2a-e980a3c7b19c","timestamp":"2026-11-10T10:07:00.0363475+09:00"}}
```

실제 403 응답 본문:

```json
{"success":false,"error":{"code":"FORBIDDEN","message":"요청을 처리하지 못했습니다.","fieldErrors":[]},"meta":{"requestId":"e01c91e9-601b-4745-a7fb-757b26416957","timestamp":"2026-11-10T10:07:00.0655608+09:00"}}
```

실제 401 응답 본문:

```json
{"success":false,"error":{"code":"UNAUTHENTICATED","message":"로그인이 필요합니다.","fieldErrors":[]},"meta":{"requestId":"6a926b34-e9b1-488b-92ce-69ccae21f7bf","timestamp":"2026-11-10T10:07:00.0846109+09:00"}}
```

실제 404 응답 본문:

```json
{"success":false,"error":{"code":"NOT_FOUND","message":"요청을 처리하지 못했습니다.","fieldErrors":[]},"meta":{"requestId":"7a43acce-8440-44e2-ba59-51938a37a9fd","timestamp":"2026-11-10T10:07:00.144052+09:00"}}
```

각 JSON 응답의 X-Request-Id와 meta.requestId가 같았고, 내부 요청에서 Set-Cookie가 없음을 확인했다. 204는 두 호출 모두 빈 본문이었다.

### 리뷰

CONTRIBUTING.md 3.3 표의 리뷰어를 Reviewers에 지정한다.

- [ ] DB 마이그레이션 (`db/migration`)
- [x] 파트끼리 주고받는 API · 호출 형식 · DB로 주고받는 행 형식
- [ ] `infra/`, `Jenkinsfile`

### 체크리스트

- [ ] 대상 브랜치가 `develop`이다 (MR 생성 시 확인)
- [x] 로컬에서 실행 · 테스트해 보았다
- [x] `.env`, 비밀번호, API 키, 실제 개인정보가 포함되지 않았다
- [x] 커밋 본문에 Jira 키를 적었다 (코드 후속 커밋 65290d0의 Jira: S15P31B201-237 확인)
- [ ] DB를 바꿨다면: 병합된 V 파일은 그대로이고, 새 파일 이름/ERD 변경 기록에 반영했다 (해당 없음)
- [ ] 의존성을 바꿨다면 lock 파일도 함께 커밋했다 (해당 없음)
- [x] 기능명세서와 다르게 구현한 부분이 있다면 아래에 적었다

### 기능명세서와 다른 점 · 참고 사항

INT-04·08 month는 YYYY-MM만 적힌 보고서 계약보다 엄격하게 0000년을 VALIDATION_ERROR 400으로 거절하며, AI valid_month·ScreenContext와 같은 규칙을 유지한다. API-11·12는 계약 month 패턴으로 복원했다. 로그는 확정 문서의 저장 수/실패 동 기록 대신 11/10 2차 지시의 네 항목으로 제한했다. 2단계 V 파일·seed는 이 MR 병합 뒤 인프라 담당이 제공한다. fake는 생성 없이 접수만 하며, 긍정 보고서 조회는 테스트용 AI 계정 저장 fixture로 검증했다. 실제 AI/GMS 호출은 AI 수정 뒤 별도 진행한다. 코드 후속 수정은 65290d0에 반영됐다. 에이전트는 git 쓰기를 실행하지 않았다.
