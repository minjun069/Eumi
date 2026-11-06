# 이음이 백엔드 실행과 공통 기반

Java 21 · Spring Boot 4.1.2 · Gradle Wrapper 9.8.2를 사용한다. 공통 기반, A1 로그인·최신 프로필·로그아웃, AI1 Fake AI 패널, 지역·기관 회원 조회 API-39~42, 대시보드 API-10~12, 사례자·상담 API-19~29, 복지자원 API-13~17, 마이페이지 API-30·31·35, AI 대화 기록 API-36~38, 비밀번호 변경 API-32를 구현했다. 회원가입·임시 비밀번호 발급·탈퇴는 후속 작업이다.

## 먼저 읽을 기록

- [11월 1일 재개 안내와 운영 설정 검토 사항](docs/g1/2026-11-01_이어가기.md)
- [G1 현재 범위와 인계](docs/g1/README.md)
- [G1 구현 결정](docs/g1/decisions.md)
- [G1 검증 결과와 재현 방법](docs/g1/verification.md)
- [A1 구현·검증·MR 인계](docs/a1/README.md)
- [11월 3일 A1 리뷰 후속 보완](docs/a1/2026-11-03_review-follow-up.md)
- [지역·기관 회원 조회 API-39~42 구현·검증·MR 인계](docs/region/README.md)
- [복지자원 API-13~17 구현·검증·MR 인계](docs/resources/README.md)
- [내 정보·담당 자원 API-30·31·35 구현·검증·MR 인계](docs/my/README.md)
- [AI 대화 기록 API-36~38 구현·검증·MR 인계](docs/my-history/README.md)
- [비밀번호 변경 API-32 구현·검증·A3 리뷰 인계](docs/password/README.md)
- [AI1 구현·설정·검증·MR 인계](docs/ai1/README.md)
- [AI1 리뷰 후속·운영 모드 인계](docs/ai1/2026-11-03_review-follow-up.md)
- [AI1 질문 보존·진단 재점검 후속](docs/ai1/2026-11-03_masking-follow-up.md)
- [AI1 명시 표지 개인정보 노출 회귀 수정](docs/ai1/2026-11-03_privacy-regression-follow-up.md)
- [AI1 수집 항목 기준 마스킹 범위 축소·계약 인계](docs/ai1/2026-11-03_masking-scope.md)
- [협업 규칙](../CONTRIBUTING.md), [인증 결정](../docs/decisions/login-sse.md), [로컬 DB·메일](../infra/README.md)

최종 API 계약은 이 작업 폴더의 [docs/api/openapi.json](../docs/api/openapi.json) 2.3.0이다. AI는 [ai-agent-panel.md](../docs/api/ai-agent-panel.md)의 A 방식이 기준이다. 저장소 밖 `공통_응답_및_세션_규칙.md`와 `구현_트랜잭션_가이드.md`도 함께 읽되, 폐기된 SSE·AI 실행 계약을 적용하지 않는다. G1 문서에 남아 있는 2.2.0·과거 브랜치 안내는 당시의 기록이다.

## 로컬 실행

공용 PostgreSQL·Mailpit은 사용자가 `eumi-infra`에서 준비한다. 에이전트는 Docker Compose를 실행하지 않는다. 현재 공용 DB에는 V20261102_02까지 적용돼 있다. backend 폴더에서 실행한다.

```powershell
.\gradlew.bat bootRun
```

BE는 eumi_app으로 접속하고 Hibernate는 validate, Session JDBC의 테이블 자동 생성은 never로 둔다. 호스트에서 띄운 BE는 infra의 `.env`를 자동으로 읽지 않는다.

