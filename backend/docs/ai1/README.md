# AI1 AI 패널 구현·검증·MR 인계

2026-11-03 최신 지시: 사용자가 테이블 정의서의 실제 수집 항목을 기준으로 불필요한 마스킹 삭제를 요청했다. 현재 범위·삭제 내역·검사·계약 수정 인계는 [마스킹 범위 축소](2026-11-03_masking-scope.md)를 먼저 읽는다. 이전 회귀 수정(110/39)은 [개인정보 회귀 수정](2026-11-03_privacy-regression-follow-up.md), 질문 보존·진단 보완(82/37)은 [질문 보존 후속](2026-11-03_masking-follow-up.md), 1차 보완(67/36)은 [리뷰 후속](2026-11-03_review-follow-up.md)에 있다. 아래 최초 구현과 당시 검사 수치는 역사적 기록이다.

기준일: 2026-11-03. 작업 브랜치 `feat/be-agent`, 시작 커밋 `095618e`. Jira: `S15P31B201-214`.

기준은 현재 저장소의 OpenAPI 2.3.0, `docs/api/ai-agent-panel.md`, `V20261102_02__ai_message.sql`이다. SSE·구 `/agent/runs` 계약을 적용하지 않았다. Git 쓰기 명령·브랜치 변경·Docker Compose·마이그레이션·FE·AI 코드 변경은 수행하지 않았다.

## 1. 작업 ID·API ID

| API | 구현 |
|---|---|
| API-03 `POST /api/agent/questions` | 대화·마스킹 질문 저장 후 AI 실행 요청, 202 |
| API-03-S1 `GET /api/agent/conversations/{id}/messages?after=` | messageId 커서 조회·무응답 복구, 200 |
| API-03-S2 `POST /api/agent/conversations/{id}/cancel` | 취소 요청·응답 누락 시 BE 취소 행, 204 |

`AgentClient`와 Fake·HTTP 구현, 질문 마스킹, DB append writer, JPA validate용 읽기 전용 매핑, 실제 DB·HTTP 검사를 추가했다. 대화 목록·상세·삭제 API-36~38은 AI2 범위다.

## 2. 계약·DTO·오류 코드

요청·응답 형식 변경 없음. 마스킹 동작 범위는 사용자 지시로 축소했으며 docs/api의 포괄적 설명은 [최신 인계](2026-11-03_masking-scope.md)에 따라 계약 담당자가 정리해야 한다.

- `AgentDtos.QuestionRequest`: 필수 `conversationId`(첫 질문이면 null), `question`(trim 후 1~4000 코드 포인트). 계약에서 제거된 screen 등 미정의 필드를 거절한다. 요청 toString은 원문을 숨긴다.
- `QuestionCreated`: `conversationId`, `questionId`.
- `Message`: `messageId`, `questionId`, `role`, `status`, `content`, `details`, `artifacts`, `createdAt`. nullable 필드도 포함한다.
- `Messages`: 메시지 배열. after 기본 0, 범위 0~9007199254740991, messageId 오름차순이며 새 행이 없으면 빈 배열이다.
- `RUN_ALREADY_ACTIVE` 409 추가. 메시지는 현재 OpenAPI 예제와 같은 `요청을 처리하지 못했습니다.`다.
- 일반 성공은 ApiResponse.of(), 업무 오류는 ApiException(ErrorCode), 취소 성공은 본문 없는 204다.

질문은 저장 전에 이메일·회원 API의 하이픈형 휴대전화, 명시 표지의 이름·생년월일만 가린다. 이름 표지는 `이름`·`성명`·`성함`·`사례자명`·`회원명`, 생년월일 표지는 `생년월일`이다. 값은 세미콜론·줄바꿈·입력 끝까지 가리고, 구분자 밖의 질문을 보존한다. 주민번호·금융번호·상세주소·자연어 추론은 제거했다. 처리 결과만 DB에 저장하며 지원 범위 밖의 내용은 남을 수 있다. 질문 본문은 로그하지 않고 HTTP AI 요청에는 conversationId·questionId만 보낸다. AI는 DB의 처리 결과를 읽는다.

## 3. 권한·트랜잭션·잠금

