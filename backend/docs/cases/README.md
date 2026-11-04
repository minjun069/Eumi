# 사례자·상담 C1~C4 구현·검증·MR 인계

2026-11-04. 시작 커밋 `58092bb`, 브랜치 `feat/be-case`. 기능 구현은 `7d7f224`로 commit·push되었으며 Claude Code의 C3 리뷰에서 병합 차단 문제 없음·관리번호 5개 항목 적합 판정을 받았다. 이 문서는 리뷰에서 발견한 타 기관 사례자 행 잠금 범위를 보완한 내용까지 포함한다. 11/3의 AI1·지역·대시보드 병합·운영 배포는 완료된 선행 작업이다.

## 1. 작업 ID·API ID

C1~C4, API-19~29. Jira S15P31B201-192(사례자 CRUD)·193(상담 CRUD)·194(접근 권한)를 사용자 요청으로 ‘진행 중’으로 옮기고 다시 조회해 확인했다. 172(로그인)·214(AI1)·160(대시보드)는 Jira에서 이미 ‘완료’다. 사례자 3건은 코드 구현 완료와 MR 리뷰·병합 완료를 구분하여 진행 중으로 유지한다.

| API | 메서드·경로 | 성공 |
|---|---|---|
| API-19 | GET /api/cases | 200 CasePage |
| API-20 | GET /api/cases/{caseId} | 200 CaseDetail |
| API-21 | POST /api/cases/duplicate-check | 200 duplicates 배열 |
| API-22 | POST /api/cases | 201 caseId·managementNo |
| API-23 | PUT /api/cases/{caseId} | 204 |
| API-24 | DELETE /api/cases/{caseId} | 204 |
| API-25 | GET /api/cases/{caseId}/consultations | 200 배열 |
| API-26 | GET /api/cases/{caseId}/consultations/{consultationId} | 200 ConsultationDetail |
| API-27 | POST /api/cases/{caseId}/consultations | 201 consultationId |
| API-28 | PUT /api/cases/{caseId}/consultations/{consultationId} | 204 |
| API-29 | DELETE /api/cases/{caseId}/consultations/{consultationId} | 204 |

`cases` 패키지의 Controller·DTO·Service·JDBC Repository를 추가했다. backend/README.md의 운영 변수 전달 안내도 서버 `/srv/eumi/.env.config`와 운영 Compose의 backend environment 기준으로 정리했다. 다른 작업 폴더·FE·docs/api·db/migration·seed·infra·Jenkinsfile·의존성은 수정하지 않았다. Git 쓰기 명령·Docker Compose·Flyway는 실행하지 않았다.

## 2. 계약과 달라진 점·DTO·오류 코드

계약과 달라진 점: **API-23 409 미구현(조건 미정, 11/4 결정)**. 사용자가 전달한 11/4 인프라 결정에 따라 STATE_CONFLICT 조건은 11/9 동시성 작업에서 정한다. 나머지는 현재 저장소 OpenAPI 2.3.0, 공통 응답·세션 규칙, 트랜잭션 가이드와 프로토타입 상세 계약을 따른다. 과거 프로토타입의 별도 번호 시퀀스 대신 현재 DB 함수의 MAX 기반 동작을 적용했다.

