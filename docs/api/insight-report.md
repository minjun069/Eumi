# 인사이트 보고서 내부 연동 계약 (A 방식, 2026-11-06 초안)

파이프라인이 월 분석을 끝내면 BE가 그 달 동 목록을 AI(FastAPI)에 넘기고, AI는 동마다 보고서를 만들어 BE API로 보낸다. BE가 검사한 뒤 `region_insight_report`에 저장하고, 화면은 API-11 · 12로 읽는다. 생성 상태(실행 기록)는 저장하지 않는다(A 방식).
API 형식은 `openapi.json` 2.3.1의 `x-internal-ai-api` INT-04~06, DB는 `db/migration/V20261106_01__insight_report_slots.sql`이 기준이다. AI 담당(김민준) 확인 전 초안이며, 재시도 횟수 · 간격은 제안값이다.

## 1. 구성 요소

| 구성 요소 | 하는 일 |
|---|---|
| 파이프라인 (Airflow) | 14단계(결과 검증)까지 성공하면 마지막 작업이 INT-04를 보낸다. 결과 행을 다시 쓸 때마다 `updated_at`을 바꾼다 |
| BE (Spring) | INT-04를 받아 그 달 결과 목록으로 INT-05를 보낸다. INT-06을 검사해 저장한다. 보고서를 DB에 쓰는 것은 BE(`eumi_app`)뿐이다 |
| AI (FastAPI) | INT-05를 접수하고 뒤에서 동마다 보고서를 만들어 INT-06으로 보낸다. DB는 읽기만 한다(`eumi_ai`) |
| DB | 동 · 월마다 보고서 한 행. 결과 행이 지워지면 보고서도 지워진다(FK CASCADE) |
| 화면 (FE) | API-11(퀵 인사이트) · API-12(보고서)로 저장된 보고서를 읽는다. 조회는 생성을 일으키지 않는다 |

- 대화 패널(INT-01~03)은 AI가 `ai_message`에 직접 쓰지만, 보고서는 AI가 BE로 보내고 BE만 저장한다. `eumi_ai`의 `region_insight_report` 쓰기 권한은 11/6에 거뒀다(`afterMigrate.sql`).
- 보고서는 동 · 월마다 한 행이고 다시 만들면 덮어쓴다. 시트 이름은 허용 목록(9절)과 맞아야 한다.

## 2. 흐름

1. 파이프라인이 14단계까지 성공하면 Airflow 마지막 작업이 INT-04를 보낸다. 여러 달을 처리했으면 달마다 한 번 보낸다.
2. BE는 그 달 `region_result`의 `adm_cd10`, `updated_at`을 모두 읽어 INT-05로 AI에 넘긴다.
3. AI는 202로 접수만 답하고, 뒤에서 동마다 분석 데이터를 읽어 보고서를 만든다.
4. AI는 동 하나를 끝낼 때마다 INT-06으로 보낸다. 동이 100개면 100번 보낸다.
5. BE는 토큰 · 본문을 검사하고, 결과 행의 `updated_at`이 꼬리표와 같을 때만 저장한다.

## 3. 꼬리표 `resultUpdatedAt`

- 그 동 결과 행의 `updated_at`, 즉 파이프라인이 그 결과를 마지막으로 쓴 시각이다. BE가 INT-05에 담아 보내고 AI는 INT-06에 그대로 돌려준다.
- 형식은 `YYYY-MM-DDTHH:mm:ss.SSSSSS`, 오프셋 없음, 소수 정확히 6자리다. BE는 `LocalDateTime`으로 읽어 값이 `.000000`이어도 6자리로 쓴다.
- AI는 받은 문자열을 복사해 돌려준다. 날짜로 바꾸거나 밀리초로 줄이거나 시간대를 붙이지 않는다.
- 같은지만 비교한다. 시각의 크고 작음(`generatedAt >= updated_at` 등)으로 옛 보고서를 판단하지 않는다.
- 데이터 분석 파트 약속: 결과 행을 다시 쓸 때마다 `updated_at`을 바꾼다.

## 4. API

### INT-04 월 분석 완료 알림 (파이프라인 → BE)

