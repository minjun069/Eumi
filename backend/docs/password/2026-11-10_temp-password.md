# A3 비밀번호 찾기 · 구현·검증·리뷰·MR 인계

2026-11-10. 브랜치 `feat/be-temp-password`, 기준 develop `1c3a97d` (AI-b BE·DB 2단계·FE 병합 포함), 원 구현 `3029302` 위의 리뷰 후속. Jira: **S15P31B201-174**.

## 1. 작업 ID · API ID · 변경 파일

A3 비밀번호 찾기, API-09 `POST /api/auth/temp-password`, FR-014·015. 기준은 OpenAPI 2.4.0, `docs/work-ref/미구현_기능_구현_계획.md` 3절·4-2와 11/10 오후 사용자 지시다. M3는 A3 병합 뒤 별도 `feat/be-withdrawal`에서 진행한다.

| 파일 (backend 아래) | 변경 |
|---|---|
| `src/main/java/com/eumi/backend/auth/password/TempPasswordRequest.java` | 로그인과 같은 String.trim 이메일·이름 처리, 코드 포인트 길이·엄격한 JSON 타입/필드 검사, toString 가림 |
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

리뷰 후속은 TempPasswordRequest·TempPasswordTests·TempPasswordIntegrationTests·이 인계 문서 네 파일이다. N1·N2·N5는 문서에 반영했고, N3는 strip→trim 및 공백별 회귀 검사, N4는 다른 DB 연결과 실제 SELECT FOR UPDATE 잠금 대기를 확인하는 검사로 보강했다. 로그인 코드와 발급·메일·세션 처리 코드는 바꾸지 않았다.

## 2. 계약과 달라진 점 · DTO · 오류

**구현 방침:** 이번 계획·사용자 지시의 처리 흐름을 유지한다. 이전 공통 문서의 BE 메모리 요청 제한 설명보다 이번 지시를 우선해, API-09 요청 제한은 Nginx 담당으로 두었다. BE 제한기는 추가하지 않았다.

**계약 문서 보완 요청(N1):** API-09는 공통 제한 세션 규칙과 x-temporary-password-allowed=false에 따라 PASSWORD_CHANGE_REQUIRED 403을 반환하지만, 개별 x-error-codes와 403 설명에는 이 코드가 빠져 있다. 동작은 유지하고 인프라 담당에게 API-09 오류 목록·403 설명/예제 반영을 요청한다. docs/api는 직접 수정하지 않았다.

- 요청 `{email,name}`: 이메일과 이름은 로그인과 같은 Java String.trim()을 사용한다(N3). 이메일은 Locale.ROOT로 소문자화한다. U+0020과 U+0001 등 U+0020 이하 문자는 앞뒤에서 제거하고, U+3000 전각 공백은 남겨 조회 문자열에 포함한다. 리뷰 예시의 '전각 공백이면 반드시 400'은 현재 Hibernate 이메일 검증기와 다르므로 단정하지 않는다. 이메일 최대 254자, 이름 1~100자를 코드 포인트로 검사한다. 이름의 대소문자나 내부 공백은 바꾸지 않는다.
- 모르는 필드·타입·필수 속성 누락은 INVALID_JSON 400, 잘못된 이메일·null·빈 이름·길이 초과는 VALIDATION_ERROR 400이다. DTO의 toString은 입력을 노출하지 않는다.
- 정상 형식의 업무 요청은 성공 여부를 구분하지 않고 204다. 대상 없음·이름 다름·탈퇴·유효한 임시 비밀번호가 있으면 DB·메일·세션을 변경하지 않는다. CSRF·제한 세션 같은 공통 보안 규칙은 먼저 적용한다.
- 모든 정상 형식 요청에서 PBKDF2를 한 번 계산한다. 초기 조회 연결을 반환한 뒤 수행하므로 대상 없음에도 같은 해시 계산 비용을 쓴다.
- 12자 비밀번호에 대문자·소문자·숫자·`!@#$%^&*` 중 특수문자를 각각 하나 이상 넣는다. `0`, `O`, `o`, `1`, `l`, `I`는 제외하고 SecureRandom으로 생성·섞는다. 원문은 메일 작성에만 사용하고 로그·DB·응답에 넣지 않는다.
- 잠금 뒤 다시 자격을 확인하고 Clock의 현재 순간을 기준으로 만료를 24시간 뒤로 설정한다. 만료와 updated_at은 같은 순간을 기준으로 저장한다.
- 메일 제목은 `[이음이] 임시 비밀번호 안내`, 본문에는 임시 비밀번호·서울 만료 시각·24시간 유효·즉시 변경 안내만 넣는다. 이름·기관은 넣지 않는다.
- 메일 발송 예외는 기존 INTERNAL_SERVER_ERROR 500이다. 해시·만료·수정 시각·세션 삭제를 함께 되돌린다. 새 오류 코드는 추가하지 않았다.