- 새 ErrorCode는 MANAGEMENT_NUMBER_EXHAUSTED 409이며, 등록 시 해당 기관·발급 연도 최대 번호가 9999이면 반환한다. 등록·수정의 부적합 담당자는 VALIDATION_ERROR 400이다. API-23은 STATE_CONFLICT를 반환하지 않으며, 사용하지 않는 enum도 추가하지 않는다. 조건 확정 전 이를 구현 완료로 보고하지 않는다.
- 목록·중복 확인은 본인 담당이면서 같은 기관인 사례자만 조회한다. 중복 확인은 이름·생년월일의 일치만 확인하고 excludeCaseId를 제외한다. 중복은 경고이며 등록을 금지하지 않는다. 다른 직원 전용·다른 기관 사례자의 이름·번호는 반환하지 않는다.
- 목록은 지역·연령대·성별·등록일·최근 기록일·이름/번호 부분 검색을 제공한다. `%`, `_`, 역슬래시는 POSITION으로 문자 그대로 검색한다. 정렬 키 6종과 방향은 허용 목록만 SQL에 사용한다. 동률은 case_id DESC다. 최근 기록일 null은 양방향 마지막이고 날짜 필터에서 제외된다.
- 결과가 없으면 totalCount=0·totalPages=0·page=1·items=[]이며, 페이지 초과는 마지막 페이지로 보정한다. 기본 page=1·size=10, size 최대 100이다. FE가 관할 시군구를 초기 선택하며 지역 query가 생략되면 본인 담당 전체를 조회한다.
- 이름·상담 목적·내용·기타는 trim 후 검증하고 길이는 Unicode 코드 포인트 기준이다. 이름 100·목적 200·내용 20000·기타 20자다. 생년월일·등록일·상담일은 한국 날짜 기준 미래를 거절한다. 지역·ID 형식과 담당자 최소 1명을 검증하고 담당자 중복을 제거한다. 등록자는 서버에서 자동 추가한다.
- 최초 등록일 수정 시 managementNo는 고정한다. 수정 시 본인을 담당자에서 제외하면 204로 저장되고 이후 상세는 403이다. CaseDetail.managers의 title:null과 lastRecordedAt:null을 유지한다.
- 상담은 일자 DESC·ID DESC로 정렬하고, 경로 caseId와 consultationId가 함께 일치해야 한다. 공동 담당자는 수정·삭제할 수 있고 최초 recorder_member_id는 유지한다. 최초 기록자가 탈퇴해도 FK·이름 조회를 유지한다. 기타 이외 분류의 categoryEtc는 null로 정규화한다.
- 사례자·상담은 물리 삭제한다. 사례자 삭제 시 case_manager·consultation은 기존 FK CASCADE로 정리된다. 최근 기록일은 기존 뷰의 MAX(consulted_at)로 계산한다.
- 성공·오류 공통 envelope·X-Request-Id·no-store를 사용하고, 변경 성공 204에는 본문이 없다. 요청 DTO의 toString은 값을 가린다. 업무 코드에 이름·상담 내용·연락처 원문을 기록하는 로그를 추가하지 않았다. 연락처 등 계약에 없는 입력 항목도 추가하지 않았다.

## 3. 권한·트랜잭션·잠금·관리번호

세션 인증·CSRF·임시 비밀번호 제한은 기존 공통 계층을 사용한다. 서비스에서도 최신 AuthService.currentUser를 확인하므로 기존 정상 세션의 회원이 DB에서 제한 상태로 바뀌면 403, 탈퇴·임시 암호 만료면 401이다.

상세·수정·삭제·상담은 없는 사례자와 다른 기관 사례자를 NOT_FOUND 404로 처리한다. 같은 기관이지만 현재 담당자가 아니면 FORBIDDEN 403이다. 다른 사례자의 상담 ID를 경로에 넣으면 404다. 클라이언트 orgId·recorderMemberId·managementNo는 받지 않는다.

단순 조회는 읽기 전용 트랜잭션이다. 쓰기는 **기관 FOR UPDATE → 회원 ID 오름차순 FOR UPDATE → 사례자 FOR UPDATE → 상담 UPDATE/DELETE** 순서다. 회원·사례자 잠금 쿼리는 모두 로그인 회원의 org_id 조건을 적용하므로 다른 기관 행은 잠그지 않는다. 기관 잠금으로 같은 기관의 담당자 변경·등록·삭제를 직렬화하고, 잠금 후 최신 회원·담당 권한을 재검사한다. 수정은 잠금 전 접근 확인도 수행한다.

관리번호 C3의 같은 트랜잭션 순서:

1. 로그인 회원의 기관 행을 FOR UPDATE로 잠근다.
2. 등록자와 지정 담당자 행을 ID 순서로 잠그고 같은 기관·미탈퇴를 확인한다.
3. 최초 등록일 연도의 기존 management_no에서 최대 4자리 순번을 조회한다.
4. 최대 9999이면 MANAGEMENT_NUMBER_EXHAUSTED 409로 종료하고 함수를 호출하지 않는다. 기존 함수의 10000 → 4자리 lpad 문제를 서비스에서 차단한다.
5. public.next_management_no(orgId, firstRegisteredAt)를 호출하고 사례자 INSERT·담당자 INSERT를 수행한다.
6. 모두 성공하면 커밋한다. 담당자 저장 등 후속 실패 시 사례자 INSERT도 롤백한다.

함수·서비스가 유지하는 기관 잠금은 커밋까지 풀리지 않는다. 발급은 기관·연도별이며 가장 큰 번호의 사례자가 삭제되면 그 번호가 재사용될 수 있다. 이 동작은 현재 계약 그대로다. IDENTITY 값 소모와 관리번호를 혼동하지 않으며 시퀀스를 초기화하지 않는다.

## 4. 실행한 검사와 결과

JDK 21.0.11·Gradle 9.8.2, 사용자가 띄운 공용 PostgreSQL·Mailpit. backend 폴더에서 실행:

```powershell
.\gradlew.bat integrationTest --tests '*CaseIntegrationTests' --console=plain
.\gradlew.bat test integrationTest bootJar --console=plain
```

| 구분 | 결과 |
|---|---|
| 신규 단위: CaseValidationTests | 5개 통과 |
| 신규 실제 DB·A1 인증·HTTP: CaseIntegrationTests | 29개 통과 |
| 전체 단위·MVC·설정·로컬 HTTP stub | 107개, 실패·오류·생략 0 |
| 전체 실제 DB·HTTP·Mailpit 통합 | 105개, 실패·오류·생략 0 |
| bootJar | 통과 |
| 별도 8080 실제 jar HTTP | API-19~29 전 경로 정상 흐름 통과 |

단위 5개는 Bean Validation의 코드 포인트 길이·담당자 ID 범위·한국 날짜 경계(고정 Clock)·DTO의 값 가림을 확인한다. fixture 값과 실제 회원 정보는 구분한다.

신규 통합은 실제 A1 로그인·PBKDF2·JDBC 세션·PostgreSQL·HTTP를 사용한다. CaseRepository는 Spy로 감싸되 일반 검사는 실제 메서드를 실행하며, **29개 중 등록 롤백 1개만 replaceManagers에 합성 실패를 주입**한다. 이 검사는 실제 DB INSERT가 롤백되는지 확인한다. 인증 대체 코드나 사례자 DB 대체는 없다.

정상 CRUD·공동 담당·본인 제외 후 접근 상실·기관별 격리·중복 확인 범위·목록 필터/정렬/페이지·literal 검색·상담 정렬/기록자 보존/최근 기록일·경로 ID 불일치·CASCADE·부적합 담당자·9999 차단·최고 번호 삭제 후 재사용·기관/연도별 발급·동일 기관 4건 동시 발급·등록 롤백·401/403/400·CSRF·공통 헤더를 확인했다.

타 기관 잠금 회귀 검사는 독립 DB 연결에서 테스트가 만든 다른 기관 사례자 행의 FOR UPDATE 잠금을 유지한다. 이 상태에서 사례자 DELETE와 상담 POST·PUT·DELETE가 5초 내 모두 404로 끝나는지 확인한다. 수정 전 `7d7f224`의 구현으로는 TimeoutException이 발생했고, access 쿼리에 기관 조건을 추가한 뒤 통과했다. 실패 시에도 finally에서 잠금을 롤백하여 요청과 자체 데이터를 정리한다. 최신 전체 검사 결과는 단위 107·통합 105이며, Claude Code가 재실행했던 단위 107·통합 104는 후속 수정 전 `7d7f224`의 결과다.

검사는 별도 합성 기관 두 개와 회원·사례자·상담을 생성하고 해당 기관의 데이터·자체 세션만 정리한다. 공용 지역 데이터·다른 회원 데이터·시퀀스를 초기화하지 않는다. IDENTITY 값 소모는 되돌리지 않는다.