`POST /api/internal/analysis/pipeline-completions` · `Authorization: Bearer <파이프라인 토큰>`

```json
{ "month": "2025-12", "pipelineRunId": "scheduled__2026-11-01T01:00:00+00:00", "reason": "FULL" }
```

| 필드 | 규칙 |
|---|---|
| `month` (필수) | `YYYY-MM` |
| `pipelineRunId` | Airflow 실행 번호 등 1~200자. 로그용 |
| `reason` | `FULL` · `RESULT_RELOAD` · `ANALYSIS_RELOAD`, 없으면 `FULL`. 로그용이며 처리는 모두 같다 |

- 보내는 시점: 14단계 성공 뒤. 12 · 13단계만 다시 돌렸어도 보낸다. 실패한 실행과 `--dry-run`은 보내지 않는다.
- BE 처리: 토큰 · 본문 검사 → 그 달 결과가 없으면 404 → INT-05 호출(`eumi.ai.http-timeout`, 기본 3초) → AI가 202면 202 `{month, targetCount}`. AI가 응답하지 않거나 202가 아니면 503 `AI_UNAVAILABLE`.
- 같은 달을 다시 보내면 그 달 보고서를 다시 만든다. 동 · 월마다 한 행은 유지되지만 AI 문장과 고른 시트는 달라질 수 있다.
- `EUMI_AI_MODE=fake`에서는 INT-05를 보내지 않고 202만 돌려준다.
- 오류: 400 `VALIDATION_ERROR` · `INVALID_JSON`, 401 `UNAUTHENTICATED`, 403 `FORBIDDEN`(다른 호출자 토큰), 404 `NOT_FOUND`, 503 `AI_UNAVAILABLE`.

### INT-05 보고서 생성 요청 (BE → AI)

`POST /internal/insight-reports/runs` · 인증 없음(내부망)

```json
{
  "requestId": "0f5c2a3e-6b1d-4c8e-9a51-2d7e4f0b9c13",
  "month": "2025-12",
  "targets": [
    { "dongCode": "1168066000", "resultUpdatedAt": "2026-11-03T10:42:36.824797" },
    { "dongCode": "1168064000", "resultUpdatedAt": "2026-11-03T10:42:36.824797" }
  ]
}
```

| 필드 | 규칙 |
|---|---|
| `requestId` (필수) | INT-04를 처리하며 BE가 만든 UUID. INT-04 응답의 `X-Request-Id` · `meta.requestId`와 같다(호출자가 보낸 값은 쓰지 않음). 로그를 잇는 용도 |
| `month` (필수) | `YYYY-MM` |
| `targets` (필수) | 그 달 결과가 있는 모든 동. 동 코드는 중복 없음 |
| `targets[].resultUpdatedAt` (필수) | 그 동 결과 행의 `updated_at` (꼬리표) |

- AI 응답: 202 `{"accepted": 2}`(접수한 동 수, 아직 만들기 전). 본문이 잘못됐으면 400.
- AI는 `eumi_ai` 읽기 권한으로 분석 데이터를 읽고, 동마다 퀵 인사이트 1개와 허용 시트 8개 중 서로 다른 3개, 그래프별 설명을 만든다. `region_insight_report`에는 쓰지 않는다.
- 같은 달 요청이 진행 중에 또 오면 하던 작업을 멈추고 새 요청으로 다시 시작하는 것을 권장한다. BE가 옛 보고서를 거르는 것은 결과 시각이 바뀐 경우뿐이다. 12 · 13단계만 다시 돌려 시각이 같으면 늦은 응답이 새 보고서를 덮을 수 있다.

### INT-06 동별 보고서 저장 (AI → BE)

`PUT /api/internal/analysis/insight-reports/{month}/{dongCode}` · `Authorization: Bearer <AI 토큰>` · 같은 동 · 월에 다시 보내면 덮어쓴다.