- A1의 실제 세션 principal을 사용하고, 서비스에서 최신 활성 회원·임시 암호 상태를 다시 검사한다. 제한 세션은 PASSWORD_CHANGE_REQUIRED 403이다.
- 본인 대화만 조회·질문·취소할 수 있다. 다른 회원·기관의 대화와 만료·없는 대화는 404다.
- 첫 질문은 대화 INSERT와 질문 INSERT를 한 트랜잭션으로 커밋한다. 이어서 질문은 대화 행 FOR UPDATE 아래 끝 행 없는 질문을 확인하고 있으면 409다.
- AI start·status·cancel 호출은 DB 트랜잭션 밖에서 실행한다. start 전에 질문 커밋이 끝났음을 실제 검사한다.
- 메시지는 INSERT만 한다. AiConversation·AiMessage는 Hibernate Immutable 매핑이며 ddl-auto=validate를 통과한다. last_message_at·delete_scheduled_at은 DB 기본값·트리거만 갱신한다.
- Fake·BE 보완 행은 별도 REQUIRES_NEW 트랜잭션으로 행마다 커밋한다. 후속 보완에서는 KEY SHARE 대화 잠금으로 종료 여부를 재확인하며, 이미 끝난 질문의 23505·40P01 처리와 제한된 재시도를 적용한다. 다른 정합성 오류는 숨기지 않는다.
- AI 호출의 동시 start·cancel·복구는 프로세스 안의 고정 개수 잠금으로 직렬화한다. 질문별 복구 재요청은 한 BE 프로세스에서 한 번이다. 프로세스 재시작 시 재요청 표시가 초기화되며 질문 시각 기반 절대 실행 제한은 유지된다.
- 취소 타이머는 요청 당시 questionId만 대상으로 한다. 완료가 먼저 저장되면 완료가 유지되고 새 질문에 이전 취소가 적용되지 않는다.

### 실행 모드·시간 값

사용자는 Jira 키를 확정했고 BE 여유는 1~2초 정도라고 전달했다. AI 실행 제한은 아직 공유받지 않았으며 무응답 판정·취소 대기 값도 미확정이다. 아래 기본값은 Fake 개발 검증용이며 AI 담당 합의값으로 간주하지 않는다.

| 설정 | 환경변수 | Fake 기본 | HTTP 모드 |
|---|---|---|---|
| eumi.ai.mode | EUMI_AI_MODE | local은 fake, prod는 명시 필수 | http 지정 |
| eumi.ai.base-url | AI_BASE_URL | http://localhost:8000 | 내부 AI 주소 |
| eumi.ai.execution-limit | EUMI_AI_EXECUTION_LIMIT | 60s, 개발용 | 명시 필수 |
| eumi.ai.grace-period | EUMI_AI_GRACE_PERIOD | 2s, 사용자 범위 내 | 명시 필수 |
| eumi.ai.unresponsive-after | EUMI_AI_UNRESPONSIVE_AFTER | 5s, 개발용 | 명시 필수 |
| eumi.ai.cancel-wait | EUMI_AI_CANCEL_WAIT | 2s, 개발용 | 명시 필수 |
| eumi.ai.fake-step-delay | EUMI_AI_FAKE_STEP_DELAY | 1s | 사용하지 않음 |
| eumi.ai.http-timeout | EUMI_AI_HTTP_TIMEOUT | 3s | 연결·전체 응답 제한 |

모든 시간은 양수다. HTTP 모드는 네 업무 시간 값 중 하나라도 명시하지 않으면 기동 실패한다. 내부 HTTP는 응답 헤더뿐 아니라 본문 수신까지 시간 제한을 적용하고 본문·예외 원문은 오류에 노출하지 않는다.

prod는 `EUMI_AI_MODE` 자체도 필수다. 시연은 fake를 명시하고, 실제 AI 전환 시 http로 변경한다. 운영 Compose 변수 전달은 별도 인프라 변경이 필요하며 [후속 인계](2026-11-03_review-follow-up.md)에 정확한 항목을 적었다.

Fake는 질문 이해 → 자료 확인 → 답변 정리를 1초 간격으로 커밋한 뒤 연결 확인용 완료 답변을 저장한다. 실제 분석 답변을 생성했다고 표시하지 않는다. HttpAgentClient는 INT-01·02·03을 구현하며 같은 질문이 이미 실행 중인 409는 상태를 확인해 중복 시작으로 처리한다.

