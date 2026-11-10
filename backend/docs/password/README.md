# A3 비밀번호 변경 API-32 구현·검증·필수 리뷰 인계

이 문서는 11/4 API-32 구현 당시 기록이다. API-09 비밀번호 찾기와 전체 세션 폐기는 [11/10 A3 인계](2026-11-10_temp-password.md)를 함께 따른다.

2026-11-04. 사용자가 최신 develop `4fb09d3`에서 만든 `feat/be-password`에서 구현했다. 구현·검사를 완료했고 commit·push·MR·병합은 사용자가 진행한다. **A3는 병합 전에 Claude Code 리뷰가 필요하다.** 이번 범위는 비밀번호 변경이며 임시 비밀번호 발급(API-09)은 포함하지 않는다.

## 1. 작업 ID·API ID

- A3 일부, API-32 `PUT /api/members/me/password`.
- Jira: S15P31B201-175 `[BE] 비밀번호 변경과 임시 계정 접근 제한 구현`. 제목·상태를 읽기만 했으며 Jira 등록·수정·상태 변경은 하지 않았다.
- 기준: 이 폴더 OpenAPI 2.3.0, 공통 응답·세션 규칙과 트랜잭션 가이드, V1 회원·JDBC 세션 테이블. 만료 임시 비밀번호를 CURRENT_PASSWORD_MISMATCH 400으로 처리하는 사용자 11/4 결정을 적용했다.
- 새 코드: `auth/password/PasswordChangeController`, `PasswordChangeService`, `PasswordChangeRepository`, `PasswordChangeRequest`. 기존 SessionAuthenticationSupport와 PBKDF2 인코더를 재사용한다.

## 2. 계약과 달라진 점·DTO·오류

계약과 달라진 점: 없음. 이 브랜치에서만 ErrorCode에 아래 업무 코드 두 개를 추가했다. SecurityConfig·PasswordChangeRequiredFilter·DB 마이그레이션·의존성·seed·frontend·infra·docs/api는 변경하지 않았다.

| 항목 | 동작 |
|---|---|
| 입력 | currentPassword 1~128 코드 포인트, newPassword 8~128 코드 포인트와 영문·숫자·특수문자 포함. 두 값 모두 trim하지 않음 |
| 성공 | 200 `data={user:LoginUser}`. user 9개 필드, mustChangePassword=false, title=null도 유지 |
| CURRENT_PASSWORD_MISMATCH | 400, `현재 비밀번호가 일치하지 않습니다.`. 현재 암호 불일치·만료 임시 암호·잠금 전후 해시 변경을 같은 코드로 처리 |
| NEW_PASSWORD_EQUALS_CURRENT | 400, `새 비밀번호는 현재 비밀번호와 달라야 합니다.` |
| 형식 오류 | 400 VALIDATION_ERROR와 currentPassword/newPassword 필드 오류. 누락·추가 JSON 속성은 INVALID_JSON |
| 인증·CSRF | 비인증·탈퇴·유효 JDBC 세션 없음은 401. CSRF 실패는 CSRF_INVALID 403 |

- 새 암호 규칙은 OpenAPI 정규식 그대로 적용한다. Unicode 길이는 코드 포인트 기준이며 앞뒤 공백도 암호의 일부다. 암호를 임의로 자르거나 정규화하지 않는다.
- 현재 암호 검증 후 새 암호를 현재 해시와 비교해 동일 암호를 거절한다. 잘못된 해시의 matches 예외는 현재 암호 불일치로 처리한다.
- 만료 임시 암호 요청은 일반 AuthService.currentUser의 401 경로로 보내지 않는다. 기존 제한 세션에서 API-32를 호출하면 만료 여부를 별도로 확인하고 CURRENT_PASSWORD_MISMATCH 400으로 응답한다.
- PasswordChangeRequest와 조회 Account의 toString은 내용을 가린다. 암호·해시·쿠키·세션 ID를 업무 로그나 오류 메시지에 넣지 않는다. 응답은 새 user만 반환한다.

## 3. 권한·잠금·DB 커밋·세션 저장

