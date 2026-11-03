# 지역·기관 회원 조회 구현·검증·MR 인계

기준일: 2026-11-03. 브랜치 `feat/be-region`, 시작 커밋 `8a273f1`(AI1 develop 병합), Jira `S15P31B201-160`.

현재 작업 폴더의 OpenAPI 2.3.0, 공통 응답·세션 규칙, API_DB_매핑의 G1 범위를 기준으로 구현했다. 과거 G1 문서의 API-39~42 미착수 표시는 당시 기록이다. 사용자에게 Git 쓰기 권한이 있으므로 에이전트는 브랜치 변경·fetch·pull·commit·push·병합을 하지 않았다. Docker Compose도 실행하지 않았다.

## 1. 작업 ID·API ID

G1 지역·소속 기관 회원 기준정보 조회. `reference` 패키지에 DTO·Controller·Service·JDBC Repository를 추가했다.

| API | 경로 | 데이터 원천 | data 항목 |
|---|---|---|---|
| API-39 | GET /api/regions/sidos | v_sido | sidoCode, sidoName |
| API-40 | GET /api/regions/sidos/{sidoCode}/sigungus | v_sigungu | sigunguCode, sigunguName |
| API-41 | GET /api/regions/sigungus/{sigunguCode}/dongs | dim_region | dongCode=adm_cd10, dongName=adm_nm |
| API-42 | GET /api/organizations/me/members | member | memberId, name, title |

응답은 네 경로 모두 `200 {success:true,data:[...],meta:{requestId,timestamp}}`다. 페이지 객체나 items로 감싸지 않는다. X-Request-Id와 meta.requestId가 같고 Cache-Control은 no-store다.

## 2. 계약·DTO·오류 코드

계약과 달라진 점: 없음. `ReferenceDataDtos`의 SidoItem·SigunguItem·DongItem·MemberOption은 OpenAPI와 같은 필드만 반환한다. MemberOption.title은 필수 nullable 필드로 유지하며 이메일·전화번호·기관 ID·암호 해시 등은 목록에 포함하지 않는다. 새 오류 코드는 추가하지 않았다.

- sidoCode는 ASCII 숫자 2자리, sigunguCode는 ASCII 숫자 5자리다. 경로 문자열의 자리수·문자가 맞지 않으면 VALIDATION_ERROR 400이다.
- 형식은 맞지만 v_sido·v_sigungu에 상위 코드가 없으면 NOT_FOUND 404다. 유효한 조회 결과가 비어 있으면 배열을 반환하며, 데이터 미적재 시 API-39는 200과 빈 배열이다.
- 지역은 코드 오름차순, 회원은 name·member_id 오름차순이다. 정렬 조건이 지정되지 않은 선택 목록에 일관된 순서를 적용했다.
- v_sido의 이름이 null·빈값·공백이면 null 이름을 정상 응답으로 내보내지 않고 INTERNAL_SERVER_ERROR 500을 반환한다. 서버 WARN에 누락된 sidoCode를 남겨 데이터 담당자가 v_sido의 이름 매핑을 확인할 수 있게 했다. Java에 새로운 시도명 매핑을 복제하거나 마이그레이션을 수정하지 않았다.

## 3. 권한·잠금

네 API 모두 로그인 세션이 필요하다. 기존 SecurityConfig와 PasswordChangeRequiredFilter를 그대로 사용하고, 서비스에서도 AuthService.currentUser로 최신 회원 상태·현재 기관·임시 비밀번호 제한을 확인한다.

- 비로그인: UNAUTHENTICATED 401.
- 임시 비밀번호 제한: PASSWORD_CHANGE_REQUIRED 403.
- 로그인 후 탈퇴한 회원: 최신 DB 확인으로 401.
- 지역 목록: 적재된 전체 지역 기준정보를 조회한다.
- 기관 회원 목록: 클라이언트의 orgId·memberId를 사용하지 않고 로그인한 회원의 현재 DB org_id로 조회한다. withdrawn_at IS NULL인 회원만 반환하고 본인도 포함한다. 임시 비밀번호를 쓰는 다른 회원은 미탈퇴이면 목록에 포함된다.

업무 조회는 읽기 전용 트랜잭션과 SELECT만 사용하며 별도의 행 잠금이나 데이터 변경이 없다. API-42 결과는 선택 시점의 목록이므로 후속 사례자·담당자 변경 API는 저장 시 동일 기관·활성 조건을 다시 확인해야 한다.

## 4. 실행한 검사·결과

환경: JDK 21.0.11·Gradle 9.8.2, 사용자가 실행해 둔 공용 로컬 PostgreSQL·Mailpit.

