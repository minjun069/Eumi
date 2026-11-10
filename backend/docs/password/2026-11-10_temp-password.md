# A3 비밀번호 찾기 · 구현·검증·리뷰·MR 인계

2026-11-10. 브랜치 `feat/be-temp-password`, 기준 develop `1c3a97d` (AI-b BE·DB 2단계·FE 병합 포함). Jira: **S15P31B201-174**.

## 1. 작업 ID · API ID · 변경 파일

A3 비밀번호 찾기, API-09 `POST /api/auth/temp-password`, FR-014·015. 기준은 OpenAPI 2.4.0, `docs/work-ref/미구현_기능_구현_계획.md` 3절·4-2와 11/10 오후 사용자 지시다. M3는 A3 병합 뒤 별도 `feat/be-withdrawal`에서 진행한다.

| 파일 (backend 아래) | 변경 |
|---|---|
| `src/main/java/com/eumi/backend/auth/password/TempPasswordRequest.java` | 이메일 정규화·이름 trim·코드 포인트 길이·엄격한 JSON 타입/필드 검사, toString 가림 |
| `TempPasswordController.java` | API-09 요청 검사 후 빈 본문 204 |
| `TemporaryPasswordGenerator.java` | SecureRandom 기반 12자 생성·섞기 |
| `TempPasswordRepository.java` | 초기 조회·회원 FOR UPDATE·해시/만료/수정 시각 변경 |
| `TempPasswordService.java` | 트랜잭션 밖 PBKDF2, 잠금 뒤 재확인·변경·전체 세션 폐기·메일 발송 |
| `PasswordChangeRepository.java` | 기존 deleteOtherSessions 유지, 같은 업무 트랜잭션용 deleteAllSessions 추가 |
| `src/test/java/com/eumi/backend/TempPasswordTests.java` | 생성 규칙·정규화·무처리·잠금 뒤 재확인·발송 순서의 단위 검사 |
| `TempPasswordWebTests.java` | 실제 MVC/보안, 서비스 mock으로 204·400·CSRF/제한 세션 검사 |
| `TempPasswordIntegrationTests.java` | 실제 PostgreSQL·8080·A1 인증·SMTP/Mailpit 검사 |
| `support/MailpitTestInbox.java` | 고유 fixture 수신자에 해당하는 메일만 조회·정리 |
| `README.md`, `docs/password/README.md`, 이 문서 | 현재 구현과 검증·인계 진입점 |

표에서 생략한 main Java 경로는 `src/main/java/com/eumi/backend/auth/password/`, 테스트 경로는 `src/test/java/com/eumi/backend/`다. frontend·db·infra·docs/api·Jenkinsfile·의존성은 변경하지 않았다.

## 2. 계약과 달라진 점 · DTO · 오류

**이번 계획·사용자 지시 대비 차이: 없음.** 이전 공통 문서의 BE 메모리 요청 제한 설명보다 이번 지시를 우선해, API-09 요청 제한은 Nginx 담당으로 두었다. BE 제한기는 추가하지 않았다.