- memberId는 인증된 SessionPrincipal에서만 얻고 현재 세션 ID도 HttpServletRequest의 세션에서 얻는다. 요청 본문으로 대상 회원·세션을 지정할 수 없다. 기존 필터의 API-32 허용 규칙을 그대로 사용하므로 제한 세션에서도 호출할 수 있다.
- DB에서 현재 회원의 암호 정보를 조회한 뒤 커넥션을 반환한다. 현재 암호 비교·동일 새 암호 비교·새 PBKDF2 해시 생성은 트랜잭션과 바인딩 커넥션 없이 수행한다.
- 이후 한 DB 트랜잭션에서 기관 FOR UPDATE → 본인 회원 FOR UPDATE → 현재 JDBC 세션 FOR UPDATE 순서로 잠근다. 회원 활성 상태·기관·기존 해시가 바뀌지 않았는지·임시 암호 만료·현재 세션의 principal/유효 기간을 재확인한다. 잠금 안에서 PBKDF2를 다시 계산하지 않는다.
- 새 해시 저장·temp_password_expires_at=NULL·updated_at 갱신 → 같은 memberId 문자열의 다른 세션 삭제 → 최신 LoginUser 재조회가 한 트랜잭션이다. 삭제는 `principal_name=memberId AND session_id<>현재ID`인 SQL로 실행해 회원 변경과 같은 트랜잭션에 참여한다. 다른 회원의 세션은 건드리지 않으며 속성은 FK CASCADE로 정리된다.
- **DB 커밋 성공 후** 컨트롤러가 기존 SessionAuthenticationSupport.establish를 호출한다. 기존 전략이 changeSessionId → CSRF 토큰 삭제 → mustChangePassword=false principal의 SecurityContext 저장을 수행한다. DB 실패 시 이 단계로 가지 않아 세션 ID도 바뀌지 않는다.
- Spring Session 4.1.1 소스를 확인했다. 기본 ON_SAVE에서 실제 현재 세션의 JDBC 저장과 SESSION 쿠키 반영은 SessionRepositoryFilter의 응답 커밋/요청 종료 단계다. 회원 DB 트랜잭션과 Servlet 응답 저장 전체가 하나의 원자적 작업이라고 주장하지 않는다. 성공 응답 후 새 ID·principal 영속화, 이전 ID 소실, 다른 세션 401을 실제 HTTP와 DB에서 검사했다.
- 다른 세션 삭제 후 예외를 주입해 해시·임시 만료·다른 세션 행이 함께 롤백되고 현재 ID도 유지되는지 검사했다. 이는 DB 커밋 전 실패 검사이며 응답 커밋 시점의 세션 저장 장애를 주입한 검사는 아니다.

## 4. 실행한 검사와 결과

JDK 21.0.11, Git Bash, 실제 공용 PostgreSQL localhost:5432(eumi_app, Asia/Seoul)과 기존 Mailpit을 사용했다. 에이전트는 Docker Compose·Flyway·Git 쓰기 명령을 실행하지 않았다.

```bash
cd /c/Users/SSAFY/Desktop/PJT3/S15P31B201/backend
export JAVA_HOME='C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot'
./gradlew.bat test integrationTest bootJar --console=plain
```

2026-11-04 16:58~16:59 KST 실행, BUILD SUCCESSFUL이다.

| 구분 | 결과 | 범위 |
|---|---|---|
| DB 없는 단위/fixture 전체 | 132개 통과 | 기존 124 + PasswordChangeRequestTests 8. 실패·오류·생략 0 |
| 실제 PostgreSQL·HTTP 통합 전체 | 193개 통과 | 기존 179 + PasswordChangeIntegrationTests 14. 실패·오류·생략 0 |
| bootJar | 통과 | 이번 main 코드가 포함된 실행 jar |
| 실제 8080 jar HTTP | 통과 | 실제 임시 암호 로그인·제한 확인 → API-32 200·user 9개 필드·ID 교체 → 현재 회원 API 200·다른 본인 세션 401·다른 회원 세션 200 → 불일치/동일 암호 400 → 이전 암호 로그인 401·새 암호 로그인 200 |
| git diff --check | 통과 | 문서 포함 공백 검사 |
| FE 브라우저·운영 HTTPS·응답 세션 저장 장애·동시 요청 전수 | 미실행 | 후속 리뷰·FE·운영 확인 범위 |