8080의 기존 프로세스가 이 작업 폴더의 백엔드인지 확인해 종료한 뒤 bootJar를 빌드하고 새 jar를 시작했다. 실행 중인 jar를 덮어쓰지 않았다. 테스트 컨텍스트·Spy가 없는 실제 jar에서 합성 회원으로 로그인 → 중복 확인 → 등록 → 목록·상세 → 수정 → 상담 등록·목록·상세·수정·삭제 → 사례자 삭제 → 로그아웃을 확인했다. 11/4 계약 점검을 반영한 재검사에서 API-23의 부적합 담당자가 409 대신 400 VALIDATION_ERROR이고 정상 수정은 204임도 확인했다. 응답 본문에 개인정보 원문을 출력하지 않고 상태 코드와 검증 결과만 기록했다. 자체 fixture는 정리했다.

DB 읽기 전용 점검: eumi_app, TimeZone=Asia/Seoul, 관리번호 함수·사례자/상담 DML 권한 정상, dim_region 47행. 실제 검사 뒤 사례자·상담은 각각 0행으로 확인했다.

브라우저·FE 화면·운영 HTTPS·Nginx·운영 SMTP·운영 DB·FastAPI는 이번에 검사하지 않았다. 경계값 전수와 장시간 부하는 수행하지 않았다.

## 5. 남은 것·리뷰·FE 인계

**C3 필수 리뷰는 `7d7f224`에 대해 Claude Code가 완료했고 아래 항목 모두 적합 판정을 받았다.** 이번 후속 변경은 관리번호 발급 순서를 바꾸지 않고, 사례자 access 쿼리의 기관 조건·타 기관 행 잠금 회귀 검사·인계 문서만 보완한다. 후속 재점검에서는 해당 쿼리와 회귀 검사, 정상 권한 동작을 우선 확인한다. C3 리뷰 기준은 다음과 같다.

- create의 Spring 트랜잭션이 기관 잠금·한도 조회·함수·사례자/담당자 INSERT 전체를 포함하는지.
- 9999에서 함수 호출 전에 차단하고, 동시 등록에서 커밋까지 같은 기관을 직렬화하는지.
- 회원 ID 순서·다른 기관 행 미잠금·사례자 잠금 후 재검사가 담당자 변경·향후 탈퇴와 맞는지.
- 후속 실패 시 등록 전체가 롤백되고, API별 오류 코드가 x-error-codes 범위 안인지.
- API-23의 409는 ‘조건 미정, 11/4 결정’으로 보류되었으며 부적합 담당자는 400인지. 409 조건은 11/9 동시성 작업에서 확정한다.
- 다른 기관 404·같은 기관 미담당 403과 중복 확인 범위, 상담 recorder 보존, SQL/로그의 개인정보 취급.

FE는 5173의 프록시를 현재 실행 중인 8080으로 두고 실제 로그인 후 목록 빈 상태 → 등록 → 중복 경고 → 상세·수정 → 공동 담당·본인 제외 → 상담 CRUD·최근 기록일 → 삭제를 확인한다. 현재 시연 데이터는 0건이므로 합성 값으로 등록부터 진행한다. 실제 개인정보를 테스트 데이터로 넣지 않는다.

Reviewers는 CONTRIBUTING 3.3 기준 김민준(PM)이며 API 소비자인 FE 확인도 필요하다. Claude Code 기술 리뷰와 사람의 MR 승인을 구분한다. 사용자가 commit·push·develop 대상 MR·병합을 진행한다. 사례자 MR과 복지자원 W1~W3는 분리하며, 복지자원은 사용자가 별도 feat/be-resources를 준비한 뒤 진행한다.

커밋·MR 제목 제안: `feat: [BE] 사례자 및 상담 CRUD 구현`

리뷰 후속 커밋 제목 제안: `fix: [BE] 타 기관 사례자 잠금 범위 제한` (Jira: S15P31B201-194).

커밋 본문 마지막 줄:

```text
Jira: S15P31B201-192, S15P31B201-193, S15P31B201-194
```