- 요청 `{email,name}`: 이메일은 앞뒤 공백 제거·소문자화, 이름은 앞뒤 공백만 제거한다. 이메일 최대 254자, 이름 1~100자를 코드 포인트로 검사한다. 이름의 대소문자나 내부 공백은 바꾸지 않는다.
- 모르는 필드·타입·필수 속성 누락은 INVALID_JSON 400, 잘못된 이메일·null·빈 이름·길이 초과는 VALIDATION_ERROR 400이다. DTO의 toString은 입력을 노출하지 않는다.
- 정상 형식의 업무 요청은 성공 여부를 구분하지 않고 204다. 대상 없음·이름 다름·탈퇴·유효한 임시 비밀번호가 있으면 DB·메일·세션을 변경하지 않는다. CSRF·제한 세션 같은 공통 보안 규칙은 먼저 적용한다.
- 모든 정상 형식 요청에서 PBKDF2를 한 번 계산한다. 초기 조회 연결을 반환한 뒤 수행하므로 대상 없음에도 같은 해시 계산 비용을 쓴다.
- 12자 비밀번호에 대문자·소문자·숫자·`!@#$%^&*` 중 특수문자를 각각 하나 이상 넣는다. `0`, `O`, `o`, `1`, `l`, `I`는 제외하고 SecureRandom으로 생성·섞는다. 원문은 메일 작성에만 사용하고 로그·DB·응답에 넣지 않는다.
- 잠금 뒤 다시 자격을 확인하고 Clock의 현재 순간을 기준으로 만료를 24시간 뒤로 설정한다. 만료와 updated_at은 같은 순간을 기준으로 저장한다.
- 메일 제목은 `[이음이] 임시 비밀번호 안내`, 본문에는 임시 비밀번호·서울 만료 시각·24시간 유효·즉시 변경 안내만 넣는다. 이름·기관은 넣지 않는다.
- 메일 발송 예외는 기존 INTERNAL_SERVER_ERROR 500이다. 해시·만료·수정 시각·세션 삭제를 함께 되돌린다. 새 오류 코드는 추가하지 않았다.

받아들이는 한계는 계획 3-3·4-2와 같다. SMTP 접수 뒤 DB 커밋이 실패하면 메일의 값은 사용할 수 없다. SMTP 장애 시 대상 있는 요청만 500이 될 수 있다. outbox나 별도 생성 상태는 추가하지 않는다.

## 3. 권한 · 세션 · 잠금

- API-09는 기존 공개 경로 설정을 사용한다. 로그인은 필요 없지만 CSRF 쿠키/헤더가 필요하다. CSRF 실패는 403 CSRF_INVALID다.
- 기존 임시 비밀번호 제한 세션의 API-09 요청은 공통 필터가 403 PASSWORD_CHANGE_REQUIRED로 거절한다. 재발급 무처리 검사는 비로그인 요청으로 수행한다.
- 초기 SELECT와 PBKDF2는 트랜잭션 밖이다. TransactionTemplate 안에서 해당 회원 한 행을 FOR UPDATE로 잠그고 이메일·이름·탈퇴·기존 임시 만료를 재확인한다. 다른 기관·사례자·자원 행 잠금은 얻지 않는다.
- 적용 순서는 해시/만료/updated_at 변경 → principal_name=memberId인 모든 spring_session 삭제 → MailService.sendPlainText → 커밋이다. 세션 삭제는 SessionRepository의 별도 트랜잭션 대신 같은 JDBC 연결의 DELETE로 처리한다.
- 동시 요청이 먼저 새 임시 비밀번호를 발급했다면 후속 요청은 잠금 뒤 미래 만료를 보고 204로 끝낸다. 기존 비밀번호 변경의 다른 세션 삭제 메서드는 유지했다.
- 실제 로그인 후 mustChangePassword=true, 일반 API 403, API-32 변경 후 만료 제거와 제한 해제는 기존 코드를 사용한다.

## 4. 실행한 검사와 결과

2026-11-10 KST, JDK 21.0.11·Gradle 9.8.2. 사용자가 준비한 PostgreSQL 5432·Mailpit SMTP 1025/API 8025를 사용했다. 직접 Docker Compose를 실행하지 않았다.

| 구분 | 클래스/검사 | 개수 | 시작 시각(KST)·결과 |
|---|---|---:|---|
| DB 없는 전체 단위/MVC/설정/HTTP 대역 | `test` | 170 | 13:20:55~13:21:20, 모두 통과 |
| 신규 단위/fixture | TempPasswordTests | 14 | 13:21:19, 통과 |
| 신규 MVC·서비스 mock | TempPasswordWebTests | 4 | 13:21:20, 통과 |
| 실제 DB·A1 HTTP 회귀 | AuthIntegrationTests | 8 | 13:21:58, 통과 |
| 실제 DB·PBKDF2 연결 경계 | AuthTransactionIntegrationTests | 1 | 13:22:08, 통과 |
| 실제 DB·비밀번호 변경·세션 회귀 | PasswordChangeIntegrationTests | 14 | 13:22:11, 통과 |
| 실제 DB·SMTP/Mailpit·8080 | TempPasswordIntegrationTests | 10 | 13:22:19, 통과 |
| 패키징 | bootJar | — | 통과 |
| 변경 검사 | git diff --check·변경 파일 공백 검사 | — | 통과. 변경 파일 13개 모두 backend 내부 |