단위 8개는 새 암호 형식 5가지, Unicode 128/129 코드 포인트 경계, trim하지 않는 입력·toString 가림을 검사한다.

실제 통합 14개는 정상 변경·해시/updated_at 갱신·다른 본인 세션 폐기·다른 회원 세션 보존·이전 ID 차단·현재 principal 영속화·새 암호 로그인, 임시 암호 세션의 제한 해제, 불일치와 만료의 같은 오류·실패 시 세션 유지, 동일 암호 거절, 공백·128 코드 포인트 암호, PBKDF2의 트랜잭션/커넥션 비점유, 비교 후 해시 변동 재확인, 다른 세션 삭제 직후 실패 시 DB 롤백, 잘못된 새 암호 5가지, 길이·추가/누락 필드·비인증·탈퇴·CSRF를 검사한다. 성공 시 XSRF-TOKEN의 마지막 삭제 헤더가 Max-Age=0·Path=/인지도 확인한다.

실제 A1 로그인·PBKDF2·JDBC 세션을 사용하며 인증 대체 컨트롤러가 없다. PasswordEncoder Spy는 실제 계산을 호출하며 비교·생성 시 트랜잭션 경계를 관찰한다. 해시 변경과 DB 실패 두 경우만 자체 데이터 변동·예외를 주입했다. 통합 클래스의 minimum-idle=1은 여러 테스트 컨텍스트가 공용 DB 연결 한도를 소모하지 않도록 한 테스트 전용 설정이다.

각 검사와 8080 보조 검증은 메모리에서 합성 암호를 만들고 자체 기관·회원·해당 principal 세션만 정리했다. 공용 계정의 암호나 세션은 변경하지 않았다. 공용 데이터·시퀀스 초기화와 되돌림도 없다. 암호 원문과 쿠키·세션 값은 파일·로그·보고에 남기지 않는다.

XML: `build/test-results/test/`, `build/test-results/integrationTest/`. HTML: `build/reports/tests/`. 8080 보조 도구와 런타임 로그는 무시되는 build 아래에만 있다.

## 5. 남은 것·필수 리뷰·FE 인계

- **A3 필수 Claude Code 리뷰 후 develop에 병합한다.** 리뷰는 새 비밀번호 검증, 잠금 전후 해시·만료 재확인, DB와 다른 세션 삭제의 롤백, 현재 ID 교체·principal 영속화·CSRF 재준비 경계를 중점으로 본다.
- 새 jar를 local/Fake 모드로 8080에 실행해 두었다. 문서 작성 당시 PID 12916이며 이후 사용할 때 실제 포트·프로세스를 확인한다.
- FE는 현재/새 암호를 trim하지 않고 전송한다. 성공 응답의 data.user로 인증·메뉴 상태를 갱신하고 CSRF를 다시 준비한다. 제한 상태였어도 현재 로그인을 유지한 채 일반 화면으로 이동할 수 있다. 다른 브라우저의 같은 회원은 다음 요청에서 401이 정상이다.
- CURRENT_PASSWORD_MISMATCH는 현재 암호 칸, NEW_PASSWORD_EQUALS_CURRENT는 새 암호 칸의 오류로 표시한다. 만료 사실을 별도 메시지로 노출하지 않는다. 형식 오류는 fieldErrors 필드 이름으로 처리한다.
- FE 브라우저·운영 HTTPS 및 응답 커밋 시 세션 저장 장애는 아직 검증하지 않았다. 동시에 진행 중인 로그인·다른 요청과 세션 회전의 경합 세부는 AGENTS의 후속 동시성 점검 범위다. DB 커밋 전 롤백 검사와 이 범위를 혼동하지 않는다.
- 임시 비밀번호 발급(API-09)·회원가입·탈퇴는 별도 작업이다. Jira 완료·MR·병합은 사용자가 진행한다.

제안 커밋 제목: `feat: [BE] 비밀번호 변경과 다른 세션 폐기 구현`

제안 커밋 본문 마지막 줄: `Jira: S15P31B201-175`

MR 대상: develop. 위 1~5절을 MR 설명으로 사용하고 A3 리뷰 결과를 추가한다.
