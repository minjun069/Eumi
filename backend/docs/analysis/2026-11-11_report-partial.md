# API-12 일부 표시 · 검증과 MR 최종안

2026-11-11. 작업: AI-b 후속 / API-12, API-11 회귀 확인. 사용자가 준비한 브랜치 `feat/be-insight-report-partial`, 기준 `origin/develop d486af9`이며 git 명령은 실행하지 않았다.

사용자가 구현 커밋 `6d63d14`, 후속 커밋 `899c73a` 완료와 Claude Code의 초기·재리뷰 결과를 전달했다. 아래 최초 검증 기록은 커밋 전 구현 당시 결과이며, 리뷰 후속 변경과 재검사는 별도로 구분한다. 커밋 해시·본문·리뷰 결과는 사용자 전달 정보이며 에이전트는 git 조회·수정을 하지 않았다.

기준은 OpenAPI 2.6.0, `docs/api/insight-report.md` 4·8절, `docs/decisions/internal-integration.md` 14번, V20261111_01이다. 계약과 달라진 점은 없다.

- `AnalysisService.report`: 세 칸을 원래 칸 순서로 확인하고 빈 칸은 조용히 제외한다. 허용 밖 시트는 그 그래프만 제외하고 requestId·month·원래 slot(1~3)만 WARN에 남긴다. 퀵 인사이트와 남은 그래프가 모두 없을 때만 report=null이다.
- `AnalysisRepository.report`는 기존 세 칸 반환을 유지한다. DTO·오류 코드·Jackson 설정·API-11 구현은 바꾸지 않았다. quickInsight와 description의 null 키를 유지한다.
- `AnalysisServiceTests`, `ReportFakeIntegrationTests`에 일부 저장·null·허용 밖 시트·빈 보고서/설명 CHECK 검사를 추가했다. `AnalysisIntegrationTests`의 기존 저장 보고서 존재 조건을 일부 표시 계약에 맞췄다.
- 권한·잠금: 기존 세션 인증·최신 활성 회원·임시 비밀번호 제한을 유지한다. 일반 로그인 회원은 관할 밖 지역도 조회할 수 있다. 읽기 전용 트랜잭션이며 추가 행 잠금·쓰기·AI 생성은 없다.
- INT-04·05·08, savedCount의 로그 전용 처리, `docs/`, `db/migration/`, `frontend/`, `ai/`, AGENTS.md는 수정하지 않았다. 실제 DB의 테스트 데이터는 테스트가 생성한 회원·기관·세션과 미사용 과거 월의 소유 행만 정리한다.

## 검증 기록

- JDK 21.0.11, Gradle Wrapper 9.8.2.
- `./gradlew.bat test --console=plain`: 28클래스 206개 통과, 실패·오류·생략 0. AnalysisServiceTests 20개 포함. DB 없는 단위·mock·MVC·설정·HTTP 대역 검사다.
- 전체 `integrationTest`: 23클래스 337개 중 207개 통과·128개 실패·2개 생략. PostgreSQL 연결 한도(`53300`, remaining connection slots)로 6클래스 127개가 ApplicationContext 초기화에 실패했다. 별도로 `AgentRecoveryIntegrationTests.recentProgressIsNotRestarted` 1개가 Mockito NeverWantedButInvoked로 실패했다. 관련 없는 복구 코드는 수정하지 않았다. 실제 AI 검사 2개는 의도적으로 생략했다.
- 분석·보고서 실제 DB/HTTP 클래스별 재실행: 3클래스 37개 통과, 실패·오류·생략 0. 아래 시각은 2026-11-11 KST의 XML suite 시작 시각이다.

| 클래스 | 시작 시각 | 결과 | 실제 사용한 경계 |
|---|---|---|---|
| AnalysisServiceTests | 16:48:33 | 20개 통과 (전체 test에 포함) | Repository/Auth mock, DB 없음 |
| AnalysisIntegrationTests | 16:53:04 | 18개 통과 | 실제 PostgreSQL·A1 로그인·세션·BE HTTP |
| ReportFakeIntegrationTests | 16:53:19 | 10개 통과 | 실제 PostgreSQL·eumi_pipeline/eumi_ai 저장·8080, AI는 fake |
| ReportHttpIntegrationTests | 16:53:33 | 9개 통과 | 실제 PostgreSQL·BE HTTP·INT-05 loopback AI 대역 |

