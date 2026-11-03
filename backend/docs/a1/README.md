# A1 로그인 구현과 인계

기준일: 2026-11-02. 작업 폴더 `C:\Users\SSAFY\Desktop\PJT3\S15P31B201`, 브랜치 `feat/be-login`, 시작 HEAD `4de5c62`. Git 쓰기 명령·Docker Compose는 실행하지 않았다.

사용자의 최신 지시를 우선해 현재 폴더의 OpenAPI 2.3.0·AI 패널 계약·V20261102_02를 읽었다. 루트 AGENTS.md의 병합 전 INFRA 참조와 과거 G1 문서의 2.2.0·예전 브랜치 안내는 이번 작업의 기준으로 사용하지 않았다. AI1은 사용자가 `feat/be-agent`를 만든 뒤 별도 진행한다.

## 1. 작업 ID와 API ID

- A1: API-08 `POST /api/auth/login`, API-01 `GET /api/auth/me`, API-02 `POST /api/auth/logout`.
- OPEN-04: PBKDF2 인코더 확정, 8~128자 지원, 기관·회원 시연 seed.
- G1 후속: 현재 브랜치 재검증과 prod SMTP·EUMI 필수 설정 누락 방지.

## 2. 계약·DTO·오류 코드

계약과 달라진 점: 없음.

- `LoginRequest`: 이메일 trim·소문자화, 이메일 형식·254자 제한, 암호는 trim 없이 1~128 코드 포인트. `toString()`은 원문을 숨긴다.
- `LoginUser`, `SessionLoginData`: 로그인 200의 `data.user`에 9개 계약 필드. 토큰을 반환하지 않는다.
- `MenuProfile`: `/auth/me`의 `data`에 7개 계약 필드. nullable title도 필드로 반환한다.
- `ErrorCode.INVALID_CREDENTIALS` 추가: 미등록·암호 불일치·탈퇴·임시 암호 만료는 같은 401 코드·문구. 입력 오류는 기존 `VALIDATION_ERROR`·`INVALID_JSON`을 사용한다.
- `DelegatingPasswordEncoder`: 기본 id `pbkdf2`, `Pbkdf2PasswordEncoder.defaultsForSpringSecurity_v5_8()` 사용. seed 4개 해시에 개별 salt를 사용한다.
- prod 설정에서 필수 SMTP·EUMI 값의 누락·빈값·미해석 placeholder를 거절한다. AuthHashProperties 바인딩도 `${...}` 문자열을 거절한다.

구현은 `auth/login/`, `config/PasswordConfiguration.java`, `auth/session/SessionAuthenticationSupport.java`에 있다. 해시 생성·seed 실행 방법은 [backend README](../../README.md)를 참고한다.

## 3. 권한·잠금

- 로그인은 DB의 회원·기관을 조회해 활성 상태·암호·임시 암호 만료를 검사한 뒤에만 `SessionAuthenticationSupport.establish`를 호출한다.
- principal은 `member_id` 문자열이며 프로필은 브라우저가 보내는 회원 ID를 사용하지 않는다. `/auth/me`는 최신 DB 프로필을 재조회하고, 탈퇴·임시 암호 만료라면 현재 세션을 폐기하고 401을 반환한다.
- 유효 임시 암호는 제한 principal을 발급한다. me·logout·암호 변경과 Health·CSRF만 허용하고 업무 요청은 `PASSWORD_CHANGE_REQUIRED` 403이다.
- 로그인 재인증은 세션 ID 교체, SecurityContext 저장, CSRF 정리를 수행한다. 로그아웃은 현재 JDBC 세션과 SESSION·CSRF 쿠키를 제거한다. 세션이 없어도 204이며 CSRF 검사는 적용한다.
- A1 조회는 읽기 전용 트랜잭션이며 행 잠금은 추가하지 않는다. 암호 변경·발급의 회원 잠금과 다른 세션·전체 세션 폐기는 A3 범위다.

## 4. 실행한 검사

JDK 21.0.11, Gradle 9.8.2, 실제 로컬 PostgreSQL 17.11·Mailpit을 사용했다. 캐시 상태만 확인하지 않고 변경 전 `--rerun-tasks`로도 실행했다.

