# 마이페이지 내 정보·담당 자원 구현·검증·MR 인계

2026-11-04. 사용자 계획의 [1](11/5 예정)을 `feat/be-my`에서 선행 구현했다. 시작 커밋은 `caea75e`(복지자원 develop 병합)이며 브랜치는 사용자가 생성·이동했다. 구현·검사를 완료했고 commit·push·MR·병합은 사용자가 진행한다. 아래 결과는 이 작업 폴더의 코드 기준 실행 기록이다.

## 1. 작업 ID·API ID

- 마이페이지 M1·M2: API-30 `GET /api/members/me`, API-31 `PATCH /api/members/me`, API-35 `GET /api/members/me/resources`.
- 관련 Jira: S15P31B201-177 `[BE] 내 정보 조회·수정 구현`. API-35 전용 Jira 키는 별도로 지정받지 않았다. Jira 제목·상태를 읽기만 했으며 변경하지 않았다.
- 기준 계약: 이 폴더의 `docs/api/openapi.json` 2.3.0, 공통 응답·세션 규칙, 트랜잭션 가이드, V1 회원·기관과 V2 지역 뷰, V3 복지자원 뷰.
- 새 코드: `mypage/MyController`, `MyService`, `MyRepository`, `MyDtos`. 기존 `ResourceRepository`에는 본인 담당 자원 조회 메서드만 추가했다.

## 2. 계약과 달라진 점·DTO·오류

계약과 달라진 점: 없음. ErrorCode·SecurityConfig·의존성·DB 마이그레이션·seed·frontend·infra·docs/api는 변경하지 않았다.

| API | 응답과 동작 |
|---|---|
| API-30 | 200 `data={name,email,orgName,jurisdictionName,title,phone}`. title·phone은 null이어도 필드를 유지 |
| API-31 | 200, 갱신된 MyInfo 6개 필드 전체. title·phone만 변경, updated_at 갱신 |
| API-35 | 200 `data={totalCount,items}`. 페이지 없이 본인 담당 미삭제 자원 전체, 항목은 기존 ResourceListItem 11개 필드 |

- jurisdictionName은 기관의 jurisdiction_sigungu_code를 기준으로 `v_sido.sido_name + " " + v_sigungu.sigungu_name`을 만든다. 서울특별시 강남구·강원특별자치도 춘천시의 전체 이름을 실제 DB로 확인했다. 누락·중복 매핑은 임의 이름으로 채우지 않고 회원 ID·지역 코드 수준의 진단 로그와 500으로 처리한다.
- PATCH는 JsonNode에서 필드 존재 여부와 nullable 값을 각각 보관한다. `{"title":"새 직함"}`은 phone 유지, `{"phone":null}`은 phone 비움, title의 빈 문자열·공백은 null로 정규화한다. 명시적 null과 생략이 SQL CASE에서도 구분된다.
- title은 trim 후 Unicode 코드 포인트 최대 100자, phone은 trim 후 `^01[016789]-[0-9]{3,4}-[0-9]{4}$`다. 빈 phone은 null로 바꾸지 않고 400 VALIDATION_ERROR와 phone 필드 오류로 거절한다. title 길이 오류도 title 필드 오류를 준다.
- 빈 객체 `{}`는 minProperties=1에 따라 400 VALIDATION_ERROR다. 허용되지 않은 필드, 문자열/null이 아닌 값, 객체가 아닌 JSON은 400 INVALID_JSON이다. 요청에서 회원 ID·이름·이메일·기관·관할을 바꿀 수 없다.
- API-35는 `v_resource_summary WHERE manager_member_id=본인`을 조회하며 `status_order asc, period_end asc, resource_id asc` 순서다. ResourceRepository의 기존 listItem 매핑을 그대로 재사용한다. 기존 API-13~17의 쿼리·매핑·동작은 변경하지 않았다.
- 새 업무 오류 코드는 없다. 일반 성공·실패 응답의 requestId와 Cache-Control: no-store를 유지한다.

## 3. 권한·잠금·세션

- 회원 ID는 인증된 SessionPrincipal에서만 얻는다. 최신 회원을 DB에서 다시 읽으며 비인증·탈퇴·만료 임시 비밀번호는 401, 유효 임시 비밀번호 제한 상태는 403 PASSWORD_CHANGE_REQUIRED다.
- API-30·35는 본인의 정보만 반환한다. 같은 기관 동료·다른 기관 회원의 자원도 본인 담당이 아니면 제외한다. 삭제 자원은 뷰에서 제외된다.
- API-31은 CSRF 검사 후 한 트랜잭션에서 기관 FOR UPDATE → 본인 회원 FOR UPDATE 순서로 잠그고 최신 활성 상태·기관을 다시 확인한다. title·phone·updated_at 갱신과 응답 정보 재조회가 같은 트랜잭션이다. 단순 GET에는 쓰기 잠금을 사용하지 않는다.
- 프로필 수정은 세션 ID·principal을 교체하거나 다른 세션을 폐기하지 않는다. `/auth/me`가 DB의 최신 title을 읽는 것을 확인했다. FE는 PATCH 결과로 내 정보 캐시를 갱신하고 메뉴 프로필을 다시 조회하면 된다.
- 비밀번호 변경의 다른 세션 폐기·현재 세션 ID 교체는 [3] feat/be-password의 별도 범위다.

