# 인사이트 보고서 내부 연동 계약 (A 방식, 11/10 확정)

파이프라인이 월 분석을 끝내면 BE가 그 달 동 목록을 AI(FastAPI)에 넘기고, AI는 동마다 보고서를 만들어 `region_insight_report`에 **직접 저장**한다. 화면은 API-11 · 12로 읽는다. 생성 상태(실행 기록)는 저장하지 않는다(A 방식).
API 형식은 `openapi.json` 2.4.0의 `x-internal-api` INT-04 · 05 · 08과 API-11 · 12, DB는 `db/migration/V20261106_01__insight_report_slots.sql`(1단계)과 `V20261110_02__insight_report.sql`(2단계 · 시연용 보고서)이 기준이다. 11/10에 AI 구현(`ai/api.py`)에 맞춰 확정했고, AI 구현이 아직 계약과 다른 곳은 0절에 적었다.

- **저장 주체 (11/6 결정, [decisions/internal-integration.md](../decisions/internal-integration.md) 1번):** BE가 받아 저장하던 INT-06은 없앴다. 권한은 `afterMigrate.sql`로 바꿔 11/9 운영에 반영했다. 표 설명(COMMENT)의 "백엔드가 저장"은 V20261110_02에서 고쳤다. 병합된 1단계 V 파일의 머리 주석은 그대로 둔다.
- **11/10에 바뀐 것 (결정 2 · 10번):** INT-05는 `{requestId, month, dongCodes}`, 202 본문 없음(꼬리표는 AI가 직접 읽음). 생성 완료 알림 INT-08을 더했다. API-11 · 12는 새 형식(8절)으로 바뀐다.

## 0. AI 구현과 아직 다른 곳 (김민준 확인 대기)

| 항목 | 계약 | 현재 AI 구현 | 영향 |
|---|---|---|---|
| 일부만 만든 보고서 | 8칸이 모두 있어야 저장한다. 칸 누락은 DB가 거부한다(4절) | 검토를 통과한 칸만 넣고 나머지를 NULL로 저장하려 한다 | V20261110_02의 NOT NULL 제약에 걸려 그 동은 실패(`failedDongCodes`)로 끝나고, 화면은 '보고서 준비 중' |
| 저장 조건 | 결과 행 `updated_at` = 읽어 둔 꼬리표일 때만 반영(4절) | 조건 없이 UPSERT | 생성 중 결과가 다시 적재되면 옛 결과로 만든 보고서가 최신 보고서를 덮을 수 있다. 꼬리표가 달라 조회에서는 숨겨진다 |
| 같은 달 요청이 겹침 | 하던 작업을 멈추고 새 요청으로 다시 만든다(4절 INT-05) | 두 요청이 함께 돈다 | 늦게 끝난 쪽이 덮는다(7절) |
| 저장 재시도 | 일시 실패만 3번, 1초 · 5초 · 30초(6절) | 오류 종류와 상관없이 간격 없이 최대 3번 | 제약 위반도 다시 시도하고, DB 장애가 길면 실패로 끝난다 |

- 11/9 로컬 시험에서 자료 조회 도구를 고르지 않는 문제(대화 패널과 같은 작업 선택 단계)가 확인됐다. 고쳐질 때까지 실제 AI로 보고서를 만들지 않는다.

## 1. 구성 요소

| 구성 요소 | 하는 일 |
|---|---|
| 파이프라인 (Airflow) | 14단계(결과 검증)까지 성공하면 마지막 작업이 INT-04를 보낸다. 결과 행을 다시 쓸 때마다 `updated_at`을 바꾼다 |
| BE (Spring) | INT-04를 받아 그 달 동 목록으로 INT-05를 보내고, INT-08을 받아 로그에 남긴다. 보고서는 저장하지 않고 화면 조회(API-11 · 12)만 한다(`eumi_app` 읽기만) |
| AI (FastAPI) | INT-05를 접수하고 뒤에서 동마다 보고서를 만들어 `region_insight_report`에 직접 저장한다(`eumi_ai`, 4절 '보고서 저장'). 요청 하나를 끝내면 INT-08을 보낸다 |
| DB | 동 · 월마다 보고서 한 행. 결과 행이 지워지면 보고서도 지워진다(FK CASCADE) |
| 화면 (FE) | API-11(퀵 인사이트) · API-12(보고서)로 저장된 보고서를 읽는다. 조회는 생성을 일으키지 않는다 |