통합 합계는 33개다. 모든 실행에서 실패·오류·생략은 0이다. 신규 단위 14개와 MVC 4개는 전체 test 170개에 포함되므로 중복 합산하지 않는다. 통합 실행은 13:22:26에 종료했으며 클래스별 결과는 build/a3-verification.json에 실행 직후 기록했다(로컬 빌드 산출물, 커밋 대상 아님).

실제 8080 TempPasswordIntegrationTests의 확인 내용:

1. 비로그인 발급 204 → Mailpit에서 해당 고유 수신자의 메일 조회 → 임시 비밀번호로 A1 로그인 → mustChangePassword=true → 일반 업무 API 403 → API-32 변경 후 제한 해제.
2. 원래 비밀번호의 로그인 거절, 같은 회원의 기존 세션 전체 삭제, 다른 회원 세션 유지.
3. 대상 없음·이름 다름·탈퇴·유효 기간 내 재요청은 204이며 비밀번호/만료/updated_at·메일·세션을 유지.
4. 만료된 임시 비밀번호 재발급과 서울 만료 시각·12자 본문 규칙.
5. 메일 발송 실패 시 500과 DB/세션 롤백. 이 실패는 **JavaMailSender 예외 대역**으로 주입했고, 정상 발송은 실제 SMTP·Mailpit을 사용했다.
6. PBKDF2가 대상 없음에도 한 번 실행되고 실제 트랜잭션/DB 연결 밖임을 spy로 관찰.
7. 잠금 직전 탈퇴 상태 변경을 repository spy로 재현해 재확인 확인. 별도로 두 실제 HTTP 요청을 동시에 보내 한 통만 발급됨을 확인.
8. 로그인 중인 요청자의 자기 세션도 삭제되고 요청 종료 시 되살아나지 않음.
9. CSRF/입력 오류에서 메일·DB가 바뀌지 않음.