받아들이는 한계는 계획 3-3·4-2와 같다. SMTP 접수 뒤 DB 커밋이 실패하면 메일의 값은 사용할 수 없다. SMTP 장애 시 대상 있는 요청만 500이 될 수 있다. outbox나 별도 생성 상태는 추가하지 않는다.

**응답 시간 한계(N2):** 해시 횟수를 맞춰도 발급 대상에만 트랜잭션·잠금·DB 변경·동기 Mailpit 전송이 추가되므로 응답 시간 차이가 남을 수 있다. 시간으로 이메일·이름 조합의 일치 여부가 전혀 드러나지 않는다고 보장하지 않는다. 실제 구별 가능성·차이 크기는 측정하지 않았다. Nginx 제한과 유효 기간 내 재발급 방지를 유지하고, 이번에는 지연 보정이나 비동기 발송을 추가하지 않는다.

이번 메일 전달 대상은 Mailpit이다. SMTP는 백엔드→Mailpit 통신 방식이며 외부 SMTP 서비스·도메인 소유권·외부 실제 수신함 배송은 이번 작업에 포함되지 않는다.

## 3. 권한 · 세션 · 잠금

- API-09는 기존 공개 경로 설정을 사용한다. 로그인은 필요 없지만 CSRF 쿠키/헤더가 필요하다. CSRF 실패는 403 CSRF_INVALID다.
- 기존 임시 비밀번호 제한 세션의 API-09 요청은 공통 필터가 403 PASSWORD_CHANGE_REQUIRED로 거절한다. 재발급 무처리 검사는 비로그인 요청으로 수행한다.
- 초기 SELECT와 PBKDF2는 트랜잭션 밖이다. TransactionTemplate 안에서 해당 회원 한 행을 FOR UPDATE로 잠그고 이메일·이름·탈퇴·기존 임시 만료를 재확인한다. 다른 기관·사례자·자원 행 잠금은 얻지 않는다.
- 적용 순서는 해시/만료/updated_at 변경 → principal_name=memberId인 모든 spring_session 삭제 → MailService.sendPlainText → 커밋이다. 세션 삭제는 SessionRepository의 별도 트랜잭션 대신 같은 JDBC 연결의 DELETE로 처리한다.
- 동시 요청이 먼저 새 임시 비밀번호를 발급했다면 후속 요청은 잠금 뒤 미래 만료를 보고 204로 끝낸다. 기존 비밀번호 변경의 다른 세션 삭제 메서드는 유지했다.
- 실제 로그인 후 mustChangePassword=true, 일반 API 403, API-32 변경 후 만료 제거와 제한 해제는 기존 코드를 사용한다.

## 4. 실행한 검사와 결과

2026-11-10 KST, JDK 21.0.11·Gradle 9.8.2. 사용자가 준비한 PostgreSQL 5432·Mailpit SMTP 1025/API 8025를 사용했다. 직접 Docker Compose를 실행하지 않았다.

### 이번 N1~N5 후속 검사 (3029302 위의 변경)

| 구분 | 클래스/검사 | 개수 | 시작 시각(KST)·결과 |
|---|---|---:|---|
| DB 없는 전체 단위/MVC/설정/HTTP 대역 | `test` | 173 | 최종 재실행 통과 |
| 공백 정규화·기존 서비스 단위 | TempPasswordTests | 17 | 14:24:25, 통과 |
| 기존 MVC·보안·서비스 mock | TempPasswordWebTests | 4 | 14:24:38, 통과 |
| 실제 DB·A1 HTTP 회귀 | AuthIntegrationTests | 8 | 14:25:47, 통과 |
| 실제 DB·PBKDF2 연결 경계 | AuthTransactionIntegrationTests | 1 | 14:26:11, 통과 |
| 실제 DB·비밀번호 변경·세션 회귀 | PasswordChangeIntegrationTests | 14 | 14:26:19, 통과 |
| 실제 DB·Mailpit·8080·잠금 대기 | TempPasswordIntegrationTests | 12 | 14:26:38, 통과 |
| 패키징 | bootJar | — | 이번 후속 소스로 통과 |
| 변경 검사 | git diff --check·공백 검사 | — | 통과. 이번 후속은 backend 내부 네 파일만 변경 |

최종 통합 합계 35개, 단위 합계 173개이며 실패·오류·생략은 모두 0이다. 통합 실행은 14:26:53에 종료했다. 신규 공백 단위 3건과 실제 HTTP 1건, 잠금 경합 1건을 기존 검사에 더했다. 단위의 17개·4개는 전체 173개에 포함된다. 클래스별 수·시각은 실행 직후 build/a3-follow-up-verification.json에 따로 기록해 원 구현 기록과 구분했다.