- 대화 패널과 같이 보고서도 AI가 DB에 직접 쓴다. 권한(`afterMigrate.sql`): `eumi_ai`는 `region_insight_report` 조회 · INSERT · UPDATE, `eumi_app`은 조회만, DELETE는 둘 다 없다.
- 보고서는 동 · 월마다 한 행이고 다시 만들면 덮어쓴다. 시트 이름은 허용 목록(9절)과 맞아야 한다.

## 2. 흐름

1. 파이프라인이 14단계까지 성공하면 Airflow 마지막 작업이 INT-04를 보낸다. 여러 달을 처리했으면 달마다 한 번 보낸다.
2. BE는 그 달 `region_result`의 `adm_cd10`을 모두 읽어 INT-05로 AI에 넘긴다.
3. AI는 202로 접수만 답하고, 뒤에서 동마다 꼬리표(3절)를 먼저 읽은 뒤 분석 데이터를 읽어 보고서를 만든다. 동시에 만드는 동 수는 AI 설정(`SETTINGS_REPORT_CONCURRENCY`, 기본 2)이다.
4. AI는 동 하나를 끝낼 때마다 저장 문장(4절 '보고서 저장') 하나로 그 동 보고서를 저장한다.
5. 저장 문장은 결과 행의 `updated_at`이 꼬리표와 같을 때만 1행을 반영한다. 0행이면 옛 결과로 만든 보고서라 버린다.
6. 생성 중 오류가 난 동은 요청 끝에 한 번 더 만든다. 모든 동을 처리하면 INT-08을 한 번 보낸다.

## 3. 꼬리표 (결과 행 `updated_at`)

- 그 동 결과 행의 `updated_at`, 즉 파이프라인이 그 결과를 마지막으로 쓴 시각이다.
- AI가 동마다 보고서에 쓸 분석 데이터보다 먼저, 또는 같은 트랜잭션에서 읽고, 저장 문장의 조건에 그대로 쓴다. BE는 넘기지 않는다.
- DB에서 읽은 TIMESTAMP 값을 그대로 쓴다. 밀리초로 줄이거나 시간대를 붙이지 않는다.
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
- BE 처리: 토큰 · 본문 검사 → 그 달 결과가 없으면 404 → INT-05 호출(`eumi.ai.http-timeout`, 기본 3초) → AI가 202면 202 `{month, targetCount}`(`targetCount`는 보낸 동 수). AI가 응답하지 않거나 202가 아니면 503 `AI_UNAVAILABLE`.
- 같은 달을 다시 보내면 그 달 보고서를 다시 만든다. 동 · 월마다 한 행은 유지되지만 AI 문장과 고른 시트는 달라질 수 있다.
- `EUMI_AI_MODE=fake`에서는 INT-05를 보내지 않고 202만 돌려준다(`targetCount`는 그 달 동 수).
- 오류: 400 `VALIDATION_ERROR` · `INVALID_JSON`, 401 `UNAUTHENTICATED`, 403 `FORBIDDEN`(다른 호출자 토큰), 404 `NOT_FOUND`, 503 `AI_UNAVAILABLE`.

### INT-05 보고서 생성 요청 (BE → AI)

`POST /internal/insight-reports/runs` · 인증 없음(내부망)

```json
{ "requestId": "0f5c2a3e-6b1d-4c8e-9a51-2d7e4f0b9c13", "month": "2025-12", "dongCodes": ["1168064000", "1168066000"] }
```

| 필드 | 규칙 |
|---|---|
| `requestId` (필수) | INT-04를 처리하며 BE가 만든 UUID. INT-04 응답의 `X-Request-Id` · `meta.requestId`와 같다(호출자가 보낸 값은 쓰지 않음). 로그와 INT-08을 잇는다 |
| `month` (필수) | `YYYY-MM` |
| `dongCodes` (필수) | 그 달 결과가 있는 모든 동의 10자리 코드. 1개 이상, 중복 없음 |

- AI 응답: 202 본문 없음(접수만, 아직 만들기 전). 본문이 잘못됐으면 400(모르는 필드, 형식, 중복 동).
- AI는 받은 `dongCodes`의 동만 만든다. 동마다 퀵 인사이트 1개와 허용 시트 8개 중 서로 다른 3개, 그래프별 설명을 만들어 아래 '보고서 저장'대로 저장한다.
- BE는 INT-05를 다시 보내지 않는다. 실패하면 INT-04가 503으로 끝나고 파이프라인이 다시 보낸다.
- **같은 달 요청이 진행 중에 또 오면:** 하던 작업을 멈추고 새 요청으로 처음부터 다시 만든다. 멈춘 작업은 그 뒤 보고서를 저장하지 않고 INT-08도 보내지 않는다. 다른 달 요청은 동시에 돌려도 된다. (11/10 AI 구현에는 아직 없다, 0절)

