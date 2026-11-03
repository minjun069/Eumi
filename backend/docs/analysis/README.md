# 대시보드 분석 API 구현·검증·인계

2026-11-03. 브랜치 `feat/be-analysis`, 시작 커밋 `6dc13fb`(지역 API develop 병합). Jira: S15P31B201-160.

## 1. 작업 ID·API ID

D1·D2, 고립 위험 탐색(`/risk`)의 분석 결과 조회. 현재 저장소의 OpenAPI 2.3.0과 대시보드 구현 확정안, 공통 응답·세션 규칙을 기준으로 구현했다. 오래된 G1 문서는 과거 구현 기록으로만 참고했다.

| API | 경로 | 응답 data | 조회 원천 |
|---|---|---|---|
| API-10 | GET /api/analysis/sigungus/{sigunguCode}/months | `{months:["YYYY-MM",...]}` | public.region_result |
| API-11 | GET /api/analysis/dongs/{dongCode}/insight?month=YYYY-MM | DongInsightData | public.v_region_insight |
| API-12 | GET /api/analysis/dongs/{dongCode}/report?month=YYYY-MM | `{report:object 또는 null}` | public.region_result, public.region_insight_report |

`analysis` 패키지에 Controller·DTO·Service·JDBC Repository·SavedReportReader를 추가했다. 의존성·SecurityConfig·ErrorCode·마이그레이션·seed·infra·FE·docs/api는 바꾸지 않았다. Git 쓰기 명령과 Docker Compose·Flyway는 실행하지 않았다. 지역·기관 API-39~42는 선행 작업이며 이번 분석 API와 구분한다.

## 2. 계약과 달라진 점·404 기준·DTO

계약과 달라진 점: 없음. 새 오류 코드는 없다.

- API-10의 문서에 구체적인 404 조건이 없어, public.dim_region에 해당 시군구 접두어가 없으면 NOT_FOUND 404로 정했다. 지역 마스터에는 있지만 결과가 없으면 200과 `months:[]`다. 적재 월은 중복 없이 오름차순으로 반환한다.
- API-11·12는 동·월의 region_result 행이 없으면 404다. API-11의 뷰는 결과 행과 dim_region을 조인하므로 이 기준과 일치한다.
- 동 코드는 adm_cd10(10자리), 시군구 코드는 5자리 문자열이다. month는 `YYYY-MM`을 그 달 1일 DATE로 바꾼다. 잘못된 코드·월 형식 또는 필수 month 누락은 VALIDATION_ERROR 400이다.
- API-11은 bg_score/bg_grade를 background.score/stage, bh_score/bh_grade를 behavior.score/stage, risk_grade를 riskGrade로 반환한다. 생성 전에는 필수 필드 `insight:null`을 유지한다. 생성 후에는 summary_lines와 insight_generated_at을 summary·generatedAt으로 매핑한다.
- 점수·등급 필수 값이 빠지거나 등급 범위·저장 요약이 계약과 다르면 INTERNAL_SERVER_ERROR 500으로 처리하고, 정적인 진단과 동 코드·월만 WARN에 남긴다. 기본 점수나 단계를 만들어 넣지 않는다.
- API-12는 결과 행에서 보고서를 LEFT JOIN하여 결과 없음과 보고서 미생성을 구분한다. 미생성 응답에도 `report:null` 필드를 유지한다. generated_at이 report.generatedAt의 기준이며 JSON에 같은 이름이 있어도 DB 시각을 사용한다.
- 저장 보고서는 headline·sections와 paragraph/bullets/chart, trend/factors/weekday/compare/ratio의 계약 필드를 확인한 뒤 반환한다. question:null, 음수 요인 기여도, 문장·강조 표시를 보존한다. trend 월 순서·순위·사분위수, weekday 배열 길이, ratio count≤total 등 명시된 관계도 확인한다. 손상된 JSON·필드·차트는 500이며 report:null로 숨기지 않는다. 보고서 원문·SQL·예외 원문을 진단 로그에 넣지 않는다.
- 세 API 모두 공통 성공·오류 envelope, X-Request-Id와 meta.requestId 일치, Cache-Control:no-store를 사용한다. 조회 요청은 AI 클라이언트·생성 API를 호출하지 않는다.

## 3. 권한·잠금

세션 인증이 필요하고 임시 비밀번호 제한 세션은 PASSWORD_CHANGE_REQUIRED 403이다. 서비스에서도 AuthService.currentUser로 최신 DB 회원 상태를 확인한다. 로그인 후 DB에서 제한 상태로 바뀐 기존 세션도 403, 탈퇴·임시 비밀번호 만료 회원은 401이다.

확인한 계약·권한 문서에는 분석을 기관 관할로 제한하는 규칙이 없다. 로그인 회원은 전체 지역을 조회할 수 있고, 관할 시군구는 첫 화면의 기본 선택값으로만 사용한다. 통합 검사에서 강남구 관할 회원의 춘천시 월·인사이트·보고서 조회를 확인했다. 별도의 FORBIDDEN 지역 제한을 추가하지 않았다.

서비스는 읽기 전용 트랜잭션과 public 스키마 SELECT만 사용한다. 행 잠금·분석 데이터 변경·analysis 스키마 직접 접근·AI 생성은 없다. DB 점검에서도 eumi_app의 analysis USAGE 권한이 false임을 확인했다.