## 4. 실행한 검사와 결과

JDK 21.0.11, Git Bash, 실제 공용 PostgreSQL localhost:5432(eumi_app, Asia/Seoul)과 기존 Mailpit을 사용했다. Docker Compose·Flyway·Git 쓰기 명령은 실행하지 않았다.

```bash
cd /c/Users/SSAFY/Desktop/PJT3/S15P31B201/backend
export JAVA_HOME='C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot'
./gradlew.bat test integrationTest bootJar --console=plain
```

2026-11-04 15:17~15:18 KST 실행, BUILD SUCCESSFUL이다.

| 구분 | 결과 | 범위 |
|---|---|---|
| DB 없는 단위/fixture 전체 | 124개 통과 | 기존 110 + MyPatchTests 14. 실패·오류·생략 0 |
| 실제 DB·HTTP 통합 전체 | 163개 통과 | 기존 151 + MyIntegrationTests 12. 실패·오류·생략 0 |
| bootJar | 통과 | 이번 main 코드가 포함된 실행 jar |
| 실제 8080 jar HTTP | 통과 | 실제 A1 로그인, API-30 200·6개 필드·관할 전체 이름, API-31 200·생략 유지·null 비움·빈 phone 400, 최신 /auth/me·SESSION 유지, API-35 200·본인 미삭제 자원만 반환 |
| git diff --check | 통과 | 문서 포함 변경 공백 검사 |
| FE 브라우저·운영 배포·Nginx·HTTPS | 미실행 | 후속 연동에서 확인 |

단위 14개는 PATCH 생략/null/공백, 100·101 코드 포인트 경계, 잘못된 phone·빈 객체, 잘못된 JSON 형태·허용하지 않은 필드를 검사한다.

실제 통합 12개는 MyInfo 필드와 양쪽 관할 이름, PATCH 생략·null·빈 title·updated_at, 다른 회원 정보 보존, 기존 두 세션의 ID·세션 집합 유지, 최신 메뉴 프로필, 잘못된 phone 6가지와 부분 저장 방지, title Unicode 경계·추가 필드 거절, 본인 자원 15건 전체·정렬·동 null 필드 유지·타인/삭제 자원 제외, 비인증·제한/탈퇴 거절·CSRF를 검사한다. 인증 대체 컨트롤러 없이 실제 PBKDF2와 A1 로그인을 사용한다.

모든 데이터는 테스트에서 생성한 합성 기관·회원·자원이다. 세션은 해당 회원 principal로만 찾아 지우며 자원·회원·기관도 자체 소유 ID·marker로 정리한다. 공용 데이터·시퀀스 초기화나 되돌림은 없다. 실제 8080 검증 역시 메모리에서 합성 암호를 생성하고 자체 데이터·세션만 정리했다. 비밀번호·쿠키·세션 값·실제 개인정보를 파일·로그·보고에 남기지 않았다.

검사 XML: `build/test-results/test/`, `build/test-results/integrationTest/`. HTML: `build/reports/tests/`. 실제 HTTP 보조 도구와 런타임 로그는 무시되는 build 아래에만 있다.

## 5. 남은 것·FE 인계

- 새 jar를 local/Fake 모드로 8080에 실행해 두었다. 문서 작성 당시 PID 13768이며 이후 사용 시 포트·프로세스를 다시 확인한다.
- FE 확인: 로그인 → 내 정보 조회 → title만 수정하고 phone 유지 확인 → phone을 null로 비움 → 메뉴 프로필 재조회 → 담당 자원 탭에서 본인 담당만 표시되는지 확인. 빈 전화 입력은 FE가 null로 보내고 변경하지 않은 필드는 생략한다.
- 담당 자원 응답은 페이지 객체가 아닌 totalCount·items다. 진행 중 우선이며 전체 목록을 반환한다. 공통 자원 목록의 ResourceListItem 타입을 그대로 사용한다.
- FE 브라우저 연동과 운영 배포는 아직 확인하지 않았다. Jira 완료·MR 생성·병합은 사용자가 진행한다.
- [2] API-36~38은 feat/be-conversations, [3] API-32는 feat/be-password에서 각각 별도 MR로 진행한다. 현재 브랜치에서 다음 단계 구현을 섞지 않는다. [3]은 Claude Code 리뷰 후 병합한다.

제안 커밋 제목: `feat: [BE] 내 정보 조회·수정과 담당 자원 조회 구현`

커밋 본문 마지막 줄: `Jira: S15P31B201-177`

MR 대상: develop. 위 1~5절을 인계와 MR 설명으로 사용한다.