```json
{
  "resultUpdatedAt": "2026-11-03T10:42:36.824797",
  "quickInsight": "야간 활동이 전월보다 크게 줄었습니다.\n1인 가구 비율이 높아 배경 취약성도 3단계입니다.",
  "graphs": [
    { "sheet": "EmbedDetailV01", "description": "행동 이상 점수가 3개월 연속 올랐습니다." },
    { "sheet": "EmbedDetailV03", "description": "저녁 시간대 활동이 특히 줄었습니다." },
    { "sheet": "EmbedDetailV06", "description": "1인 가구 비율이 가장 큰 요인입니다." }
  ],
  "generatedAt": "2026-11-10T17:10:00.123+09:00"
}
```

| 필드 | 규칙 | DB 칸 |
|---|---|---|
| 경로 `month` · `dongCode` | `YYYY-MM`(저장할 때 그 달 1일 DATE), 숫자 10자리. AI는 INT-05로 받은 동만 보낸다 | `period_start` · `adm_cd10` |
| `resultUpdatedAt` (필수) | INT-05에서 받은 문자열 그대로 | 비교 후 `result_updated_at` |
| `quickInsight` (필수) | 앞뒤 공백을 뺀 뒤 코드 포인트 1~500자, 줄바꿈 허용. 2~3줄은 작성 권고(검사하지 않음) | `quick_insight` |
| `graphs` (필수) | 정확히 3개. 배열 순서 = 화면 순서 | `graph_1~3` · `desc_1~3` |
| `graphs[].sheet` | `EmbedDetailV01`~`V08` 중 하나(9절), 세 개가 서로 다름 | `graph_n` |
| `graphs[].description` | 앞뒤 공백을 뺀 뒤 코드 포인트 1~1000자 | `desc_n` |
| `generatedAt` (필수) | AI가 만든 시각, 오프셋 포함 ISO 8601 | `generated_at` |

글자 수는 공통 규칙대로 앞뒤 공백을 뺀 뒤 Unicode 코드 포인트로 센다. BE는 대상 목록을 저장하지 않으므로 그 동을 INT-05로 보낸 적이 있는지는 검사하지 않는다. 지금 결과 행(404) · 꼬리표(409) · 본문 형식(400)을 검사하고 SQL 한 문장으로 저장한다(V20261106_01 머리 주석과 같음).

```sql
INSERT INTO region_insight_report
    (period_start, adm_cd10, quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3,
     result_updated_at, generated_at)
SELECT r.period_start, r.adm_cd10, :quick, :g1, :d1, :g2, :d2, :g3, :d3, r.updated_at, :generated_at
FROM region_result r
WHERE r.period_start = :month AND r.adm_cd10 = :dong AND r.updated_at = :result_updated_at
ON CONFLICT (period_start, adm_cd10) DO UPDATE
  SET quick_insight = EXCLUDED.quick_insight,
      graph_1 = EXCLUDED.graph_1, desc_1 = EXCLUDED.desc_1,
      graph_2 = EXCLUDED.graph_2, desc_2 = EXCLUDED.desc_2,
      graph_3 = EXCLUDED.graph_3, desc_3 = EXCLUDED.desc_3,
      result_updated_at = EXCLUDED.result_updated_at,
      generated_at = EXCLUDED.generated_at;
```

`:month`는 경로의 `YYYY-MM`을 그 달 1일 DATE로 바꾼 값, `:result_updated_at`은 꼬리표 문자열을 TIMESTAMP로 바꾼 값이다. 0행이면 결과 행이 없을 때 404, 있으면 409다.

| 응답 | 뜻 | AI가 할 일 |
|---|---|---|
| 200 `{month, dongCode, saved: true}` | 저장됨 | 끝 |
| 400 `VALIDATION_ERROR` · `INVALID_JSON` | 형식이 틀림 (`fieldErrors`에 필드 경로) | 고칠 수 있으면 고쳐서 다시, 아니면 버리고 로그 |
| 401 `UNAUTHENTICATED` · 403 `FORBIDDEN` | 토큰 문제 | 재시도하지 말고 설정 확인 |
| 404 `NOT_FOUND` | 그 동 · 월 결과 행이 없음 | 버림 |
| 409 `RESULT_VERSION_MISMATCH` (신규) | 그사이 결과가 다시 쓰임 (옛 결과로 만든 보고서) | 버림. 새 INT-05가 오면 그때 다시 만듦 |
| 500 · 연결 실패 | 서버 쪽 문제 | 같은 본문으로 재시도 |