자신이 만든 조직·회원·세션과 고유 수신자의 메일만 정리했다. Mailpit 정리는 비어 있지 않은 소유 메일 ID만 전송한다. 메일 조회/삭제 형식은 [Mailpit 공식 API](https://mailpit.axllent.org/docs/api-v1/)와 로컬 응답을 확인해 사용했다. 비밀번호·쿠키·본문을 출력하거나 테스트 결과에 기록하지 않았다. 검사 서버는 종료했다.

Git Bash 재현 명령 (backend 폴더, 공용 DB·Mailpit 준비 및 빈 8080 필요):

```bash
./gradlew.bat test --console=plain
./gradlew.bat integrationTest --tests '*TempPasswordIntegrationTests' --tests '*PasswordChangeIntegrationTests' --tests '*AuthIntegrationTests' --tests '*AuthTransactionIntegrationTests' bootJar --console=plain
git diff --check
```

로컬 DB 암호는 실행 환경으로 준비하며 파일·명령 본문에 값을 적지 않는다. 실제 AI는 호출하지 않았다. 브라우저/FE, Nginx 429, 운영 SMTP·최종 배달·운영 배포는 미실행이다.

## 5. 남은 것 · 리뷰 · MR 초안

- **A3 세션 폐기 범위는 AGENTS.md 5장에 따라 Claude Code 리뷰 대상이다.** 구현·검사를 마쳤으며 외부 리뷰 완료로 표시하지 않는다. PBKDF2 경계, 잠금 뒤 재확인, 전체 세션 삭제의 트랜잭션 참여, SMTP 예외 롤백과 비밀값 노출을 검토한다.
- FE는 API-09의 성공/무처리 공통 204 뒤 같은 안내를 표시하고 로그인 화면으로 이동한다. 429는 Nginx 응답을 처리한다.
- 인프라는 API-09 요청 제한을 Nginx에서 담당한다(계획: 인증 메일과 합산 분당 3, 순간 3). 이번 BE 검사에서는 Nginx를 거치지 않았다.
- M3는 A3 병합 뒤 `feat/be-withdrawal`에서 API-33·34를 구현한다. 그 MR의 계약 차이에 API-34 x-db-objects의 ai_conversation_turn→ai_message 및 필드 설명 정정은 인프라 담당임을 적는다. M3는 이번에 구현하지 않았다.
- 에이전트는 git 쓰기를 실행하지 않았다. 김민재가 커밋·리뷰·push·develop 대상 MR·병합을 진행한다.

커밋/MR 제목 제안: `feat: [BE] 임시 비밀번호 발급과 전체 세션 폐기 구현`.

커밋 본문 끝: `Jira: S15P31B201-174`.

### Jira

S15P31B201-174

### 변경 내용

- A3 API-09 비밀번호 찾기 구현. 대상 존재 여부와 무관하게 204, 입력 오류 400.
- SecureRandom 12자·24시간 임시 비밀번호, PBKDF2 저장, 전체 세션 폐기와 메일 발송을 같은 트랜잭션에서 처리. 메일 실패 시 롤백/500.
- 대상 없음에도 해시 한 번, 잠금 뒤 조건 재확인, 유효 임시 비밀번호 재발급 방지.
- 기존 비밀번호 변경의 deleteOtherSessions 유지, 공용 deleteAllSessions 추가. 변경 파일과 권한·잠금은 이 문서 1~3절.

### 확인 방법

1. PostgreSQL·Mailpit과 빈 8080을 준비하고 4절 Git Bash 명령을 실행한다.
2. 단위/MVC/HTTP 대역 170개, 실제 DB·HTTP 통합 33개 통과. API-09 신규 통합 10개는 SMTP·Mailpit 메일에서 읽은 비밀번호의 제한 로그인, 무처리·재요청·동시 발급·세션 폐기를 검사한다.
3. 메일 실패는 JavaMailSender 예외 대역으로 실제 DB 롤백을 검사한다. 정상 발송·메일 읽기는 실제 Mailpit이다.
4. bootJar 통과. 브라우저·Nginx 429·운영 배달은 미실행이다. 상세 시각과 범위는 4절.

### 리뷰

CONTRIBUTING.md 3.3 표에 따라 김민준(PM)을 Reviewers에 지정한다. A3 세션 폐기는 AGENTS.md 5장에 따라 Claude Code 리뷰 후 병합한다.

승인 필수 변경이 있나요? (계약 형식·DB·infra 변경 없음)

- [ ] DB 마이그레이션 (`db/migration`)
- [ ] 파트끼리 주고받는 API · 호출 형식 · DB로 주고받는 행 형식(ai_message · 보고서)
- [ ] `infra/`, `Jenkinsfile`

### 체크리스트

- [ ] 대상 브랜치가 `develop`이다
- [x] 로컬에서 실행 · 테스트해 보았다
- [x] `.env`, 비밀번호, API 키, 실제 개인정보가 포함되지 않았다
- [ ] 커밋 본문에 Jira 키를 적었다
- [ ] DB를 바꿨다면: 병합된 V 파일은 그대로이고, 새 파일 이름이 `V{날짜}_{순번}__설명.sql`이며, ERD 변경 기록에 반영했다 (해당 없음)
- [ ] 의존성을 바꿨다면 lock 파일도 함께 커밋했다 (해당 없음)
- [x] 기능명세서와 다르게 구현한 부분이 있다면 아래에 적었다

### 기능명세서와 다른 점 · 참고 사항

이번 계획·사용자 지시 대비 없음. 이전 공통 문서의 BE 메모리 요청 제한 설명 대신 11/10 지시대로 Nginx가 제한한다. SMTP 접수와 DB 커밋/최종 배달의 완전한 원자성은 보장하지 않는다. 실제 원문은 메일로만 전달하며 응답·DB·로그에 넣지 않는다. M3는 A3 병합 뒤 별도 MR이다.
