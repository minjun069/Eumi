# G1 검증 결과와 재현 방법

기준일: 2026-10-31. B0~B4 구현 검사를 완료했다. fixture 검사 15개·로컬 통합 검사 4개·실제 jar HTTP 검사 5개가 통과했다. G1 전체와 A1~A3 업무 완료를 뜻하지 않는다.

## 실행 환경

- 기준 develop 99e6356, 작업 브랜치 feat/be-common-foundation
- Temurin JDK 21.0.13+9, Gradle 9.8.2, Boot 4.1.2
- 로컬 Docker PostgreSQL 17.11, Flyway 13.11.1, Mailpit v1.27
- 실제 DB 계정 eumi_app. 지역·기관·회원 초기 데이터 각 0건

## 검사 분리

| 명령 또는 대상 | 실제 환경과 fixture 구분 | 현재 결과 |
|---|---|---|
| gradlew.bat --version | 실제 JDK·Wrapper | 통과 |
| dependencies --configuration testRuntimeClasspath | 의존성 그래프 조회 | 통과 |
| Docker·Flyway·권한 조회 | 실제 PostgreSQL 읽기 전용 | 통과 |
| gradlew.bat test | MockMvc·설정·SMTP 실패 fixture | 15개 통과, 실패·오류·생략 0 |
| gradlew.bat integrationTest | 실제 PostgreSQL·HTTP·Mailpit, 인증만 fixture | 4개 통과, 실패·오류·생략 0 |
| gradlew.bat bootJar | 실제 실행 jar 빌드 | 통과 |
| scripts/Verify-CommonHttp.ps1 | fixture 컨트롤러 없는 실제 jar의 HTTP | 5개 통과 |
| jar 내용 확인 | 테스트 컨트롤러 포함 여부 | fixture·테스트 클래스 없음 |
| git diff --check | 변경 파일 공백·충돌 표시 검사 | 통과 |

## 재현

backend 폴더에서 JDK 21과 로컬 서비스를 준비하고 실행한다.

```powershell
.\gradlew.bat test
.\gradlew.bat integrationTest
.\gradlew.bat bootJar
```

이번 최종 실행 명령은 `.\gradlew.bat test integrationTest bootJar --console=plain`이며 종료 코드 0, BUILD SUCCESSFUL이었다. 단위 검사와 통합 검사의 Gradle XML 결과에서 실패·오류·생략 수를 각각 다시 확인했다.

test는 실제 로그인 자격 검증을 하지 않는다. integrationTest의 로그인 경로도 src/test fixture이며 204를 반환하므로 A1의 200 data.user 계약을 구현했다고 해석하면 안 된다. JDBC principal 저장·다음 HTTP 요청 복원·ID 교체·이전 ID 폐기·세션 삭제 후 401을 검사한다. 생성한 테스트 세션만 정리하고, 사람이 확인할 수 있도록 Mailpit의 합성 테스트 메일은 유지한다.

## 실제 jar HTTP 검사

별도의 빈 로컬 포트 53671에서 local 프로필의 실행 jar를 기동하고 다음 명령을 실행했다. 이 서버는 검사가 끝난 뒤 종료했다. PostgreSQL·Mailpit 컨테이너는 유지한다.

```powershell
.\scripts\Verify-CommonHttp.ps1 -BaseUrl http://127.0.0.1:53671/api
```

| 검사 | 실제 결과 |
|---|---|
| HTTP-01 CSRF 준비 | 204·빈 본문·Path=/·HttpOnly=false·SameSite=Lax·Domain 미지정 |
| HTTP-02 Health | 200·원문 status=UP·success envelope 없음 |
| HTTP-03 보호 요청 | 401 JSON·UNAUTHENTICATED·UUID 헤더/본문 일치·no-store·리다이렉트 없음 |
| HTTP-04 CSRF 실패 | 누락·잘못된 헤더 모두 403 CSRF_INVALID |
| HTTP-05 raw CSRF | CSRF 통과 후 아직 없는 로그인 컨트롤러의 404. 실제 로그인 성공으로 처리하지 않음 |

JDBC 인증 fixture에서는 세션 principal 910000001, 7200초 만료, 속성 저장·다음 요청 복원, ID 교체와 이전 ID 소실, 삭제 후 401을 확인했다. local SESSION 쿠키의 Path=/api·HttpOnly·Lax·Secure=false·Domain 미지정을 실제 HTTP 헤더로 확인했다. Secure=true인 CSRF 쿠키는 MVC fixture로 확인했다. 운영 HTTPS의 SESSION Secure·브라우저 동작은 미검증이다.

Mailpit은 합성 수신자·고유 제목의 메일을 실제 SMTP로 접수했고 목록에서 고유 제목을 찾은 뒤 해당 메일의 본문을 다시 읽어 수신을 확인했다. 기존 메일 본문을 열거나 삭제하지 않았다. 테스트가 보낸 메일은 Mailpit 화면에서 확인할 수 있도록 유지했다. 최종 확인 시 메일함에는 합성 테스트 메일 2건이 있었다.

검사 후 spring_session과 spring_session_attributes의 행 수는 각각 0이었다. 검사에서 만든 세션이 정리됐음을 확인했다. 마지막 컨테이너 상태는 postgres·mailpit healthy, flyway Exited (0)이다. Gradle 실행에는 deprecated API와 JVM CDS 경고가 있었지만 테스트·빌드 실패는 없었다.

## 실행 중 발견하고 수정한 항목

1. 테스트의 JdbcSession 구체 타입이 공개되지 않아 Session 인터페이스로 받도록 수정했다.
2. MockMvc 오류 dispatch는 요청 post-processor로 DispatcherType을 지정했다.
3. 테스트 컨트롤러의 중복 등록을 제거하고 TestComponent로 일반 스캔에서 제외했다.
4. Security의 csrf() 테스트 보조기가 Cookie 저장소를 바꾸는 영향을 확인하고, CSRF 준비 API가 발급한 실제 쿠키를 헤더에 넣도록 모든 양성 검사를 바꿨다.
5. SPA 처리기는 첫 요청에서도 쿠키를 준비할 수 있다. 유효 쿠키를 가진 CSRF 준비 재호출에서 Set-Cookie가 생략되는 정상 동작을 반영해 최초 발급과 재호출을 나눠 검사했다.

## 후속 검증

- A1 실제 암호 검증·로그인·로그아웃·최신 회원 복원
- A2 코드·가입 증명·가입·동시 중복·SMTP 실패와 DB rollback
- A3 임시 암호 24시간·제한 해제·다른 세션 또는 전체 세션 폐기·트랜잭션 순서
- FE·실제 브라우저에서 쿠키 가독성·Secure·CSRF 재준비·401/403 분기
- 운영 HTTPS·Nginx·SSE·SMTP 최종 배달

검사 로그와 테스트 리포트는 backend/build 아래 생성되며 Git 추적 대상이 아니다. 비밀값·쿠키·입력 원문이 포함된 덤프를 MR이나 기록에 첨부하지 않는다.
