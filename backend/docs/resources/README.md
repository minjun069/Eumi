# W1~W3 복지자원 API 구현·검증·MR 인계

2026-11-04. 작업 브랜치 `feat/be-resources`, 시작 커밋 `b22abbb`(최신 develop에서 사용자 생성). 이 기록은 미커밋 구현의 검사 결과이며 commit·push·MR·병합은 사용자가 진행한다.

## 1. 작업 ID·API ID

- W1~W3, API-13 목록, API-14 상세, API-15 수정, API-16 삭제, API-17 등록.
- Jira: S15P31B201-184(조회), S15P31B201-185(CRUD), S15P31B201-186(권한·상태). Jira에서 제목과 현재 ‘진행 중’ 상태를 읽기만 했으며 상태를 변경하지 않았다.
- 기준: 이 폴더의 OpenAPI 2.3.0, `V3__resources.sql`, 공통 응답·세션 규칙과 트랜잭션 가이드. API-35 내 담당 자원은 이번 범위에 포함하지 않는다.
- 구현: `resources/ResourceController`, `ResourceService`, `ResourceRepository`, `ResourceDtos`. JDBC로 기존 테이블과 TEXT[]를 사용한다. 의존성·마이그레이션 변경 없음.

## 2. 계약과 달라진 점·DTO·오류

계약과 달라진 점: 없음. ErrorCode·SecurityConfig·docs/api·frontend·infra·seed를 변경하지 않았다.

| API | 정상 응답 | 주요 결과 |
|---|---|---|
| API-13 `GET /api/resources` | 200, `data={totalCount,page,size,totalPages,items}` | 항목당 11개 필드, 빈 결과는 totalPages=0·page=1·items=[] |
| API-14 `GET /api/resources/{resourceId}` | 200, ResourceDetail 24개 필드 | manager 5개 필드와 nullable 필드를 항상 유지 |
| API-15 `PUT /api/resources/{resourceId}` | 204, 본문 없음 | 전체 수정, 생략한 선택 입력도 null로 덮어씀, updated_at 갱신 |
| API-16 `DELETE /api/resources/{resourceId}` | 204, 본문 없음 | deleted_at만 설정, 행과 updated_at 보존 |
| API-17 `POST /api/resources` | 201, `data={resourceId}` | 같은 기관 활성 담당자를 지정해 등록 |

- 새 오류 코드는 없다. 없거나 삭제된 자원은 404 NOT_FOUND, 담당자가 아닌 회원의 수정·삭제는 403 FORBIDDEN이다.
- 문자열 trim, 선택 글의 빈값 null, 연령 배열 중복 제거를 적용한다. 연령·성별·상태·정수 범위·기간·실제 지역 존재·시군구/동 일치·후임 활성 상태를 검사한다. 입력 오류는 400 VALIDATION_ERROR와 해당 fieldErrors 필드 이름으로 반환한다. 추가 JSON 속성은 INVALID_JSON이다.
- 목록의 잘못된 형식·정렬값·지역 코드 조합·정원 최소/최대 역전은 400이다. 정수는 DB INT 상한까지, ID·page는 계약의 안전 정수 상한까지 검사한다. 미래 운영 기간과 정원 초과 참여자 수는 허용한다.
- 조회는 전부 `public.v_resource_summary`를 사용한다. 시도·시군구·동, 연령·성별 무관 포함, 정원 범위, literal 부분 검색을 AND로 적용한다. 이름 검색의 `%`, `_`, 역슬래시를 문자 그대로 처리하며 `managerName`에는 `manager_withdrawn=false`를 함께 적용한다.
- 정렬은 status_order asc → 선택 sort/direction → period_end asc → resource_id asc. 기본 periodEnd asc이며 마지막 페이지 초과는 마지막 페이지로 보정한다.
- 표시 status·autoEnded는 DB current_date 기준 뷰 계산값이고 manualStatus는 저장값이다. 종료 자원의 탈퇴 담당자는 name=퇴사자·title=null, memberId·orgName 유지. 진행 중 자원에 탈퇴 담당자가 남으면 자원 ID만 포함한 정합성 오류 로그와 500을 반환한다. 입력·이름·연락처 원문은 로그에 넣지 않는다.

## 3. 권한·트랜잭션·잠금

- 로그인한 활성 회원은 기관·관할 제한 없이 모든 미삭제 자원을 조회한다. editable은 활성 담당자 본인만 true이다. 임시 비밀번호 제한 세션은 403 PASSWORD_CHANGE_REQUIRED이다. 세션에 남은 과거 상태만 믿지 않고 최신 회원을 재조회한다.
- 등록 때 작성자와 다른 같은 기관 활성 회원을 담당자로 지정할 수 있다. 작성자가 자동 담당자로 추가되지 않는다.
- 쓰기는 한 트랜잭션에서 기관 FOR UPDATE → 같은 기관 회원을 member_id 오름차순 FOR UPDATE → 자원 FOR UPDATE 순서다. 현재 회원·선택 담당자의 기관과 활성 상태를 잠금 후 다시 확인한다. 타 기관 담당자 후보의 회원 행은 잠그지 않는다.
- 수정·삭제는 뷰에서 존재와 담당자를 먼저 확인해 비담당자 요청을 거절한다. 승인 가능한 요청은 위 잠금을 얻은 뒤 자원 원본 행의 삭제 여부·담당자를 재확인하고 변경한다. 담당자 변경 직후 이전 담당자는 조회만 가능하다.
- 담당자 활성 상태와 교차하는 후속 탈퇴·인계 서비스도 같은 잠금 순서를 사용해야 한다. 단순 목록·상세에는 쓰기 잠금을 사용하지 않는다.