- Health: <http://localhost:8080/api/health> → `200 {"status":"UP"}`. DB readiness 검사가 아니다.
- CSRF 준비: `GET /api/auth/csrf` → 204·본문 없음·XSRF-TOKEN 쿠키.
- 로그인: `POST /api/auth/login` → 200 `data.user`. 이메일은 trim·소문자화하고 암호는 원문을 유지한다.
- 프로필: `GET /api/auth/me` → 200 `data`의 메뉴 프로필, 비인증·탈퇴·만료 임시 암호 회원은 401.
- 로그아웃: `POST /api/auth/logout` → 현재 JDBC 세션·SESSION·CSRF 쿠키 정리 후 204. 세션이 없어도 204이며 유효 CSRF는 필요하다.
- 지역: `GET /api/regions/sidos`, `/api/regions/sidos/{sidoCode}/sigungus`, `/api/regions/sigungus/{sigunguCode}/dongs` → 로그인 후 코드·이름 배열. 형식 오류 400, 없는 상위 코드 404.
- 기관 회원: `GET /api/organizations/me/members` → 현재 로그인 회원의 기관에 속한 미탈퇴 회원의 memberId·name·title 배열. title이 null이어도 필드를 유지한다. 지역·기관 조회 모두 임시 비밀번호 제한 세션은 403이다.
- Mailpit: <http://localhost:8025>, SMTP localhost:1025. 로컬은 인증·STARTTLS를 사용하지 않는다.
- Windows에서 JDK 21을 선택하고 `java -version`, `.\gradlew.bat --version`을 확인한다. 전역 Gradle 설치는 필요 없다.

이번 PC의 검증용 JDK는 `C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot`이다. 다른 환경에서는 자신의 JDK 21을 사용한다. 전역 JAVA_HOME은 변경하지 않는다.

## 검사 명령

```powershell
.\gradlew.bat test
.\gradlew.bat integrationTest
.\gradlew.bat bootJar
```

fixture 없는 실제 서버를 실행한 뒤 PowerShell 7에서 `.\scripts\Verify-CommonHttp.ps1`을 실행하면 Health·401·CSRF 계약을 검사한다. 다른 로컬 포트는 `-BaseUrl http://localhost:8081/api`로 지정한다. 쿠키 원문은 출력하지 않는다.

`test`는 MVC·보안·CSRF·설정·메일 실패·PBKDF2 검사이며 DB가 필요 없다. `FoundationWebTests`의 인증 컨트롤러만 fixture다. `integrationTest`는 local 프로필로 실제 PostgreSQL·HTTP·Mailpit을 사용한다. `AuthIntegrationTests`는 실제 A1 컨트롤러·암호 검증·세션을 사용하며 테스트마다 생성한 회원·기관·세션만 정리한다. `DemoSeedIntegrationTests`는 실제 SQL seed의 반복 실행·기존 데이터 보존을 확인하고 롤백한다. IDENTITY 시퀀스의 소모 값은 되돌리지 않는다.

## 암호 인코더와 시연 seed

OPEN-04는 PBKDF2로 확정했다. `DelegatingPasswordEncoder`의 기본 id는 `pbkdf2`, 구현은 `Pbkdf2PasswordEncoder.defaultsForSpringSecurity_v5_8()`이다. 해시에는 `{pbkdf2}` 접두어가 붙는다. salt 16바이트·310,000회·SHA-256·256비트이며, 8~128자와 한글 128자를 자르지 않고 처리한다.

backend 폴더에서 먼저 Gradle 빌드로 의존성을 준비한 뒤 다음처럼 해시를 생성한다. `GRADLE_USER_HOME`을 따로 쓰면 캐시 경로를 맞춘다. Java 도구는 터미널에서 암호를 숨겨 입력받고 해시만 출력한다. 평문을 명령행 인수·파일·로그에 넣지 않는다.

```powershell
.\gradlew.bat classes
$taskGradleCache = if ($env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME } else { Join-Path $env:USERPROFILE '.gradle' }
$taskCryptoJar = Get-ChildItem (Join-Path $taskGradleCache 'caches\modules-2\files-2.1\org.springframework.security\spring-security-crypto\7.1.2') -Recurse -Filter 'spring-security-crypto-7.1.2.jar' | Select-Object -First 1
& "$env:JAVA_HOME\bin\java.exe" --class-path $taskCryptoJar.FullName scripts/GeneratePasswordHash.java
```