### 보고서 저장 (AI → DB)

AI가 `eumi_ai` 계정으로 동마다 한 번 저장한다. 같은 동 · 월을 다시 저장하면 덮어쓴다. BE API를 거치지 않는다.

| 값 | 규칙 | DB 칸 |
|---|---|---|
| `:month` · `:dong` | INT-05의 `month`(그 달 1일 DATE) · `dongCodes`의 그 동 | `period_start` · `adm_cd10` |
| `:result_updated_at` | 3절에서 읽어 둔 꼬리표 | 비교 후 `result_updated_at` |
| `:quick` | 퀵 인사이트. 앞뒤 공백을 뺀 뒤 코드 포인트 1~500자, 줄바꿈 허용. 2~3줄은 작성 권고 | `quick_insight` |
| `:g1` ~ `:g3` | `EmbedDetailV01`~`V08` 중 하나(9절), 세 개가 서로 다름. 순서 = 화면 순서 | `graph_1~3` |
| `:d1` ~ `:d3` | 그 그래프의 비교와 근거 설명. 앞뒤 공백을 뺀 뒤 코드 포인트 1~1000자 | `desc_1~3` |
| `:generated_at` | AI가 만든 시각, 시간대 포함 (TIMESTAMPTZ) | `generated_at` |

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

확인과 저장을 두 단계로 나누지 않고 이 문장 하나로 한다. 화면은 `result_updated_at`이 결과 행과 같을 때만 보고서를 보여 준다.

| 결과 | 뜻 | AI가 할 일 |
|---|---|---|
| 1행 반영 | 저장됨 | 끝 |
| 0행 | 그 동 · 월 결과 행이 없거나, 그사이 결과가 다시 쓰임(옛 결과로 만든 보고서) | 버리고 로그. 새 INT-05가 오면 그때 다시 만든다 |
| 제약 위반 (CHECK 등) | 형식이 틀림 (칸 누락, 빈 글, 시트 이름 형식, 중복 시트) | 버리고 로그 |
| 연결 오류 등 일시 실패 | DB 쪽 문제 | 이미 만든 내용으로 다시 저장 (6절). 다시 생성하지 않는다 |

- **AI가 검사:** 저장 전에 형식(글자 수, 시트 허용 목록, 서로 다른 3개, 8칸 모두)을 검사한다. 설명이 그래프 수치와 맞는지도 AI 쪽 책임이다. DB는 칸 누락, 빈 글, 시트 이름 형식, 중복 시트만 거부한다.
- 8칸을 다 채우지 못한 동은 저장하지 않고 실패한 동으로 센다. 칸 일부만 저장하지 않는다.
- 동마다 따로 저장하므로 한 동이 실패해도 다른 동은 영향이 없다.

### INT-08 보고서 생성 완료 알림 (AI → BE)

`POST /api/internal/analysis/insight-report-completions` · `Authorization: Bearer <AI 토큰>`

```json
{ "requestId": "0f5c2a3e-6b1d-4c8e-9a51-2d7e4f0b9c13", "month": "2025-12", "savedCount": 46, "failedDongCodes": ["1168066000"] }
```

| 항목 | 규칙 |
|---|---|
| 보내는 때 | INT-05 요청 하나의 모든 동(요청 끝의 다시 만들기 포함)을 처리한 뒤 한 번 |
| `requestId` · `month` | INT-05에서 받은 값 그대로 |
| `savedCount` | 저장 문장이 1행을 반영한 동 수 (0 이상) |
| `failedDongCodes` | 저장하지 못한 동(생성 실패, 저장 0행, 제약 위반, 재시도 소진). 없으면 빈 배열. 이유는 AI 로그에 남긴다 |
| 응답 | 204 본문 없음. 400 `INVALID_JSON`(모르는 필드 · 타입 오류) · `VALIDATION_ERROR`, 401 `UNAUTHENTICATED`, 403 `FORBIDDEN`(AI 토큰이 아님) |
| 재시도 | INT-07과 같이 최대 2번. 5xx · 연결 오류 · 시간 초과일 때만 한 번 더 보내고, 4xx는 다시 보내지 않는다 |
| BE 처리 | `requestId`, 월, 저장 수, 실패한 동 코드를 로그에 남긴다. 저장하지 않는다. 같은 알림을 두 번 받아도 결과가 같다 |