## 4. 실행한 검사와 결과

JDK 21.0.11, Git Bash에서 실행했다. 실제 PostgreSQL(공용 localhost:5432, eumi_app, Asia/Seoul)과 기존 Mailpit을 사용했다. Docker Compose·Flyway를 실행하지 않았다.

```bash
cd /c/Users/SSAFY/Desktop/PJT3/S15P31B201/backend
export JAVA_HOME='C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot'
./gradlew.bat test integrationTest bootJar --console=plain
```

| 구분 | 결과 | 근거·범위 |
|---|---|---|
| DB 없는 단위/fixture | 110개 통과 | 기존 107 + ResourceValidationTests 3. trim·중복 제거·선택 빈값·Unicode 코드 포인트 길이 |
| 실제 PostgreSQL·HTTP·PBKDF2 통합 | 151개 통과 | 기존 105 + ResourceIntegrationTests 46. 실패·오류·생략 0 |
| bootJar | 통과 | 최종 main 코드가 포함된 실행 jar |
| 실제 8080 jar HTTP | 통과 | 합성 계정 로그인, POST 201, 목록·상세 200, PUT 204, 비담당자 PUT 403, DELETE 204, 이후 상세 404·물리 행 유지 |
| git diff --check | 통과 | Git 쓰기 명령 미실행 |
| FE 브라우저·Nginx·운영 HTTPS·부하 | 미실행 | FE 연동 및 배포 단계에서 확인 |

46개 통합 검사는 CRUD, 타 기관 조회·비담당자 수정/삭제 403, 담당자 교체, 무효 담당자 400, 입력 22가지, 동·무관 포함 필터, `%`·`_`·역슬래시 검색, 퇴사 담당자 검색 제외, 네 정렬의 양방향, 마지막/빈 페이지, 자동/수동 종료와 퇴사 표시, 정합성 오류 500, 잘못된 검색 13가지, 인증·제한 세션·CSRF·잘못된 JSON을 검사한다. 성공·오류의 requestId/no-store, 204 빈 본문도 확인한다.

첫 실행은 151개 중 1개가 테스트 fixture의 존재하지 않는 must_change_password 컬럼 때문에 실패했다. 실제 스키마의 temp_password_expires_at으로 수정한 뒤 위 전체 명령을 다시 실행해 110/151 전부 통과했다. 운영 main 코드의 실패로 기록하지 않는다.

테스트는 자체 기관·회원·자원과 해당 principal의 세션만 정리한다. 실제 8080 검사도 독립 합성 계정·암호를 메모리에서 생성하고 자체 데이터만 정리했다. 공용 데이터·시퀀스 초기화 및 되돌림은 없다. 검사 전후 welfare_resource·v_resource_summary는 각각 0건이다.

검사 XML은 `build/test-results/test/`, `build/test-results/integrationTest/`, HTML은 `build/reports/tests/`에 있다. 실행 로그와 8080 수동 확인용 임시 도구는 무시되는 build 아래에만 있으며 커밋 대상이 아니다.

## 5. 남은 것·FE 인계

- 8080은 새 jar를 local/Fake 모드로 실행해 두었다. 2026-11-04 검사 종료 시 PID 23952, `/api/health` 200. 재개할 때 실제 포트·프로세스를 다시 확인한다.
- 자원 seed가 없고 공용 자원은 현재 0건이다. FE는 기존 시연 계정 로그인 → 빈 목록 → 합성 자원 등록 → 필터/상세/수정 → 같은 기관 다른 활성 담당자로 교체 → 기존 담당자 editable=false → 후임 계정 수정/삭제 순서로 확인한다. 담당자 후보는 API-42를 사용한다.
- 전체 기관 조회가 가능하므로 타 기관 계정에서도 등록된 자원을 볼 수 있다. 운영 종료일이 지나면 저장값을 바꾸지 않아도 표시 상태가 종료로 나온다.
- API-35 내 담당 자원, 탈퇴 시 인계, FE 브라우저 연동, 운영 배포는 이번 완료 범위와 구분한다. Jira 완료 처리는 사용자가 실제 연동을 확인한 뒤 진행한다.
- README의 운영 변수 안내는 이미 `서버 /srv/eumi/.env.config + 운영 Compose environment`와 일치한다. 추가 인프라 변경은 필요하지 않았다.

제안 커밋 제목: `feat: [BE] 복지자원 조회·등록·수정·삭제 구현`

커밋 본문 마지막 줄: `Jira: S15P31B201-184, S15P31B201-185, S15P31B201-186`

MR 대상: develop. 위 1~5절을 MR 설명으로 사용한다.