## 4. 실행한 검사와 결과

JDK 21.0.11·Gradle 9.8.2, 공용 로컬 PostgreSQL·Mailpit. backend 폴더에서 실행했다.

```powershell
.\gradlew.bat test integrationTest bootJar --console=plain
```

| 구분 | 결과 |
|---|---|
| 신규 단위·mock | AnalysisServiceTests 12개, SavedReportReaderTests 10개 통과 |
| 신규 실제 DB·A1 인증·HTTP | AnalysisIntegrationTests 18개 통과 |
| 전체 단위·MVC·설정·로컬 HTTP stub | 102개 통과, 실패·오류·생략 0 |
| 전체 실제 DB·HTTP·Mailpit 통합 | 76개 통과, 실패·오류·생략 0 |
| bootJar | 통과 |
| 별도 실제 8080 확인 | 아래 로그인·GET·로그아웃 흐름 통과 |

단위·mock은 유효한 지역의 months 빈 배열, 조회 대상 부재, 최신 제한 회원 거절, 점수·등급 매핑, 생성된 요약·보고서, 필수 값 누락·손상 데이터 처리를 확인한다. `src/test/resources/analysis/report.json`은 합성 fixture이며 모든 블록과 차트 종류를 포함한다. 생성된 보고서·차트 검사는 실제 AI 생성 결과나 실제 DB의 보고서 검사가 아니다.

실제 통합은 인증 대체 코드 없이 A1 로그인·PBKDF2·JDBC 세션·PostgreSQL·HTTP를 사용한다. 기존 지역·분석 결과는 읽기만 하고, 검사별 합성 기관·회원과 해당 세션만 생성·정리한다. months 중복 제거·정렬·실제 데이터 일치, 관할 밖 조회, 점수·등급·지역명 매핑, insight/report의 null 필드, 결과 없음 404, 입력 오류 400, 세 경로의 401·제한 세션 403·기존 정상 세션에 대한 최신 제한·탈퇴 401·공통 헤더를 확인한다. 공용 분석 데이터나 시퀀스를 초기화하지 않는다. 합성 회원 생성에 따른 IDENTITY 값 소모는 되돌리지 않는다.

기존 8080 프로세스가 이 작업 폴더의 BackendApplication임을 확인한 뒤 새 bootJar로 교체했다. 합성 회원으로 실제 로그인하고 아래 요청을 확인한 후 로그아웃·자체 fixture 정리를 수행했다.

- API-10: 11680·51110 모두 200, 2025-08~12 다섯 달.
- API-11: 1168066000·2025-12, 200. background 24.5/2, behavior 55.13/2, riskGrade 3, insight:null.
- API-12: 같은 동·월에서 200과 report:null.
- no-store·requestId 일치, 잘못된 시군구 코드 400·없는 시군구 404, 로그아웃 204.

브라우저·Tableau·Nginx·운영 HTTPS·운영 SMTP·부하·실제 FastAPI는 이번에 검사하지 않았다.

## 5. 로컬 DB 상태·남은 것·FE 인계

읽기 전용 확인 결과(2026-11-03):

- public.region_result: **235행**. 2025-08~12 각 월에 강남구 22동·춘천시 25동. seed의 행 수·기간과 일치한다. bg_score/bg_grade/bh_score/bh_grade/risk_grade는 실제 스키마에서 모두 NOT NULL이고 값 누락도 0건이다.
- public.v_region_insight: 235행, summary_lines가 있는 생성 완료 인사이트는 0행.
- public.region_insight_report: 0행. 따라서 현재 정상 데이터로는 insight:null·report:null이 기대 응답이다. 원본 데이터를 넣거나 변경하지 않았다.
- 실제 생성된 요약·보고서가 들어온 뒤 해당 데이터의 API 응답과 FE 그래프 표시를 추가 확인해야 한다. 조회 요청으로 생성을 시도하지 않는다.

8080에는 이번 bootJar를 AI Fake 모드로 실행해 두었다. FE 담당자는 5173 프록시를 8080으로 두고 시연 계정으로 로그인하여 다음을 확인한다.

1. `/risk`의 API-10이 200이고 월 목록이 2025-08~12인지 확인한다. 이 범위는 Tableau 게시본의 2025-07~12 안에 있으므로 게시된 ①·②·③·⑤를 띄울 수 있다. Tableau 표시 자체는 FE 브라우저 확인 대상이다.
2. 서울↔강원을 바꿔 API-10과 Tableau 지역·기간이 함께 갱신되는지 확인한다.
3. 유효한 행정동 선택 후 API-11의 지역명·점수·단계와 ‘인사이트 준비 중’ 안내를 확인한다.
4. API-12의 report:null에 대해 보고서 패널의 ‘준비 중’ 안내가 나오고 나머지 화면이 유지되는지 확인한다.

docs/api의 x-implementation-status 등 구현 상태 메타데이터를 갱신하려면 계약 담당자가 반영한다. 이번 작업에서 계약 파일은 수정하지 않았다. 사용자가 add·commit·push·develop 대상 MR·리뷰·병합을 진행한다.

커밋·MR 제목 제안: `feat: [BE] 대시보드 분석 조회 API 구현`

커밋 본문 마지막 줄:

```text
Jira: S15P31B201-160
```