- N3: U+0020·U+0001·U+3000 입력을 로그인 DTO와 비교했다. 전각 공백은 현재 이메일 검증기가 허용하므로 '반드시 400'이라는 리뷰 예시를 정정했다. 실제 HTTP에서도 그 공백을 포함한 조회는 A3 무처리 204, 로그인 INVALID_CREDENTIALS 401이며, 공백 없는 기존 계정의 해시·세션·메일은 바뀌지 않았다.
- N4: 별도 연결에서 회원을 잠그고 미래 임시 만료를 미커밋 상태로 넣었다. 요청이 초기 조회·해시 뒤 lockMember에 도달했음을 latch로 확인했다. 요청 연결의 pg_backend_pid를 기록하고 pg_stat_activity·pg_blocking_pids로 **그 연결의 SELECT FOR UPDATE가 해당 별도 연결에 막혀 있음**을 확인한 뒤, 추가 300ms에도 요청이 끝나지 않음을 검사했다. 커밋 후 204, 기존 해시·수정 시각·세션 유지, 별도 트랜잭션의 만료 유지와 메일 0통을 확인했다. 300ms 대기만으로 잠금 여부를 판정하지 않는다.
- 첫 단위 실행에서는 새 테스트가 전각 공백을 형식 오류라고 잘못 예상해 1건 실패했다. 그 가정을 실제 검증기 동작에 맞춰 수정한 뒤 전체 단위 검사를 다시 실행해 위 최종 결과를 얻었다. 로그인과 A3의 검증 규칙을 추가로 강화하지 않았다.

정상 메일 전송과 읽기는 실제 Mailpit이며, 기존 메일 실패 롤백은 JavaMailSender 예외 대역이다. 이번 잠금 검사는 실제 DB 행 잠금을 사용하고 repository spy는 진입 시점과 연결 PID를 관찰하는 역할만 한다. 실제 AI·브라우저·Nginx 429·운영 Mailpit 수신·응답 시간 차이 실측은 미실행이다.

### 원 구현 3029302의 이전 검사 기록

아래 170개·33개는 최초 구현 당시 결과다. Claude Code도 3029302 리뷰에서 통합 33개를 13:59에 재실행해 통과했다. 이번 후속 결과는 위의 173개·35개로 구분한다.

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
7. 최초 구현에서는 잠금 직전 탈퇴 변경을 repository spy로 재현하고 두 실제 HTTP 요청의 한 통 발급을 확인했다. 이번 후속에서는 위 N4의 별도 트랜잭션 잠금 대기까지 추가 확인했다.
8. 로그인 중인 요청자의 자기 세션도 삭제되고 요청 종료 시 되살아나지 않음.
9. CSRF/입력 오류에서 메일·DB가 바뀌지 않음.