seed 적용 순서는 `db/seed/R__02_organization.sql` → `R__03_demo_member.sql`이다. 사용자의 SQL 도구에서 한 트랜잭션으로 순서대로 실행하거나, psql이 있는 환경에서는 backend 폴더에서 아래 명령을 사용한다. 암호는 psql의 숨김 프롬프트에 입력한다.

```powershell
psql -h localhost -p 5432 -U eumi_app -d eumi -W -v ON_ERROR_STOP=1 -1 -f ../db/seed/R__02_organization.sql -f ../db/seed/R__03_demo_member.sql
```

운영은 해당 환경의 연결 정보와 권한으로 실행한다. Flyway seed 마운트 활성화는 인프라 담당 범위다. 기관은 이름·관할 코드·공식 도메인이 같으면 다시 만들지 않고, 회원은 이메일 충돌 시 `ON CONFLICT DO NOTHING`으로 암호·프로필·탈퇴 상태를 보존한다. ID를 명시하지 않아 IDENTITY 시퀀스 수동 보정은 필요 없다. Flyway repeatable seed처럼 직렬 실행한다.

기관의 예상치 않은 PK 충돌은 오류로 드러내며 회원도 이메일 중복만 건너뛴다. 운영에서 명시적 ID 적재 후 시퀀스를 보정하지 않은 문제를 seed가 조용히 숨기거나 자동 보정하지 않는다.

가상 기관은 강남구 `11680`·춘천시 `51110` 관할이며 공식 도메인은 각각 `demo-gangnam.eumi.test`·`demo-chuncheon.eumi.test`다. 기관별 이메일의 로컬 부분은 `demo1`·`demo2`이다. 네 계정은 같은 시연 암호를 서로 다른 salt로 해시했다. 평문은 사용자에게만 전달한다. 기존 계정이 암호를 바꾼 경우 seed를 재실행해도 그 암호가 유지된다.

## 환경변수

AI1은 local에서 기본 `eumi.ai.mode=fake`다. prod는 `EUMI_AI_MODE`를 반드시 명시하고 운영 Compose가 해당 변수를 전달해야 한다. 시연은 fake, 실제 AI 전환은 http를 선택한다. HTTP 모드에는 AI 실행 제한·BE 여유·무응답 판정·취소 대기를 모두 명시해야 한다. 현재 실제 AI 실행 제한은 미확정이며 Fake 기본값은 개발 검증용이다. 설정 표와 `EUMI_AI_*` 변수는 [AI1 인계](docs/ai1/README.md)를 참고한다.

| 이름 | 용도 | local 기본 | prod |
|---|---|---|---|
| DB_URL | JDBC 주소 | localhost:5432/eumi | 필수 |
| DB_USERNAME | 앱 DB 계정 | eumi_app | 필수 |
| DB_PASSWORD | 앱 DB 암호 | 저장소의 개발 전용 설정 | 필수 비밀값 |
| EUMI_AUTH_HASH_KEY | 인증 코드·가입 증명 해시 키 | 공개된 개발 전용 값 | 필수 비밀값 |
| EUMI_MAIL_FROM | 발신 주소 | no-reply@eumi.test | 필수 |
| SMTP_HOST | SMTP 주소 | localhost | 필수 |
| SMTP_PORT | SMTP 포트 | 1025 | 필수 |
| SMTP_USERNAME | SMTP 계정 | 없음 | 인증 사용 시 필수 |
| SMTP_PASSWORD | SMTP 암호 | 없음 | 인증 사용 시 필수 비밀값 |
| SMTP_AUTH | SMTP 인증 | false | 필수 |
| SMTP_STARTTLS_ENABLED | STARTTLS | false | 필수 |