ReportFakeIntegrationTests는 eumi_ai 계정으로 graph_2·desc_2·desc_3=NULL인 행을 실제 저장했다. API-12의 두 그래프 순서와 두 번째 description:null 키, report의 세 필드 propertyNames, quick_insight=NULL인 최신 행의 API-11 insight:null/API-12 quickInsight:null을 확인했다. 퀵 인사이트만 있는 보고서는 graphs:[], 허용 밖 시트만 있으면 report:null이었다. 허용 밖 시트의 경고는 원래 칸 번호·requestId·month만 포함하며 퀵 인사이트·설명·EmbedDetailV09가 출력에 없었다. 빈 보고서와 그래프 없는 설명은 각각 SQLSTATE 23514로 거절됐다. 기존 옛 보고서·404·401/403도 통과했다.

클래스별 재실행은 integrationTest XML을 마지막 클래스 결과로 덮어쓰므로, 소스에 넣지 않는 build 산출물로 단위 전체(`report-partial-unit-summary.json`), 통합 전체(`report-partial-full-integration-summary.json`), 통합 분리 실행(`report-partial-focused-integration-summary.json`)의 수·시각을 구분해 보존했다. 최초 검사 종료 당시 마지막 XML은 ReportHttpIntegrationTests 9개 결과였다. 수정 파일의 줄 끝 공백 검사도 통과했다.

`test`는 build.gradle에서 local-integration 태그를 제외하므로 실제 DB 검사는 `integrationTest`로 따로 실행한다. 테스트용 DB 계정 값은 로컬 설정에서 실행 환경으로만 읽고 파일·로그에 복사하지 않는다. 실제 AI/GMS 호출은 비활성화한다. Docker Compose·Flyway는 실행하지 않는다.

## 리뷰 후속

- Claude Code는 계약 위반·회귀·병합 차단 사항 없음으로 판단했다. 리뷰어는 diff·계약·코드를 읽었고 테스트는 직접 실행하지 않았다.
- 낮음(로그 검사 누락): 기존 graph_1=NULL/graph_2=V09 테스트를 칸 2·3 매개변수 검사로 보강했다. 앞 칸이 비어 있어도 경고가 정확히 한 줄이고 원래 slot=2/3·requestId·month를 담으며, 출력에 EmbedDetailV09가 없는지 확인한다. 기존 칸 1 경고 검사도 유지한다. 운영 코드는 변경하지 않았다.
- 사소(인계): Jira를 `Jira: S15P31B201-237`로 확정하고 README의 11/11 기록을 날짜 순서와 기존 링크 형식에 맞췄다. 최초 지시는 AI-b 바로 아래 배치였으나 후속 리뷰 지적에 따라 11/11 기록으로 이동했다.
- 사용자 전달 재리뷰에 따르면 구현 커밋 `6d63d14`와 후속 커밋 `899c73a`의 본문은 모두 `S15P31B201-237`이며 `Jira:` 접두어가 없다. 두 커밋 모두 접두어가 없다는 사실로 이 기록을 정정했다. 기존 커밋 재작성 또는 squash 메시지에서의 보완 여부는 김민재가 결정한다. MR 설명과 이후 커밋 메시지에는 `Jira: S15P31B201-237`을 사용한다.
- 재리뷰(`899c73a`): 칸 2·3 로그 검사와 README 지적은 해소됐고 새로운 기능상 발견 사항은 없다. Jira 표기는 문서에서만 해소됐으며 커밋 메시지 규칙 미준수는 사소한 잔여 사항이다. 모든 후속 지적이 해소됐다고 기록하지 않는다. 리뷰어는 이번에도 파일을 수정하거나 테스트를 실행하지 않았다.
- 재검사: 아래 두 클래스를 실제 PostgreSQL·BE HTTP로 하나씩 실행했고 모두 통과했다. 시각은 2026-11-11 KST의 XML suite 시작 시각이다. 실제 AI/GMS는 호출하지 않았다.

| 클래스 | 시작 시각 | 결과 | 확인 범위 |
|---|---|---|---|
| ReportFakeIntegrationTests | 17:05:55 | 11개 통과, 실패·오류·생략 0 | 실제 DB·8080, 기존 10개 범위와 칸 2·3 원래 번호·시트 값 미노출 |
| AgentRecoveryIntegrationTests | 17:06:09 | 9개 통과, 실패·오류·생략 0 | 실제 DB·인증·BE HTTP, AI 장애만 mock. recentProgressIsNotRestarted 포함 |

후속 결과는 `build/report-partial-review-follow-up-summary.json`에 보존했다. 현재 마지막 integrationTest XML은 AgentRecoveryIntegrationTests 9개 결과다. 단독 실행 통과는 앞선 전체 실행 실패를 없애거나 30ms 시간 의존성이 해결됐다는 뜻은 아니다. 단위 206개·AnalysisIntegrationTests 18개·ReportHttpIntegrationTests 9개와 전체 integrationTest는 이번 후속에서 다시 실행하지 않았으며 위 최초 결과와 구분한다.