## 5. 인증과 노출

| 호출 | 인증 | 노출 |
|---|---|---|
| 파이프라인 → BE (INT-04) | `Authorization: Bearer <파이프라인 토큰>` | 내부망 `http://backend:8080/api/internal/…`. Nginx는 `/api/internal/`을 404로 막는다 |
| BE → AI (INT-05) | 없음 | AI 서버는 Nginx에 경로가 없어 밖에서 부를 수 없다. 내부망 `http://ai:8000` |
| AI → BE (INT-08) | `Authorization: Bearer <AI 토큰>` | 내부망 `http://backend:8080/api/internal/…` |
| AI → DB (보고서 저장) | `eumi_ai` 계정 | compose 내부망 `postgres:5432`. DB 포트는 밖에 열지 않는다 |

- `/api/internal/**`(서블릿 경로 `/internal/**`)는 브라우저 API와 분리한 별도 보안 체인에서 처리한다. 세션을 만들지 않고(stateless), CSRF 검사에서 제외하며, 서비스 토큰으로만 인증한다. 브라우저 API의 세션 · CSRF 보호는 그대로 둔다.
- 토큰이 없거나 틀리면 401 `UNAUTHENTICATED`, 그 경로를 부를 수 없는 호출자의 토큰이면 403 `FORBIDDEN`이다.
- 토큰은 BE 설정 `eumi.internal.pipeline-token`(`EUMI_PIPELINE_TOKEN`) · `eumi.internal.ai-token`(`EUMI_AI_TOKEN`)이다. AI는 같은 AI 토큰을 `SETTINGS_BACKEND_TOKEN`으로 받는다.
- 토큰 값은 서버 `/srv/eumi/.env.config`에만 두고 compose `environment`로 넘긴다. 로그 · 저장소 · 문서에 값을 남기지 않는다.
- 로그에는 `requestId`, 월, 동 코드, 상태 코드만 남긴다. 토큰 · SQL · 예외 원문 · 보고서 본문은 남기지 않는다.

## 6. 오류 · 재시도

연결 실패와 5xx(저장은 일시 실패)만 다시 시도하고, 4xx · 0행 · 제약 위반은 자동으로 다시 하지 않는다.

| 호출 | 다시 보내는 경우 | 횟수 · 간격 | 다시 보내지 않는 경우 |
|---|---|---|---|
| INT-04 | 연결 실패, 5xx, 503 `AI_UNAVAILABLE` | Airflow 재시도 3회, 5분 간격 (제안, DAG에 붙일 때 확정) | 400 · 401 · 403 · 404 |
| INT-05 | 따로 다시 보내지 않는다. 실패하면 INT-04가 503으로 끝나고 파이프라인이 다시 보낸다 | — | — |
| 동별 생성 (AI 안) | 생성 중 오류(LLM 오류 등) | 요청 끝에 한 번 더 | 8칸을 다 채우지 못함, 0행, 제약 위반 |
| 보고서 저장 (AI → DB) | DB 연결 오류 등 일시 실패 | 3회, 1초 · 5초 · 30초 (AI 구현은 0절) | 0행, 제약 위반 |
| INT-08 | 5xx, 연결 오류, 시간 초과 | 최대 2번 | 4xx |

## 7. 한계 (A 방식)

| 상황 | 동작 |
|---|---|
| 11단계(결과 적재)를 다시 돌림 | `updated_at`이 바뀌어 이전 보고서는 곧바로 숨겨지고, 이전 요청의 늦은 저장은 0행으로 버려진다 (아래 동시 진행은 예외) |
| 12 · 13단계만 다시 돌림 | `updated_at`이 그대로라 새 보고서가 저장될 때까지 이전 보고서가 보인다. 실행이 겹치면 늦게 끝난 쪽이 덮는다 |
| 결과 적재와 보고서 저장이 동시에 진행됨 | 저장 문장은 시작할 때 읽은 결과 시각으로 판단하므로, 0행이 아니라 옛 꼬리표로 저장되거나 최신 보고서를 덮을 수 있다. 꼬리표가 지금 결과와 달라 조회에서 숨겨지고(보고서 준비 중), 그 달 INT-04를 다시 보내면 복구된다. 이 경합을 막는 조건은 두지 않는다 |
| 보고서 생성 실패 | BE는 INT-08의 `failedDongCodes`를 로그에만 남긴다. 최신 보고서가 없는 동은 아래 조회로 찾는다. 다시 만들 때는 그 달 INT-04를 보내며, 동만 골라 다시 만드는 방법은 없다 |
| 결과 행 삭제 | FK CASCADE로 보고서도 삭제된다. 보고서 저장이 결과 행을 되살리지 않는다 |