읽기 전용 사전 확인 당시 dim_region은 47행, 시도는 서울 11·강원 51 두 개, 시군구는 11680·51110이며 시도명 매핑 누락은 0건이었다. 실제 통합 검사는 이 기존 지역 데이터가 적재된 환경을 사용하며 공용 지역 데이터를 추가·수정·삭제하지 않는다.

| 구분 | 결과 |
|---|---|
| 신규 단위·mock 검사 | ReferenceDataServiceTests 4개 통과 |
| 신규 실제 DB·로그인·HTTP 통합 | ReferenceDataIntegrationTests 19개 통과 |
| 전체 단위·MVC·설정·로컬 HTTP stub | 80개 통과, 실패·오류·생략 0 |
| 전체 실제 DB·HTTP·Mailpit 통합 | 58개 통과, 실패·오류·생략 0 |
| bootJar | 통과 |
| 실제 8080 API 확인 | 네 경로의 정상 응답·DTO·코드 정렬·401·400·404·공통 헤더 확인 |

실행 명령(backend 폴더):

```powershell
.\gradlew.bat test --tests '*ReferenceDataServiceTests' integrationTest --tests '*ReferenceDataIntegrationTests' --console=plain
.\gradlew.bat test integrationTest bootJar --console=plain
```

- 단위 검사: 공용 기준 데이터를 지우지 않고 repository·인증 서비스를 mock으로 대체해 지역 미적재 빈 배열과 시도명 null·빈 문자열·공백 매핑 오류의 500·진단을 확인한다.
- 실제 통합: 인증 대체 코드 없이 A1 로그인·PBKDF2·JDBC 세션·HTTP·PostgreSQL을 사용한다. 실제 뷰·행정동과 응답 배열·정렬을 대조한다.
- 기관 회원: 다른 기관·탈퇴 회원 제외, 현재 기관의 임시 암호 회원 포함, 필수 title:null 유지, 필요 없는 필드 비노출, orgId·memberId query 조작 무시, 세션 생성 후 DB 소속 기관 변경 반영을 확인한다.
- 네 API의 401·403, 탈퇴 이후 401, 지역 코드 형식 400과 존재하지 않는 상위 코드 404, 공통 응답·requestId·no-store를 확인한다.
- 테스트는 만든 기관 두 개·회원 네 명과 해당 회원의 세션만 정리한다. 공용 회원·지역·시퀀스를 초기화하거나 되돌리지 않는다. IDENTITY 값 소모는 되돌리지 않는다.

브라우저·Nginx·운영 HTTPS·운영 SMTP 검사는 실행하지 않았다. 이번에는 FastAPI 관련 동작을 추가하지 않았다.

이 작업 폴더의 BackendApplication임을 확인한 기존 8080만 최신 코드로 갱신했다. 실제 HTTP에서 시도 2개·시군구 2개·행정동 47개·시연 회원 소속 기관 회원 2개의 응답을 확인했다. 확인 중 업무 데이터는 생성·수정하지 않았으며 시연 로그인 세션은 로그아웃했다. 최신 백엔드는 FE 실제 API 연결을 위해 8080에 실행해 두었다.

## 5. 남은 것·다음 담당자 인계

- FE는 regionApi의 시도·시군구·행정동과 memberApi의 소속 기관 회원 옵션을 이 네 경로에 연결한다. JSON data는 배열이며 빈 목록도 배열이다. 코드 값은 숫자가 아니라 문자열로 유지한다.
- API-42는 /organizations/me/members이며 /organizations 공개 기관 선택 목록과 다른 경로다. /organizations의 가입용 구현은 이번 범위가 아니다.
- 대시보드 API-10~12는 다음 페이지 작업이다. 이번 브랜치에서 구현하지 않았다.
- 시도명 매핑 누락이 운영 데이터에서 발견되면 경고의 sidoCode를 데이터·DB 담당에게 전달하고, 기존 V 파일을 수정하지 않는 별도 데이터·매핑 변경으로 처리한다.
- backend 외부 파일, SecurityConfig·ErrorCode, 의존성, seed·마이그레이션·infra·docs/api는 변경하지 않았다.
- 사용자가 add·commit·push와 develop 대상 MR·병합을 진행한다. CONTRIBUTING 3.3 기준 Reviewers는 김민준(PM)이며, FE가 사용하는 API 연동 내용도 함께 확인한다.

커밋 제목 제안: `feat: [BE] 지역 및 소속 기관 회원 조회 API 구현`

MR 제목 제안: `feat: [BE] 지역 및 소속 기관 회원 조회 API 구현`

Jira: S15P31B201-160