- 별도 테스트 안정성 이슈: 리뷰어는 서로 다른 Spring 컨텍스트의 Hikari 기본 풀 연결 누적을 연결 한도 원인으로 판단했다. DB now()와 JVM 시계 및 30ms 기준의 영향이 AgentRecovery 실패 원인이라는 판단은 리뷰어의 추정이며 원인을 확정하지 않았다. 이번 후속에서 풀·캐시 설정이나 AI 복구 코드는 바꾸지 않았다. AgentRecovery 단독 실행 통과와 전체 실행에서의 재현 여부는 구분한다.
- 배포 인계: 현재 FE의 `description.trim()`은 null 설명을 처리하지 못한다는 리뷰 결과가 있다. 계약 8절대로 BE·FE를 함께 배포하고, AI의 일부 저장은 그 배포 뒤에만 실행한다. FE는 이번 작업에서 수정하지 않는다.

## MR 제목

`fix: [BE] 인사이트 보고서 일부 표시 (API-12 openapi 2.6.0)`

브랜치: `feat/be-insight-report-partial` → `develop`. 아래는 프로젝트 `.gitlab/merge_request_templates/Default.md`에 맞춘 최종 MR 설명이다. GitLab 게시·대상 브랜치 설정은 사용자가 진행한다.

## Jira

Jira: S15P31B201-237

## 변경 내용

- 작업 ID: AI-b 후속 / API-12 일부 표시, API-11 회귀 확인. 일부 칸이 NULL이면 보고서 전체를 숨기던 동작을 OpenAPI 2.6.0·V20261111_01에 맞춰 찬 칸만 표시하도록 수정했다.
- graph_1→2→3 순서로 빈 칸을 건너뛰고 허용 밖 시트만 제외한다. graphs는 0~3개이며 quickInsight·description은 null이어도 JSON 키를 유지한다. 퀵 인사이트와 남은 그래프가 모두 없을 때만 report:null이다.
- 허용 밖 시트는 `Saved report graph skipped: unsupported sheet requestId={} month={} slot={}`로 경고한다. 원래 칸 번호(1~3)를 유지하며 시트 값·설명·퀵 인사이트 본문은 남기지 않는다.
- 결과 행 없음 404, 최신 보고서 없음·옛 보고서 null과 API-11 quick_insight=NULL → insight:null을 유지한다. Repository·DTO·오류 코드·Jackson 설정·INT-04·05·08은 변경하지 않았다.
- 권한·잠금: 기존 활성 회원·임시 비밀번호 제한을 유지한다. 일반 로그인 회원은 관할 밖 지역도 조회할 수 있다. 읽기 전용 트랜잭션이며 추가 잠금·DB 쓰기·AI 생성은 없다.
- 일부 행·null 키·칸 순서·칸 1/2/3 경고·DB CHECK·인증/404 회귀 검사를 보강하고 README·검증 기록을 정리했다. docs/·마이그레이션·FE·AI는 수정하지 않았다.

## 확인 방법

JDK 21, V20261111_01 적용 로컬 PostgreSQL·Mailpit과 빈 8080을 준비한다. 실행 환경에 EUMI_AI_MODE=fake, EUMI_VERIFY_LIVE_AI=false, EUMI_REPORT_FIXTURES=true 및 DB_PASSWORD·EUMI_TEST_PIPELINE_PASSWORD·EUMI_TEST_AI_PASSWORD를 안전하게 전달한다. 비밀값은 파일·로그에 남기지 않는다.

backend에서 다음 명령을 하나씩 실행한다. test는 local-integration 태그를 제외하므로 실제 DB 검사는 integrationTest로 구분한다.

```bash
./gradlew.bat test --console=plain
./gradlew.bat integrationTest --tests '*AnalysisIntegrationTests' --console=plain
./gradlew.bat integrationTest --tests '*ReportFakeIntegrationTests' --console=plain
./gradlew.bat integrationTest --tests '*ReportHttpIntegrationTests' --console=plain
./gradlew.bat integrationTest --tests '*AgentRecoveryIntegrationTests' --console=plain
```

| 검사 | 최초 결과 | 리뷰 후속 결과 | 사용한 경계 |
|---|---|---|---|
| 전체 test | 28클래스 206개 통과 (AnalysisServiceTests 20개 포함) | 재실행 안 함 | DB 없는 단위·mock·MVC·설정·HTTP 대역 |
| AnalysisIntegrationTests | 18개 통과 | 재실행 안 함 | 실제 PostgreSQL·로그인·BE HTTP |
| ReportFakeIntegrationTests | 10개 통과 | 칸 2·3 보강 후 11개 통과 | 실제 PostgreSQL·pipeline/AI 계정 저장·8080, AI는 fake |
| ReportHttpIntegrationTests | 9개 통과 | 재실행 안 함 | 실제 PostgreSQL·BE HTTP·loopback AI 대역 |
| AgentRecoveryIntegrationTests 단독 | 미실행 | 9개 통과 | 실제 PostgreSQL·BE HTTP, AI 장애만 mock |

