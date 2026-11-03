# A1 리뷰 후속 보완

기준일: 2026-11-03. Jira: `S15P31B201-172`.

현재 작업 브랜치는 `fix/be-login-review`, 코드 보완 커밋은 `80acc7d`이며 로컬 `origin/develop`은 `494ddc4`다. Claude Code 재점검에서 병합 차단 문제·새 버그가 없다는 결과를 전달받았다. 이 문서와 API-08 계약의 추가 보완은 현재 작업 트리에 있으며 아직 커밋하지 않았다. 에이전트는 Git 쓰기 명령·브랜치 변경·Docker Compose를 실행하지 않았다.

초기 보완 착수 당시에는 `feat/be-login`·`69821b0`, `origin/develop`·`422227c`였고 두 커밋의 `backend/`·`db/seed/` 차이가 없음을 확인했다. 이후 사용자가 브랜치 이름 변경·커밋·push를 진행했다.

## 1. 작업·API

- A1 후속: API-08 로그인, API-01 최신 프로필, API-02 로그아웃.
- PBKDF2의 커넥션 점유 범위, 실패 문구, seed의 충돌 처리 보완.
- Claude Code가 제안한 추가 검사와 사용자가 확정한 제한 세션 재로그인 정책 검증.

## 2. 계약·DTO·오류 코드

- DTO·오류 코드 이름 변경 없음.
- `INVALID_CREDENTIALS` 문구를 OpenAPI 2.3.0의 `이메일 또는 비밀번호가 일치하지 않습니다.`로 수정했다.
- 사용자 결정: 임시 비밀번호 제한 세션은 `POST /auth/login`을 `403 PASSWORD_CHANGE_REQUIRED`로 거절한다. 로그아웃 후 다른 계정으로 로그인한다. 기존 필터 동작은 변경하지 않았다.
- 비밀번호 변경 후 현재 로그인은 유지하고 세션 ID를 교체한다. 다른 세션은 폐기한다. 이 동작은 API-32의 기존 계약이며 구현은 A3 범위다.
- **API-08 문서 보완 완료:** 사용자 요청에 따라 현재 저장소의 로그인 설명·오류 목록·403 설명과 예제에 제한 세션의 `PASSWORD_CHANGE_REQUIRED`를 반영했다. `x-temporary-password-allowed: false`는 유지했다. DTO·런타임 동작 변경 없이 이미 확정한 정책을 문서와 맞췄다.
- 이번 `docs/api/openapi.json` 수정은 사용자의 명시적인 문서 보완 요청을 우선한 예외다. 루트 AGENTS.md의 평소 BE 수정 범위와 달리 이 계약 파일도 수정했으며, 다른 작업 폴더의 계약 사본·외부 API 표는 수정하지 않았다.

기관 seed는 기존의 범용 `ON CONFLICT DO NOTHING`을 제거하고 `WHERE NOT EXISTS`로 정상 중복을 방지한다. 회원 seed는 `ON CONFLICT (email_normalized) DO NOTHING`으로 범위를 좁혔다. 사용자 전달 리뷰 3번의 보완안을 반영한 것으로, 반복 실행 시 데이터 보존은 유지하면서 예상치 않은 PK 충돌을 오류로 드러낸다.

## 3. 트랜잭션·권한·잠금

- AuthService의 클래스 전체 트랜잭션을 제거하고 `currentUser`에만 읽기 전용 트랜잭션을 지정했다.
- 로그인은 JDBC 조회가 커넥션을 반환한 뒤 PBKDF2를 계산한다. 현재 호출자는 트랜잭션 없는 AuthController다.
- `NOT_SUPPORTED`도 검토했으나 기본 트랜잭션 동기화 아래에서 JDBC 커넥션이 비교 시점까지 바인딩되는 것이 실제 통합 검사에서 확인되어 사용하지 않았다.
- 실제 DB·PBKDF2를 사용하는 회귀 검사로 비교 시점에 활성 트랜잭션·바인딩된 JDBC 커넥션이 없음을 확인한다. 인코더 spy는 경계를 관찰한 뒤 실제 인코더를 호출하며 인증을 대체하지 않는다.
- 동시 로그인 처리량이나 풀 고갈에 대한 부하 측정은 하지 않았다. 새 행 잠금·권한 변경은 없다.
- seed 충돌 검사는 `pg_temp` 임시 테이블과 독립적인 IDENTITY를 사용한다. 공용 테이블·공용 시퀀스를 초기화하거나 뒤로 돌리지 않는다.

## 4. 실행한 검사

JDK 21.0.11·Gradle 9.8.2, 실제 로컬 PostgreSQL 17.11·Mailpit을 사용했다.

실행 명령: `gradlew.bat test integrationTest bootJar --console=plain`.

| 구분 | 11/3 결과 |
|---|---|
| DB 없는 단위·fixture | 36개 통과, 실패·오류·생략 0 |
| 실제 PostgreSQL·HTTP·Mailpit 통합 | 17개 통과, 실패·오류·생략 0 |
| bootJar | 통과 |