| 구분 | 검사 | 결과 |
|---|---|---|
| 변경 전 | 현재 브랜치 `test integrationTest bootJar --rerun-tasks` | fixture 15개·통합 4개 통과 |
| DB 없는 단위·fixture | `gradlew.bat test` | 30개 통과, 실패·오류·생략 0 |
| 실제 DB·HTTP·Mailpit | `gradlew.bat integrationTest` | 11개 통과, 실패·오류·생략 0 |
| 빌드 | `gradlew.bat bootJar` | 통과 |
| 실제 prod jar 기동 | DB 설정을 제공하고 SMTP_*·EUMI_* 없이 prod 프로필 실행 | 필수 설정 오류로 비정상 종료 확인 |
| 실제 8080 HTTP | `scripts/Verify-CommonHttp.ps1` | Health·CSRF·401 등 5개 통과 |
| 실제 8080 HTTP | 시연 계정 4개 각각 로그인 → me → 로그아웃 → me | 200 → 200 → 204 → 401 통과 |
| 변경 검사 | `git diff --check`, 추적·미추적 비무시 파일의 시연 평문 암호 검사 | 통과, 평문 없음 |

단위 검사는 PBKDF2의 8·72·73·128자, 한글·보조 평면 문자 128자, 마지막 글자 불일치, salt 무작위성을 확인한다. prod 설정 검사는 실제 application-prod.yml을 읽고 SMTP_*·EUMI_* 전체 누락과 필수 변수별 누락, 미해석 해시 키의 바인딩 실패, 정상 설정 바인딩을 확인한다. 이 설정 검사는 실제 운영 SMTP 연결이나 서버 배포 검사와 구분한다.

실제 A1 통합 6개는 정상 흐름·최신 프로필·쿠키 속성·JDBC principal·2시간 만료, 세션 회전·이전 세션 재사용 401, 동일 로그인 실패 응답, 제한 세션의 업무 403, 탈퇴 후 me 401·세션 폐기, 암호 공백·128 Unicode 코드 포인트 검증을 포함한다. 인증 fixture를 등록하지 않는다. 과거 FoundationIntegrationTests의 fixture 로그인·세션 검사는 이 실제 A1 검사로 옮겼고, FoundationWebTests의 fixture는 DB 없는 보안 경계 검사에만 남겼다.

seed 통합 2개는 실제 SQL 파일을 반복 실행해 기관·회원 중복 방지와 기존 암호·프로필·탈퇴 상태 보존을 확인하고 롤백한다. 추가로 공용 로컬 DB에 시연 seed를 두 번 적용했고 계정 4개의 암호 정합성을 확인했다. 생성 ID는 IDENTITY로 발급하고 시퀀스를 초기화하거나 되돌리지 않았다. 테스트는 자신이 생성한 회원·기관·세션만 정리했다.

## 5. 남은 것과 다음 작업

- 로컬 `bootRun`이 8080에서 실행 중이다. FE는 `/api/auth/csrf` 준비 → 로그인 → CSRF 재준비 → me·logout 흐름으로 연결한다.
- 시연 기관은 강남구·춘천시 각 1개, 회원은 각 2개다. 이메일과 실행 방법은 backend README에 있고 평문 암호는 사용자에게만 전달했다.
- 브라우저·Nginx·운영 HTTPS·운영 SMTP 실연결은 검사하지 않았다. FE의 typecheck·build·브라우저 검사는 FE 담당 범위다.
- 로그인 요청 제한 세부·경합·경계값 전수는 후속 범위다. OpenAPI의 `RATE_LIMITED`는 이번에 새 동작으로 구현하지 않았다.
- AI1·G1 API-39~42·대시보드와 이후 페이지는 구현하지 않았다. 사용자가 다음 브랜치를 준비한 뒤 이어간다.
- A1 Jira 키는 `S15P31B201-172`다. 커밋·MR 본문 마지막 줄에 아래 Jira 참조를 넣는다.

커밋 제목 제안: `feat: [A1] PBKDF2 로그인과 JDBC 세션 인증 구현`

MR 제목 제안: `feat: [A1] 로그인·프로필 복원·로그아웃 구현`

MR 본문은 이 문서의 1~5절을 사용하며 대상 브랜치는 develop이다. 운영 비밀값·쿠키·평문 암호는 MR에 복사하지 않는다.

Jira: S15P31B201-172