무응답 조회는 상태 확인 후 실행 중이 아니면 한 번 재요청한다. 상태 조회 장애만으로 바로 실패시키지 않고 질문 시각 + 실행 제한 + BE 여유가 지나면 실패 행을 쓴다. 취소 응답이 없으면 취소 대기 후 BE가 취소 행을 쓰며, DB 장애가 있었다면 후속 조회에서 취소를 다시 마무리한다.

## 4. 실행한 검사·결과

JDK 21.0.11·Gradle 9.8.2, 실제 PostgreSQL 17.11·Mailpit을 사용했다.

실행 명령: `gradlew.bat test integrationTest bootJar --console=plain`.

| 구분 | 결과 |
|---|---|
| DB 없는 단위·MVC·설정 및 로컬 HTTP stub | 전체 49개 통과, 실패·오류·생략 0 |
| 실제 PostgreSQL·HTTP·Mailpit 통합 | 전체 30개 통과, 실패·오류·생략 0 |
| bootJar | 통과 |
| 실제 8080 Fake 흐름 | 로그인 → 질문 202 → 진행 3행 → 완료, after 조회 중복 없음 |
| 실제 8080 취소 | 질문 → 취소 204 → 취소 행 → 재취소 204 |

AI1 신규 검사는 단위 13개·실제 DB 통합 13개다.

- 설정: Fake 기본·HTTP 시간 값 4개 필수·0/음수 거절, 명시적 식별자 마스킹.
- 내부 HTTP stub: INT-01·02·03 경로·본문, 같은 질문 중복 접수, 장애·잘못된 상태, 헤더 수신 후 본문 지연 시간 제한. FastAPI 실연결이 아니다.
- AgentIntegrationTests 5개: 실제 A1 로그인·Fake AI·DB·HTTP로 정상 진행·완료·이어서 질문·커서, JPA 매핑·트리거 보관일, 늦은 행 23505, 취소·소유권·만료·제한 세션·필수 입력·Unicode·미정의 screen·커서 검증.
- AgentRecoveryIntegrationTests 8개: 실제 DB·A1 로그인·HTTP를 사용하고 AI 통신만 mock으로 대체한다. 커밋 뒤 start·즉시 실패·한 번 재요청·실행 중 재요청 없음·절대 시간 초과·취소 호출 실패·취소 응답 없음·동시 질문 202/409·JSONB artifacts 보존을 확인한다.
- 실제 8080 확인에서 만든 대화 2개는 해당 회원·UUID 조건으로만 삭제했고 세션도 로그아웃했다. 통합 검사는 자신이 만든 회원·기관·대화·세션만 정리한다. 공용 시퀀스를 되돌리지 않았다.

## 5. 남은 것·리뷰·인계

- 8080은 이 작업 폴더의 이전 A1 프로세스만 확인 후 종료하고 최신 AI1 코드의 Fake 모드로 재실행해 두었다.
- AI 담당이 실제 실행 제한·무응답 판정·취소 대기를 정하면 네 업무 시간 값과 내부 AI 주소를 주입해 HTTP 모드로 전환한다. 현재 FastAPI 실연결·운영 배포 결과는 없다.
- artifacts는 JSON 형태를 그대로 전달한다. 형태 합의 전 FE는 해석하지 않는다.
- FE 브라우저·Nginx·운영 HTTPS·부하·장시간 장애·프로세스 재시작 실험은 수행하지 않았다. 로그인·질문 요청 제한 세부는 후속 범위다.
- 마이페이지 API-36~38·만료 대화 배치·탈퇴와 AI 실행 정리는 이후 페이지 작업과 연결한다.
- AI1은 병합 전 Claude Code 리뷰가 필수다. DB 잠금과 AI 호출 분리, 끝 행 경합, 질문별 재요청·취소 범위, 마스킹 범위와 네 시간 값의 미확정 상태를 우선 점검한다.

커밋 제목 제안: `feat: [AI1] 질문 조회 취소 API와 Fake AI 연동 구현`

MR 제목 제안: `feat: [AI1] AI 패널 질문·조회·취소와 복구 구현`

Jira: S15P31B201-214