위 단위·통합·빌드 결과는 11/3 10:49~10:52 KST 실행 기록이다. Claude Code는 `80acc7d`의 코드·class·XML을 대조했으며 Gradle·HTTP·브라우저를 재실행하지 않았다. 이후 이번 계약·인계 문서 수정에는 JSON 구조·내부 참조·허용된 변경 범위를 확인했으며 애플리케이션 검사는 추가 재실행하지 않았다.

추가·강화한 항목:

- 로그인 PBKDF2 비교 시 활성 트랜잭션·바인딩된 JDBC 커넥션 없음.
- 로그인·로그아웃의 최종 `XSRF-TOKEN` 헤더가 빈값·`Max-Age=0`·`Path=/`임을 확인. 같은 응답에서 먼저 쿠키가 설정될 수 있어 마지막 헤더를 검사한다.
- `/auth/me`가 `title: null` 필드를 유지함을 확인.
- 유효 임시 암호로 로그인한 뒤 DB의 만료 시각을 과거로 바꾸면 me 401·JDBC 세션 삭제·쿠키 삭제 확인.
- 제한 세션에서 다른 계정의 올바른 자격 증명으로 로그인해도 403이며 기존 회원을 유지함을 확인. 로그아웃 후에는 새 계정으로 로그인 성공.
- 로그인 실패 네 종류의 코드뿐 아니라 계약 문구까지 검사.
- prod 필수 변수 6개 각각 빈 문자열이면 기동 실패 확인.
- seed 회원의 기관 FK가 이메일 도메인·관할 코드와 일치함을 확인.
- 기관·회원의 예상치 않은 PK 충돌이 각각 SQLSTATE 23505로 드러남을 확인.

통합 검사의 HTTP 서버는 임의 포트에서 실행했다. 기존 8080 서버·브라우저·Nginx·운영 HTTPS·운영 SMTP의 이번 보완 재검증과 구분한다. seed 테스트의 데이터 변경은 롤백하고, 로그인 테스트는 자신이 만든 회원·기관·세션만 정리했다.

## 5. 문서 반영·다음 작업

현재 작업 폴더의 `docs/api/openapi.json` 안 `paths["/auth/login"].post`에 다음 내용을 반영했다. OpenAPI 버전은 2.3.0을 유지한다.

1. `x-temporary-password-allowed: false` 유지.
2. `x-error-codes`에 `PASSWORD_CHANGE_REQUIRED` 추가.
3. `responses["403"].description`에 `CSRF_INVALID`와 `PASSWORD_CHANGE_REQUIRED` 명시.
4. `responses["403"].content["application/json"].examples.PASSWORD_CHANGE_REQUIRED` 추가. 기존 `/agent/questions`의 같은 오류 예제를 재사용했다.
5. 제한 세션에서 다른 계정으로 로그인하려면 먼저 로그아웃해야 한다는 정책을 설명에 명시.

현행 필터·통합 테스트·현재 저장소 API-08 문서는 사용자 결정과 일치한다. 새 문서 변경을 현재 브랜치에 추가 커밋·push한 뒤 MR에 포함한다. FE 담당자는 문서 변경을 확인하고 로그인 화면에서 `PASSWORD_CHANGE_REQUIRED`를 직접 처리한다. 다른 작업 폴더의 계약 사본은 병합 후 사용자가 Git으로 동기화하며 외부 API 표의 API-08도 별도로 맞춘다.

A3 인계:

- API-09 임시 암호 발급은 회원의 모든 세션을 폐기한다.
- API-32는 현재 임시 암호의 만료를 DB에서 다시 검사한다. 변경 후 temp 만료를 비우고 다른 세션을 삭제하며, 현재 세션 ID를 바꾸고 제한 principal을 해제한다.
- API-32·탈퇴의 잠금 안에서 해시 계산으로 커넥션을 오래 점유하지 않도록 검토한다. 잠그기 전에 암호를 비교한다면, 잠금 후 동일한 `password_hash`인지와 최신 회원·임시 암호 상태를 다시 확인해야 한다.
- 같은 브라우저의 재인증은 세션 ID를 바꾸지만 모든 속성을 비우지는 않는다. AI1 등에서 세션 속성을 추가하면 회원 전환 시 데이터 잔존 여부를 재검토한다.

seed 자동 마운트는 이번 범위에서 변경하지 않았다. 운영에 시연 계정을 넣을지와 Flyway 연결은 사용자·인프라 담당 결정 사항이다.

기존 A1은 develop에 병합됐고, 코드 후속 커밋 `80acc7d`는 `fix/be-login-review`에서 재점검을 통과했다. 이번 문서 보완까지 같은 MR에 포함해 develop으로 병합한다. Git 작업은 사용자가 수행하며 AI1은 사용자가 새 브랜치를 준비한 뒤 진행한다.

커밋 제목 제안: `fix: [A1] 로그인 검증과 seed 오류 처리 보완`

MR 제목 제안: `fix: [A1] 로그인 커넥션 점유와 계약 정합성 보완`

Jira: S15P31B201-172