자신이 만든 조직·회원·세션과 고유 수신자의 메일만 정리했다. Mailpit 정리는 비어 있지 않은 소유 메일 ID만 전송한다. 메일 조회/삭제 형식은 [Mailpit 공식 API](https://mailpit.axllent.org/docs/api-v1/)와 로컬 응답을 확인해 사용했다. 비밀번호·쿠키·본문을 출력하거나 테스트 결과에 기록하지 않았다. 검사 서버는 종료했다.

Git Bash 재현 명령 (backend 폴더, 공용 DB·Mailpit 준비 및 빈 8080 필요):

```bash
./gradlew.bat test --console=plain
./gradlew.bat integrationTest --tests '*TempPasswordIntegrationTests' --tests '*PasswordChangeIntegrationTests' --tests '*AuthIntegrationTests' --tests '*AuthTransactionIntegrationTests' bootJar --console=plain
git diff --check
```

로컬 DB 암호는 실행 환경으로 준비하며 파일·명령 본문에 값을 적지 않는다. 실제 AI는 호출하지 않았다. 브라우저/FE, Nginx 429, 운영 환경의 Mailpit 수신·운영 배포와 응답 시간 차이 실측은 미실행이다. 외부 이메일 배송은 이번 범위가 아니다.

## 5. 남은 것 · 리뷰 · MR 초안

- **A3 세션 폐기 범위는 AGENTS.md 5장에 따라 Claude Code 리뷰 대상이다.** 3029302 리뷰에서 필수 수정 없음으로 확인했고, N1~N5를 이번 후속에 반영했다. 이번 후속 변경은 재검토 대상이다. PBKDF2 경계, 잠금 뒤 재확인, 전체 세션 삭제의 트랜잭션 참여, Mailpit 전송 예외 롤백과 비밀값 노출에 관한 기존 동작을 유지한다.
- 인프라 인계(N1): API-09의 x-error-codes 및 403 설명/예제에 PASSWORD_CHANGE_REQUIRED를 반영한다. 공통 필터 규칙은 유지한다. A2 문서를 반영할 때 API-05~07에도 같은 제한 세션 오류가 필요한지 함께 확인한다.
- FE는 API-09의 성공/무처리 공통 204 뒤 같은 안내를 표시하고 로그인 화면으로 이동한다. 429는 Nginx 응답을 처리한다.
- 인프라는 API-09 요청 제한을 Nginx에서 담당한다(계획: 인증 메일과 합산 분당 3, 순간 3). 이번 BE 검사에서는 Nginx를 거치지 않았다.
- M3는 A3 병합 뒤 `feat/be-withdrawal`에서 API-33·34를 구현한다. 그 MR의 계약 차이에 API-34 x-db-objects의 ai_conversation_turn→ai_message 및 필드 설명 정정은 인프라 담당임을 적는다. M3는 이번에 구현하지 않았다.
- 에이전트는 git 쓰기를 실행하지 않았다. 김민재가 커밋·리뷰·push·develop 대상 MR·병합을 진행한다.

커밋/MR 제목 제안: `feat: [BE] 임시 비밀번호 발급과 전체 세션 폐기 구현`.

이번 후속 커밋 제목 제안: `fix: [BE] 비밀번호 찾기 정규화와 잠금 검사 보완`.

커밋 본문 끝: `Jira: S15P31B201-174`.

### Jira

S15P31B201-174

### 변경 내용

- A3 API-09 비밀번호 찾기 구현. 대상 존재 여부와 무관하게 204, 입력 오류 400.
- SecureRandom 12자·24시간 임시 비밀번호, PBKDF2 저장, 전체 세션 폐기와 메일 발송을 같은 트랜잭션에서 처리. 메일 실패 시 롤백/500.
- 대상 없음에도 해시 한 번, 잠금 뒤 조건 재확인, 유효 임시 비밀번호 재발급 방지.
- 기존 비밀번호 변경의 deleteOtherSessions 유지, 공용 deleteAllSessions 추가. 변경 파일과 권한·잠금은 이 문서 1~3절.
- 리뷰 후속: 로그인과 같은 trim 정규화, 공백별 검사와 실제 DB 잠금 대기 검사 추가. 제한 세션 오류 목록 누락·응답 시간 한계와 Jira 상태를 문서에 반영.

### 확인 방법

1. PostgreSQL·Mailpit과 빈 8080을 준비하고 4절 Git Bash 명령을 실행한다.
2. 이번 후속은 단위/MVC/HTTP 대역 173개, 실제 DB·HTTP 통합 35개 통과. TempPasswordIntegrationTests 12개는 Mailpit 메일의 제한 로그인, 무처리·재요청·동시 발급·세션 폐기와 추가된 실제 잠금 대기·전각 공백 조회를 검사한다.
3. 메일 실패는 JavaMailSender 예외 대역으로 실제 DB 롤백을 검사한다. 정상 발송·메일 읽기는 실제 Mailpit이다.
4. 이번 후속 bootJar 통과. 실행 시각과 대역/실제 구분은 4절의 별도 기록을 따른다. 브라우저·Nginx 429·운영 Mailpit 수신·응답 시간 차이 실측은 미실행이다. 외부 이메일 배송은 범위에 없다.

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
- [x] 커밋 본문에 Jira 키를 적었다 (원 구현 3029302의 Jira: S15P31B201-174 확인, 추가 커밋에도 같은 키 기재)
- [ ] DB를 바꿨다면: 병합된 V 파일은 그대로이고, 새 파일 이름이 `V{날짜}_{순번}__설명.sql`이며, ERD 변경 기록에 반영했다 (해당 없음)
- [ ] 의존성을 바꿨다면 lock 파일도 함께 커밋했다 (해당 없음)
- [x] 기능명세서와 다르게 구현한 부분이 있다면 아래에 적었다

### 기능명세서와 다른 점 · 참고 사항

API-09의 PASSWORD_CHANGE_REQUIRED 403은 공통 제한 세션 규칙에 맞지만 개별 OpenAPI 오류 목록에는 누락돼 있어 인프라에 문서 보완을 요청한다. 입력은 로그인과 같은 trim으로 통일했다. 이전 공통 문서의 BE 메모리 요청 제한 설명 대신 11/10 지시대로 Nginx가 제한한다. 해시 횟수를 맞춰도 발급 경로의 DB 변경·Mailpit 동기 전송 때문에 응답 시간 차이가 남을 수 있으며 실측하지 않았다. Mailpit 접수와 DB 커밋의 완전한 원자성은 보장하지 않는다. 원문은 메일로만 전달하며 응답·DB·로그에 넣지 않는다. 외부 이메일 배송은 이번 범위가 아니다. M3는 A3 병합 뒤 별도 MR이다.
