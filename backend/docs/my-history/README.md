# AI2 마이페이지 AI 대화 기록 구현·검증·MR 인계

2026-11-04. 사용자가 FE와 이름을 맞춰 만든 `feat/be-my-history`에서 API-36~38을 구현했다. 기존 계획의 브랜치 이름 `feat/be-conversations`를 대체한다. 시작 커밋은 `66a7282`(마이페이지 BE·FE 병합 이후 develop)다. 구현·검사를 완료했고 commit·push·MR·병합은 사용자가 진행한다.

## 1. 작업 ID·API ID

- AI2: API-36 `GET /api/members/me/conversations`, API-37 `GET /api/members/me/conversations/{conversationId}`, API-38 `DELETE /api/members/me/conversations/{conversationId}`.
- Jira: S15P31B201-229 `[BE] AI 대화 기록 확인`. 관련 FE 이슈는 S15P31B201-230이다. Jira 제목·상태를 읽기만 했으며 등록·수정·상태 변경은 하지 않았다.
- 기준: 이 폴더의 OpenAPI 2.3.0, AI 패널 A 방식 문서, V20261102_02의 ai_message·v_conversation_summary, 기존 AgentRepository·AgentLifecycle·AgentMessageWriter. V4와 외부 문서에 남은 ai_conversation_turn은 V20261102_02로 대체된 과거 구조다.
- 구현: `history/ConversationHistoryController`, `ConversationHistoryService`, `ConversationHistoryRepository`, `ConversationHistoryDtos`. 기존 AI1 코드와 ErrorCode·SecurityConfig는 변경하지 않았다.

## 2. 계약과 달라진 점·DTO·오류

계약과 달라진 점: 없음. 프론트와 맞춘 작업 브랜치 이름만 최초 계획에서 달라졌다. 의존성·DB 마이그레이션·seed·frontend·infra·docs/api 변경은 없다.

| API | 정상 응답과 동작 |
|---|---|
| API-36 | 200 `data={totalCount,page,size,totalPages,items}`. 항목은 conversationId·firstQuestion·questionCount·lastMessageAt·deleteScheduledAt 5개 필드 |
| API-37 | 200 `data={conversationId,firstQuestion,lastMessageAt,deleteScheduledAt,messages}`. messages는 AgentMessage 8개 필드의 전체 배열 |
| API-38 | 204, 본문 없음. 대화 물리 삭제와 ai_message CASCADE |

- 목록은 `v_conversation_summary WHERE member_id=본인`을 사용한다. 뷰가 `delete_scheduled_at > current_date`인 보관 중 대화만 남긴다. 정렬은 last_message_at desc → conversation_id asc다.
- page 기본 1, 안전 정수 상한 9007199254740991, size 기본 10·최대 100. 마지막 페이지 초과는 마지막 페이지로 보정하며 빈 결과는 totalPages=0·page=1·items=[]다.
- firstQuestion은 이미 저장된 첫 질문을 그대로 반환한다. 질문 수는 완료뿐 아니라 실패·취소 질문도 포함한다. 추가 마스킹이나 질문 원문 복원은 하지 않는다. 기존 마스킹의 지원 범위 밖 정보가 남을 수 있다는 계약도 유지한다.
- 상세는 뷰에서 본인·보관 기간을 확인한 뒤 `AgentRepository.messages(id,0)`의 기존 매핑을 그대로 사용한다. 질문·진행·완료·실패·취소를 messageId 오름차순으로 전부 반환하고 nullable 필드·artifacts를 유지한다. GET은 AI 복구·재실행을 요청하지 않는다.
- 없는 대화·타인 대화·보관 기간이 지난 대화는 상세와 삭제 모두 404 NOT_FOUND다. 삭제도 기존 AI1 소유권·보관 기간 확인을 재사용해 프로토타입의 보관 중 대화 처리와 맞춘다.
- 새 오류 코드는 없다. 잘못된 UUID·page·size는 400 VALIDATION_ERROR다. 정상·오류의 requestId와 Cache-Control: no-store, DELETE의 빈 본문을 유지한다.
- 질문이 없는 비정상 저장 대화는 필수 firstQuestion·최소 questionCount를 임의로 채우지 않고 대화 ID만 로그에 남겨 500으로 처리한다. 정상 질문 생성은 기존 AI1에서 대화·첫 질문을 같은 트랜잭션으로 저장한다.

## 3. 권한·잠금·취소·삭제

- 회원 ID는 SessionPrincipal에서 얻고 최신 회원을 DB에서 확인한다. 비인증·탈퇴·만료 임시 비밀번호는 401, 유효 임시 비밀번호 제한 상태는 403 PASSWORD_CHANGE_REQUIRED다. 같은 기관의 다른 회원 대화도 조회·삭제할 수 없다.
- 목록·상세는 쓰기 잠금 없이 읽는다. REPEATABLE_READ의 읽기 전용 트랜잭션으로 목록 count/항목과 상세 메타데이터/메시지를 각각 같은 스냅샷에서 읽는다.
- 삭제 순서: 최신 회원 확인 → 본인·보관 기간 확인 → DB 트랜잭션 밖에서 기존 AgentLifecycle.cancel 호출 → 별도 삭제 트랜잭션에서 최신 회원·소유권·보관 기간 재확인 및 대화 FOR UPDATE → DELETE → 메시지 CASCADE.
- AgentLifecycle이 끝 행 없는 질문을 확인하고 AgentClient에 취소를 요청한다. 이미 끝난 대화는 취소 요청 없이 삭제한다. Fake의 취소도 독립 트랜잭션에서 끝 행을 쓰므로 삭제 잠금을 얻은 채 취소를 기다리지 않는다.
- 취소 요청이 Unavailable이면 기존 AI1의 대체 취소 기록 경로를 사용한 뒤 삭제한다. 이 동작을 새로 정의하거나 AI 시간 값을 바꾸지 않았다. AI와 DB 삭제 사이의 외부 호출까지 단일 트랜잭션으로 묶지 않는다.
- 삭제 후 늦은 쓰기는 기존 AgentMessageWriter의 쓰기 가능 여부 확인·FK 오류 처리에 맡긴다. 실제 검사에서는 삭제 후 append=false와 대화·메시지 0건을 확인했다. 새로운 대화를 재생성하는 코드는 없다.
- 프로필 수정·비밀번호 변경·세션 폐기 기능은 이번 범위가 아니다. 비밀번호 변경은 다음 단계에서 별도 MR로 진행한다.