- 같은 본문을 다시 보내도 200이다. 동마다 따로 저장하므로 한 동이 실패해도 다른 동은 영향이 없다.
- BE는 형식과 꼬리표만 검사한다. 설명이 그래프 수치와 맞는지는 AI 쪽 책임이다.
- 보고서를 못 만든 동은 BE에 알리지 않고 AI 로그에 남긴다.

## 5. 인증과 노출

| 호출 | 인증 | 노출 |
|---|---|---|
| BE → AI (INT-05) | 없음 | AI 서버는 Nginx에 경로가 없어 밖에서 부를 수 없다. 내부망 `http://ai:8000` (ai 서비스를 추가한 뒤) |
| 파이프라인 → BE (INT-04) | `Authorization: Bearer <파이프라인 토큰>` | 내부망 `http://backend:8080/api/internal/…`. Nginx는 `/api/internal/`을 404로 막는다 |
| AI → BE (INT-06) | `Authorization: Bearer <AI 토큰>` | 위와 같다 |

- `/api/internal/**`(서블릿 경로 `/internal/**`)는 브라우저 API와 분리한 별도 보안 체인에서 처리한다. 세션을 만들지 않고(stateless), CSRF 검사에서 제외하며, 서비스 토큰으로만 인증한다. 브라우저 API의 세션 · CSRF 보호는 그대로 둔다.
- 토큰이 없거나 틀리면 401 `UNAUTHENTICATED`, 다른 호출자 토큰(파이프라인 토큰으로 INT-06 등)이면 403 `FORBIDDEN`이다.
- 토큰 값은 서버 `/srv/eumi/.env.config`에만 두고 compose `environment`로 넘긴다. 로그 · 저장소 · 문서에 값을 남기지 않는다.
- 로그에는 `requestId`, 월, 동 코드, 상태 코드만 남긴다. 토큰 · SQL · 예외 원문 · 보고서 본문은 남기지 않는다.

## 6. 오류 · 재시도

연결 실패와 5xx만 같은 본문으로 다시 보내고, 4xx는 자동으로 다시 보내지 않는다. 횟수와 간격은 제안값이다.

| 호출 | 다시 보내는 경우 | 횟수 · 간격 (제안) | 다시 보내지 않는 경우 |
|---|---|---|---|
| INT-04 | 연결 실패, 5xx, 503 `AI_UNAVAILABLE` | Airflow 재시도 3회, 5분 간격 | 400 · 401 · 403 · 404 |
| INT-05 | 따로 다시 보내지 않는다. 실패하면 INT-04가 503으로 끝나고 파이프라인이 다시 보낸다 | — | — |
| INT-06 | 연결 실패, 5xx | 3회, 1초 · 5초 · 30초 | 400 · 401 · 403 · 404 · 409 |

## 7. 한계 (A 방식)

| 상황 | 동작 |
|---|---|
| 11단계(결과 적재)를 다시 돌림 | `updated_at`이 바뀌어 이전 보고서는 곧바로 숨겨지고, 이전 요청의 늦은 저장은 409 (아래 동시 진행은 예외) |
| 12 · 13단계만 다시 돌림 | `updated_at`이 그대로라 새 보고서가 저장될 때까지 이전 보고서가 보인다. 실행이 겹치면 늦게 끝난 쪽이 덮는다 |
| 결과 적재와 보고서 저장이 동시에 진행됨 | 저장 문장은 시작할 때 읽은 결과 시각으로 판단하므로, 409가 아니라 옛 꼬리표로 저장되거나 최신 보고서를 덮을 수 있다. 꼬리표가 지금 결과와 달라 조회에서 숨겨지고(보고서 준비 중), 그 달 INT-04를 다시 보내면 복구된다. 이 경합을 막는 조건은 두지 않는다 |
| 보고서 생성 실패 | BE는 알지 못한다. 최신 보고서가 없는 동은 아래 조회로, 이전 보고서가 남은 채 다시 만들다 실패한 동은 AI 실패 로그로 찾는다. 다시 만들 때는 그 달 INT-04를 보내며, 동만 골라 다시 만드는 방법은 없다 |
| 결과 행 삭제 | FK CASCADE로 보고서도 삭제된다. 보고서 저장이 결과 행을 되살리지 않는다 |