위 통과한 실행은 모두 실패·오류·생략 0이다. 최초 관련 실제 DB/HTTP 37개 통과와 후속 ReportFake 11개·AgentRecovery 9개 통과를 구분한다.

- eumi_ai로 일부 행을 실제 저장해 그래프 두 개의 칸 순서·description:null 키·report 세 필드 propertyNames를 확인했다. quick_insight=NULL의 API-11 insight:null/API-12 quickInsight:null, 퀵 인사이트만 있을 때 graphs:[], 허용 밖 시트만 있을 때 report:null도 확인했다.
- 칸 1/2/3 경고의 원래 번호·한 줄·requestId·month와 시트 값/본문 미노출, 빈 보고서·그래프 없는 설명의 SQLSTATE 23514, 옛 보고서·404·401/403이 통과했다.
- 전체 integrationTest는 337개 중 207개 통과·128개 실패·2개 생략으로 실패했다. 127개는 PostgreSQL 연결 한도(53300)에 따른 컨텍스트 초기화 실패, 1개는 AgentRecovery의 recentProgressIsNotRestarted에서 NeverWantedButInvoked였다. 생략 2개는 실제 AI 검사다. 이후 관련 클래스를 분리 실행했고, AgentRecovery도 단독 9개가 통과했다. 후속 전체 실행은 하지 않았으며 단독 통과를 시간 의존성 해결로 판단하지 않는다.
- 실제 AI/GMS 생성·브라우저/Tableau·운영 배포·별도 bootRun/curl·bootJar는 미실행이다. Claude Code 리뷰어도 테스트를 직접 실행하지 않았다.

## 리뷰

리뷰어: Claude Code. 초기 6d63d14 리뷰에서 계약 위반·회귀·병합 차단 사항 없음으로 판단했다. 899c73a 재리뷰에서 칸 2·3 로그 검사와 README 지적 해소, 추가 기능상 발견 사항 없음을 확인했다. 사소한 잔여 사항은 두 커밋 본문의 Jira: 접두어 누락이다. 문서는 실제 상태로 정정했다. 리뷰 결과는 사용자 전달 내용이며 GitLab 승인 상태는 별도 확인하지 않았다.

승인 필수: 해당 없음. 계약 변경은 문서·DB MR d486af9에서 승인됐고 이 MR은 승인된 계약의 구현만 반영한다.

- [ ] DB 마이그레이션 (`db/migration`)
- [ ] 파트끼리 주고받는 API · 호출 형식 · DB로 주고받는 행 형식(ai_message · 보고서)
- [ ] `infra/`, `Jenkinsfile`

## 체크리스트

- [ ] 대상 브랜치가 `develop`이다 (MR 생성 시 확인)
- [x] 로컬에서 실행 · 테스트해 보았다 (위 통과/실패 결과 참고)
- [x] `.env`, 비밀번호, API 키, 실제 개인정보가 포함되지 않았다
- [ ] 커밋 본문에 Jira 키를 적었다 (6d63d14·899c73a 모두 키는 있으나 Jira: 접두어 없음. 팀 규칙 미준수 잔여)
- [ ] DB를 바꿨다면: 병합된 V 파일은 그대로이고, 새 파일 이름/ERD 기록에 반영했다 (해당 없음)
- [ ] 의존성을 바꿨다면 lock 파일도 함께 커밋했다 (해당 없음)
- [x] 기능명세서와 다르게 구현한 부분이 있다면 아래에 적었다

## 기능명세서와 다른 점 · 참고 사항

기능명세서와 다른 점: 없음. OpenAPI 2.6.0·V20261111_01을 따른다.

- 커밋 메시지: 사용자 전달 재리뷰에 따르면 6d63d14·899c73a 모두 본문이 S15P31B201-237이며 Jira: 접두어가 없다. 커밋 재작성 또는 squash 시 Jira: S15P31B201-237을 넣을지는 김민재가 결정한다. 에이전트는 git 명령을 실행하지 않았다.
- 별도 과제: 전체 통합의 DB 연결 한도와 AgentRecovery의 시간 의존성 가능성. 풀·캐시 설정·AI 복구 코드는 이 MR에서 바꾸지 않았다.
- 배포: BE 병합 뒤 FE 일부 표시를 연결하고 BE·FE를 한 배포로 내보낸다. 현재 FE의 null 설명 처리 보완이 필요하므로 AI 일부 저장은 해당 배포 뒤에만 실행한다.