시연 데이터(2025-07~12)는 고정이고 12 · 13단계만 다시 돌리는 일은 드물어 이 한계를 받아들인다. 실제 운영으로 갈 때는 월별 생성 세대 표(B 방식)를 새 V 파일로 더한다.

```sql
-- 결과는 있는데 최신 보고서가 없는 동
SELECT r.adm_cd10 FROM region_result r
LEFT JOIN region_insight_report i
  ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10 AND i.result_updated_at = r.updated_at
WHERE r.period_start = DATE '2025-12-01' AND i.adm_cd10 IS NULL;
```

## 8. 화면 조회 (API-11 · 12, OpenAPI 2.4.0)

- **배포 순서:** BE MR → DB MR(V20261110_02: 2단계 + 시연용 보고서) → FE MR 순서로 develop에 넣고, 운영에는 한 배포로 함께 내보낸다. 지금 운영 BE는 새 형식 행(`summary_lines` · `report`가 NULL)을 읽으면 API-11 · 12에서 500을 내므로, 새 형식 seed와 AI의 보고서 저장은 이 배포 전에 운영에 넣지 않는다.
- **시연용 보고서:** V20261110_02가 결과가 있는 모든 동 · 월에 `[시연용 예시]` 보고서(퀵 인사이트 + V01 · V06 · V03 + 설명, 수치는 그 동 결과 행의 점수 · 단계)를 넣는다. AI가 만든 최신 보고서는 덮지 않고, AI가 그 동을 저장하면 시연용 보고서를 덮어쓴다. 결과가 다시 적재되면 꼬리표가 달라 숨겨진다.
- **API-11:** 응답 모양 그대로. `insight.summary`는 최신 보고서(`result_updated_at` = 결과 행 `updated_at`)의 `quick_insight` 한 개를 담은 배열이다. 줄바꿈으로 나눠 배열을 만들지 않는다. 최신 보고서가 없거나 `quick_insight`가 NULL이면 `insight: null`이다.
- **API-12:** `report = {quickInsight, graphs: [{sheet, description}] 3개, generatedAt}` 또는 null. `graphs`는 `graph_1~3` 순서다. 결과 행이 없으면 404, 보고서가 없거나 옛 보고서면 `{report: null}`이다. 시트가 허용 목록(9절) 밖이면 그 보고서도 `{report: null}`로 보고 BE가 경고 로그를 남긴다.
- **FE:** `npm run gen:api`로 `frontend/src/api/schema.d.ts`를 다시 만든 뒤 보고서 화면을 바꾼다(FE MR에서). 퀵 인사이트와 설명은 일반 글(HTML 아님)이며 줄바꿈을 유지해 보여 준다. GET은 생성을 실행하지 않는다.

## 9. 허용 시트 카탈로그

워크북은 `eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed`(Tableau Public)이다. 시트 이름은 DB에 그대로 저장되므로 바꾸지 않는다. AI의 저장 전 검사와 FE 임베딩이 이 목록을 함께 쓴다. DB는 시트 이름 형식만 검사한다(`ck_region_insight_report_sheets`).

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

## 10. 정한 것 · 남은 것

**11/10에 정한 것**
- INT-05는 바로 202로 접수하고 뒤에서 만든다. 꼬리표는 AI가 직접 읽는다.
- 생성 중 오류가 난 동은 요청 끝에 한 번 더 만든다.
- INT-08은 요청마다 한 번, 전송은 최대 2번(INT-07과 같은 규칙).
- 토큰 설정 이름(5절).

**남은 것**
- 0절의 AI 구현 4가지 (김민준)
- INT-04 재시도 횟수 · 간격과 Airflow DAG에서 INT-04를 붙일 위치 (강병민)
- 시연 월 생성 범위: 동 하나에 모델 호출이 여러 번이라 GMS 사용량 한도를 보고 정한다
