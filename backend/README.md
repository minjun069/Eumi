# 이음이 백엔드 실행과 공통 기반

Java 21 · Spring Boot 4.1.2 · Gradle Wrapper 9.8.2를 사용한다. G1의 B0~B4는 공통 응답·세션·보안·CSRF·메일 기반이다. 실제 로그인·가입·암호 변경과 G1 지역·기관 회원 API의 완료를 뜻하지 않는다.

## 먼저 읽을 기록

- [11월 1일 재개 안내와 운영 설정 검토 사항](docs/g1/2026-11-01_이어가기.md)
- [G1 현재 범위와 인계](docs/g1/README.md)
- [G1 구현 결정](docs/g1/decisions.md)
- [G1 검증 결과와 재현 방법](docs/g1/verification.md)
- [협업 규칙](../CONTRIBUTING.md), [인증 결정](../docs/decisions/login-sse.md), [로컬 DB·메일](../infra/README.md)

최종 API 계약은 저장소 밖 전달 문서 `산출물/개발_참조/openapi.json`의 info.version 2.2.0이다. 공통 응답·세션 규칙과 트랜잭션 가이드를 함께 읽는다. 전달 문서가 없는 환경에서는 계약을 확보한 뒤 업무 API를 구현한다. 저장소 `docs/README.md`와 이전 BE-FE 인계의 명세 작성 예정 문구는 최신 상태가 아니다.

## 로컬 실행

Docker Desktop Linux 엔진이 실행 중이어야 한다. 저장소 루트에서 먼저 로컬 서비스를 준비한다.

```powershell
Set-Location infra
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
docker compose up -d
docker compose ps -a
docker compose logs flyway
Set-Location ../backend
.\gradlew.bat bootRun
```

정상 상태는 postgres healthy, flyway Exited (0), mailpit healthy다. Flyway가 eumi_owner로 V1~V6·afterMigrate를 적용한다. BE는 eumi_app으로 접속하고 Session JDBC의 테이블 자동 생성은 끈다. 기존 .env와 볼륨을 덮어쓰거나 삭제하지 않는다.

- Health: <http://localhost:8080/api/health> → `200 {"status":"UP"}`. DB readiness 검사가 아니다.
- CSRF 준비: `GET /api/auth/csrf` → 204·본문 없음·XSRF-TOKEN 쿠키.
- 비인증 보호 요청: `GET /api/auth/me` → 401 공통 오류. 실제 A1 컨트롤러는 아직 없다.
- Mailpit: <http://localhost:8025>, SMTP localhost:1025. 로컬은 인증·STARTTLS를 사용하지 않는다.
- Windows에서 JDK 21을 선택하고 `java -version`, `.\gradlew.bat --version`을 확인한다. 전역 Gradle 설치는 필요 없다.

이번 PC의 검증용 JDK는 저장소 밖 `C:\Users\rapal\Desktop\자율PJT\.tools\eumi-jdk21\jdk-21.0.13+9`, Gradle 캐시는 같은 .tools 아래 `gradle-home`이다. 다른 환경에서는 자신의 JDK 21을 사용한다. 전역 JAVA_HOME은 변경하지 않았다.

## 검사 명령

```powershell
.\gradlew.bat test
.\gradlew.bat integrationTest
.\gradlew.bat bootJar
```

fixture 없는 실제 서버를 실행한 뒤 PowerShell 7에서 `.\scripts\Verify-CommonHttp.ps1`을 실행하면 Health·401·CSRF 계약을 검사한다. 다른 로컬 포트는 `-BaseUrl http://localhost:8081/api`로 지정한다. 쿠키 원문은 출력하지 않는다.

`test`는 MVC·보안·CSRF·설정·메일 실패 fixture 검사이며 DB가 필요 없다. `integrationTest`는 local 프로필로 실제 PostgreSQL·HTTP·Mailpit을 사용하므로 위 인프라가 필요하다. 인증 자격 검증은 src/test의 fixture로 대체하며 실제 A1 로그인 검사와 구분한다. 두 결과와 남은 항목은 검증 문서에 기록한다.

## 환경변수

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

SMTP 연결·읽기·쓰기 타임아웃은 각 5000ms다. prod는 필수 값의 기본값을 제공하지 않는다. SMTP_AUTH=true인데 계정 또는 암호가 비어 있으면 기동에 실패한다. 해시 키와 발신 주소도 비어 있으면 기동에 실패한다. 실제 비밀값은 문서·로그·Git에 복사하지 않고 .env와 비밀값 파일은 추적하지 않는다. 전달은 기존 협업 규칙의 비공개 경로를 사용한다. infra/.env는 Compose용이며 호스트에서 실행하는 BE에 자동으로 로드되는 파일이 아니다.

운영 Compose·Jenkins의 변수 주입은 별도 인프라 작업이다. backend에서 요구하는 새 변수를 운영에 주입하기 전에는 prod 기동이 실패할 수 있다.

## 기능별 연결 경계

- 일반 JSON 성공은 `ApiResponse.of(data, request)`를 사용한다. Health와 204, SSE·파일 응답을 감싸지 않는다.
- 업무 오류는 안정적인 코드와 필드 오류를 사용한다. 응답·로그에 암호·코드·가입 증명·SQL·예외 원문을 넣지 않는다.
- A1은 자격 검증 이후 `SessionAuthenticationSupport.establish`를 호출한다. member_id 문자열 principal, 세션 ID 교체, 명시적 SecurityContext 저장과 기존 CSRF 정리를 수행한다.
- A1의 실제 로그아웃, A3의 다른 세션·전체 세션 폐기와 트랜잭션 순서는 후속 업무에서 구현한다.
- 제한 세션은 `/auth/me`, `/auth/logout`, `/members/me/password`와 Health·CSRF 준비만 통과한다. 실제 제한 여부·활성 회원·암호 만료 판정은 A1/A3가 최신 DB로 확인한다.
- A2/A3는 `MailService`의 SMTP 실패를 트랜잭션에 연결한다. 현재 기반만으로 DB·메일 원자성이나 발급 롤백을 검증했다고 해석하지 않는다.
- 암호 인코더와 seed의 8~128자 정합성 OPEN-04는 아직 미결정이다.