SMTP 연결·읽기·쓰기 타임아웃은 각 5000ms다. prod는 필수 값의 기본값을 제공하지 않는다. SMTP_HOST·PORT·AUTH·STARTTLS_ENABLED·EUMI_MAIL_FROM·EUMI_AUTH_HASH_KEY의 누락·빈값·미해석 placeholder는 기동 실패로 처리한다. `${EUMI_AUTH_HASH_KEY}` 글자가 해시 키로 저장될 수 없도록 바인딩에서도 거절한다. SMTP_AUTH=true인데 계정 또는 암호가 비어 있어도 기동에 실패한다. 실제 비밀값은 문서·로그·Git에 복사하지 않는다.

운영 환경변수는 서버 `/srv/eumi/.env.config`에 보관하고 운영 Compose의 backend `environment`로 컨테이너에 전달한다. 11/3 배포부터 `EUMI_AI_MODE=fake`도 전달한다. Jenkins는 배포를 실행하며, 서버 파일에 값을 추가할 때는 Compose의 전달 항목도 함께 맞춘다.

## 기능별 연결 경계

- 일반 JSON 성공은 `ApiResponse.of(data, request)`를 사용한다. Health와 204, SSE·파일 응답을 감싸지 않는다.
- 업무 오류는 안정적인 코드와 필드 오류를 사용한다. 응답·로그에 암호·코드·가입 증명·SQL·예외 원문을 넣지 않는다.
- A1은 활성 회원·암호·임시 암호 만료를 확인한 뒤 `SessionAuthenticationSupport.establish`를 호출한다. member_id 문자열 principal, 세션 ID 교체, 명시적 SecurityContext 저장과 기존 CSRF 정리를 수행한다. 회원 없음·탈퇴·암호 불일치·임시 암호 만료는 동일한 `INVALID_CREDENTIALS` 401이다.
- 로그인 해시 비교는 트랜잭션 밖에서 실행하고 `/auth/me`의 최신 프로필 조회에만 읽기 전용 트랜잭션을 지정한다.
- A3의 다른 세션·전체 세션 폐기와 암호 변경 트랜잭션 순서는 후속 작업이다.
- 제한 세션은 `/auth/me`, `/auth/logout`, `/members/me/password`와 Health·CSRF 준비만 통과한다. `/auth/me`는 최신 활성 회원을 재조회하며, 탈퇴·임시 암호 만료라면 현재 세션을 무효화하고 401을 반환한다.
- 11/3 사용자 결정에 따라 제한 세션의 재로그인은 403을 유지한다. 먼저 로그아웃한 뒤 다른 계정으로 로그인한다. API-08 설명·오류 목록·403 응답과 예제에 `PASSWORD_CHANGE_REQUIRED`를 반영했다. 비밀번호 변경 후 현재 로그인을 유지하는 API-32 계약과는 별개다.
- A2/A3는 `MailService`의 SMTP 실패를 트랜잭션에 연결한다. 현재 기반만으로 DB·메일 원자성이나 발급 롤백을 검증했다고 해석하지 않는다.
- AI1은 `feat/be-agent`에서 구현했다. FE는 질문 202 뒤 after=questionId로 1초마다 조회하고 완료·실패·취소에서 멈춘다. 병합 전 Claude Code 리뷰를 받는다.
- D1·D2 분석 조회(API-10·11·12)는 `feat/be-analysis`에서 구현했다. 로그인 회원에게 전체 지역의 적재 월·읍면동 인사이트·저장 보고서를 제공하고, 조회가 AI 생성을 실행하지 않는다. 404 기준·DB 상태·검사 결과·FE 확인 순서는 [분석 API 인계](docs/analysis/README.md)를 참고한다.
- C1~C4 사례자·상담(API-19~29)은 본인 담당·같은 기관 권한을 적용한다. 관리번호는 기관 행 잠금·9999 검사·함수 호출·INSERT를 같은 트랜잭션으로 처리한다. [사례자 인계](docs/cases/README.md)의 검사 결과와 관리번호 리뷰 항목을 확인한다.