시연 데이터(2025-07~12)는 고정이고 12 · 13단계만 다시 돌리는 일은 드물어 이 한계를 받아들인다. 실제 운영으로 갈 때는 월별 생성 세대 표(B 방식)를 새 V 파일로 더한다.

```sql
-- 결과는 있는데 최신 보고서가 없는 동
SELECT r.adm_cd10 FROM region_result r
LEFT JOIN region_insight_report i
  ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10 AND i.result_updated_at = r.updated_at
WHERE r.period_start = DATE '2025-12-01' AND i.adm_cd10 IS NULL;
```

## 8. 화면 조회 (API-11 · 12, OpenAPI 2.4.0에서 반영)

지금(2.3.x)은 응답 모양이 그대로다. 아래 변경은 BE · 2단계 V 파일 · 새 형식 seed · FE를 각자 MR로 develop에 모은 뒤 같은 배포로 내보낸다. 지금 BE는 새 형식 행(`summary_lines` · `report`가 NULL)을 읽으면 API-11 · 12에서 500을 내므로, 새 형식 seed와 INT-06 저장을 먼저 넣지 않는다.

- API-11: 응답 모양 그대로. `insight.summary`는 `quick_insight` 한 개를 담은 배열이다. `quick_insight`가 NULL이면 `insight_generated_at`이 남아 있어도 `insight: null`이다(1단계 뷰는 옛 보고서의 생성 시각을 지우지 않는다). 줄바꿈으로 나눠 배열을 만들지 않는다.
- API-12: `report = {quickInsight, graphs: [{sheet, description}] 3개, generatedAt}` 또는 null. `headline` · `sections`는 없앤다. 결과 행이 없으면 404, 보고서가 없거나 옛 보고서면 `{report: null}`이다.
- FE는 `npm run gen:api`로 `frontend/src/api/schema.d.ts`를 다시 만든 뒤 보고서 화면을 바꾼다. GET은 생성을 실행하지 않는다.

## 9. 허용 시트 카탈로그

워크북은 `eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed`(Tableau Public)이다. 시트 이름은 DB에 그대로 저장되므로 바꾸지 않는다. BE 허용 목록과 FE 임베딩이 이 목록을 함께 쓴다.

| 시트 (`sheet`) | 내용 | 크기 |
|---|---|---|
| `EmbedDetailV01` | 행동 이상 추이 | 720×420 |
| `EmbedDetailV02` | 주요 행동 지표 | 720×560 |
| `EmbedDetailV03` | 시간대 활동 | 720×420 |
| `EmbedDetailV04` | 요일별 활동 | 720×420 |
| `EmbedDetailV05` | 성 · 연령 활동 변화 | 720×440 |
| `EmbedDetailV06` | 취약성 요인 | 900×440 |
| `EmbedDetailV07` | 월별 활동 추이 | 720×420 |
| `EmbedDetailV08` | 격자 점수 분포 | 720×440 |

행정동 매개변수 `p_detail_adm`에는 ⑥ 디테일 대시보드와 같은 값(10자리 행정동 코드)을 넣는다. 시트별 다른 매개변수는 정해지면 이 표에 적는다.

## 10. 아직 정할 것 (김민준 · 강병민)

- INT-05를 바로 202로 접수하고 뒤에서 만드는 방식
- 꼬리표를 받은 문자열 그대로 돌려주기
- 같은 달 요청이 겹치면 하던 작업을 멈추고 다시 시작하기
- 실패한 동을 작업 끝에 한 번 더 시도할지
- INT-04 · 06 재시도 횟수 · 간격
- 토큰 환경 변수 이름 (BE 구현 때 정함)
- Airflow DAG에서 INT-04 호출 작업을 붙일 위치 (강병민)