## 4. 실행한 검사와 결과

JDK 21.0.11, Git Bash, 공용 PostgreSQL localhost:5432(eumi_app, Asia/Seoul)과 기존 Mailpit을 사용했다. 에이전트는 Docker Compose·Flyway·Git 쓰기 명령을 실행하지 않았다.

```bash
cd /c/Users/SSAFY/Desktop/PJT3/S15P31B201/backend
export JAVA_HOME='C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot'
./gradlew.bat test integrationTest bootJar --console=plain
```

2026-11-04 16:07~16:08 KST 실행, BUILD SUCCESSFUL이다.

| 구분 | 결과 | 근거·범위 |
|---|---|---|
| DB 없는 단위/fixture 전체 | 124개 통과 | 기존 검사 유지. 새 조회·삭제 흐름은 실제 DB 통합 검사로 검증 |
| 실제 PostgreSQL·HTTP 통합 전체 | 179개 통과 | 기존 163 + ConversationHistoryIntegrationTests 16. 실패·오류·생략 0 |
| bootJar | 통과 | 이번 main 코드가 포함된 실행 jar |
| 실제 8080 jar HTTP | 통과 | 실제 A1 로그인, 목록 200·소유권·페이지 보정, 상세 200·메시지 필드, 타인 상세/삭제 404, 완료/실행 중 Fake 대화 삭제 204·CASCADE, 삭제 후 상세 404·빈 페이지 |
| git diff --check | 통과 | 문서 포함 공백 검사 |
| FE 브라우저·실제 FastAPI·Nginx·운영 HTTPS·부하·재시작 장애 | 미실행 | 후속 연동·운영 확인 범위 |

16개 통합 검사는 목록·정렬 동률·페이지 보정·빈 목록, 질문 수에 실패/취소 포함, 상세와 API-03-S1 메시지 배열의 동일성·artifacts·null, 타인/없는/만료 대화 404, 완료 대화 삭제·CASCADE·늦은 append 차단, 실제 실행 중 Fake 취소와 삭제, 취소 호출의 트랜잭션/바인딩 커넥션 없음·삭제 전 행 존재, 취소 장애 대체 처리, 기록 GET의 AI 재실행 없음, 잘못된 페이지 6가지, 잘못된 UUID, 인증·제한/탈퇴 거절·CSRF를 확인한다.

인증은 대체 컨트롤러 없이 실제 A1 로그인·PBKDF2·JDBC 세션을 사용한다. 데이터는 자체 합성 기관·회원·대화·메시지다. AI 클라이언트는 실제 Fake를 Spy로 감싸 호출과 순서를 확인하며, 취소 장애 한 건만 Unavailable 예외를 주입한다. 실제 FastAPI 통신을 검증한 것으로 취급하지 않는다.

각 검사와 실제 8080 보조 검증은 자체 소유 ID·marker로 만든 데이터와 해당 principal의 세션만 정리한다. 공용 데이터·시퀀스 초기화나 되돌림은 없다. 암호는 메모리에서 생성하고 비밀번호·쿠키·세션 값·실제 개인정보를 파일·로그·보고에 남기지 않는다.

XML은 `build/test-results/test/`, `build/test-results/integrationTest/`, HTML은 `build/reports/tests/`에 있다. 실제 HTTP 보조 도구와 런타임 로그는 무시되는 build 아래에만 둔다.

## 5. 남은 것·FE 인계

- 새 jar를 local/Fake 모드로 8080에 실행해 두었다. 문서 작성 시 PID 30568이며 이후 사용할 때 실제 포트·프로세스를 다시 확인한다.
- FE 확인: 로그인 → AI 패널에서 합성 질문 → 기록 목록과 첫 질문·질문 수 확인 → 상세 메시지를 패널에 복원 → 기존 conversationId로 이어서 질문 → 완료 대화 삭제 → 실행 중 대화 삭제 → 목록·상세에서 사라지는지 확인.
- 목록은 page/size만 받는다. 상세 messages는 API-03-S1과 같은 행 형식이므로 기존 패널 렌더러를 재사용한다. 대화 기록 GET 자체가 AI 실행 복구를 요청하지 않으며, 패널의 기존 메시지 조회 흐름은 유지한다.
- 삭제 성공은 204이며 JSON 본문을 읽지 않는다. 없는/타인/만료 대화는 404로 처리하고, 삭제한 대화가 현재 패널에 열려 있으면 FE 상태도 정리한다.
- FE 브라우저 연동·실제 FastAPI 전환·운영 배포는 남아 있다. Jira 완료 처리와 MR·병합은 사용자가 진행한다.
- 다음 단계는 feat/be-password의 API-32다. 이번 MR과 분리하고 Claude Code 리뷰 후 병합한다.

제안 커밋 제목: `feat: [BE] AI 대화 기록 조회·상세·삭제 구현`

제안 커밋 본문 마지막 줄: `Jira: S15P31B201-229`

MR 대상: develop. 위 1~5절을 인계와 MR 설명으로 사용한다.
