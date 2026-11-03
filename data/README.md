# data — 데이터 파이프라인

지역 원본(주민등록 · 센서스 · SGIS 격자 · SKT 유동 · 공원 · 정류장 · 실거래가)을 모아 읍면동 · 100m 격자 지표를 만들고, DA 모델로 배경 취약성 점수 · 행동 이상 점수 · 위험단계를 내어 PostgreSQL 에 적재한다. 흐름은 네 모듈이다.

```
M1 수집  원본 → MinIO(raw/) · 가상 유동 → Kafka      M2 정제  원본 → 상세 · 해석용 테이블
M3 지표  상세 → 읍면동 · 격자 지표                     M4 분석  지표 → 점수 · 등급 · 위험단계 (DA 모델)
```

스크립트는 `pipeline/<모듈>/` 에 있고, 각 파일 첫 줄에 `[모듈 | 실행 위치]` 가 적혀 있다. 공통 코드는 `pipeline/common/`.

| 폴더 | 내용 |
|---|---|
| `airflow/dags/` | Airflow DAG (월 배치 스케줄) |
| `common/` | DB · MinIO 연결, 월 인자, 실거래가 API, 배경 원본 읽기, 행동 지표 산식, 유동 집계 · 적재, 모델 자산 |
| `m1_collect/` | 수동 업로드(`upload_raw`), 실거래가 API 수집 · 지오코딩, 가상 유동 생성 · Kafka 재생(`run_synth`, `synth_flow/`), 종료 신호 |
| `m2_process/` | 배경 상세 · 격자 배경 · 실거래가 적재, 유동 상세 월 배치 · 스트리밍 · 검증 |
| `m3_indicator/` | 읍면동 배경 지표, 격자 · 읍면동 행동 지표 |
| `m4_analysis/` | 읍면동 점수 · 단계(`region_result`), 격자 이상 점수(`bh_grid_anomaly`) |
| `ops/` | 월 배치 실행기(`run_month`), 기준 테이블 초기 적재(`load_dim_region`, `load_dim_grid100`), 서버 seed 생성(`make_seed`), 인프라 연결 확인 |
| `legacy/` | 1차 완성본 · DA 결과 CSV 적재 스크립트. 지금은 M2~M4 가 대체하므로 참고용 (실행하면 2차 산출값을 덮어쓴다) |

## 실행 환경

모든 스크립트는 **pipeline 컨테이너** 안에서 돈다 (`infra/docker-compose.yml` `data` 프로필, 이미지 `infra/pipeline/Dockerfile`: Python 3.12 + Spark 3.5.9 + Airflow 2.10 + `data/requirements.txt`). 호스트 venv 는 개발 · 디버깅용이고 같은 버전이다.

```bash
cd infra && docker compose --profile data up -d --build      # PostgreSQL · Flyway · MinIO(9000, 화면 9001) · Kafka(9092) · pipeline(Airflow 8081)
docker compose --profile data exec pipeline python3 pipeline/<모듈>/<스크립트>.py …     # 일반 스크립트
docker compose --profile data exec pipeline spark-submit pipeline/<모듈>/<스크립트>.py …  # Spark 잡 (유동 상세 · 격자 배경 · 검증 · 스트리밍)
```

- 호스트에서 돌릴 때: `python -m venv data/.venv && data/.venv/Scripts/python -m pip install -r data/requirements.txt` 후 `data/.venv/Scripts/python data/pipeline/<모듈>/<스크립트>.py …` (Spark 잡은 컨테이너에서만).
- 설정은 `infra/.env` (`infra/.env.example` 복사). 키: `MINIO_*`, `KAFKA_*`, `PIPELINE_DB_DSN`, `DATA_GO_KR_SERVICE_KEY`, `KAKAO_REST_KEY`, `MODEL_VERSION`(기본 v20261102), `AIRFLOW_*`.
- MinIO 버킷 `sgi`: `raw/<소스>/<기준시점>/…`(원본), `raw/skt_cohort/`(50m 코호트), `raw/model/<버전>/`(DA 모델 자산), `raw/apt_*`(실거래가 원본 · 좌표 캐시), `synth/`(가상 유동 anchor · Parquet · check).
- DB 계정 `eumi_pipeline`: `analysis` 스키마 DML 전부, `public.dim_region` UPSERT, `public.region_result` DML. TRUNCATE · DROP · CREATE 없음 → "그 달 DELETE 후 적재" 또는 UPSERT 만.
- Airflow 웹 http://localhost:8081 (계정 `.env` `AIRFLOW_ADMIN_*`), DAG 는 `data/airflow/dags/`.

## 초기 설정 (한 번)

1. 원본 파일을 팀 공유 폴더에서 받아 `data/raw/` 에 둔다 (git 제외). 목록은 인수인계서 7장.
2. `m1_collect/upload_raw.py` — `data/raw/` 를 MinIO `raw/` 로 미러링 (SKT xlsx 는 csv 로도 변환).
3. `ops/load_dim_region.py` → `ops/load_dim_grid100.py` — 행정동 47 · 100m 격자 40,942 기준 테이블.
4. DA 모델 자산 `data/raw/model/v20261102/` (모델 4개 · PCA 계수 · 임계값 · 지표 순서)와 코호트 `data/raw/skt_cohort/` 도 `upload_raw.py` 로 올라간다.
5. `m2_process/batch_bg_grid.py --year 2024` — SGIS 격자 배경(연 1회).

## 월 배치 순서

새 달 원본(주민등록 · SKT 3종 · 실거래가 API)이 준비되면 아래 순서로 돈다. 인자를 생략하면 **전월 한 달**이 대상이고, 어느 단계든 같은 달을 다시 돌리면 그 달을 지우거나 UPSERT 해 같은 결과가 나온다(재처리). 월 `YYYY-MM` 은 `--months` 로 여러 달을 줄 수 있다.

| 순서 | 모듈 | 스크립트 | 위치 | 입력 → 출력 |
|---|---|---|---|---|
| 1 | M1-1 | `m1_collect/collect_apt_trade.py` | 호스트 | 국토부 매매 · 전월세 API → `raw/apt_trade`, `raw/apt_rent` (XML 원본) |
| 2 | M1-1 | `m1_collect/geocode_apt.py` | 호스트 | 새 단지 → Kakao 좌표 · 행정동 → `raw/apt_geocode/apt_geocode.csv` |
| 3 | M1-2 | `m1_collect/run_synth.py anchor` → `generate` → `validate` | 호스트 | SKT 50m 월평균(코호트 셀) → `synth/anchor`, `synth/flow_hourly` (시간 단위 Parquet) |
| 4 | M2 | `m2_process/batch_flow_detail.py` | spark-submit | Parquet → `flow_detail` (시연 때는 `run_synth.py replay` → Kafka → `stream_flow_detail.py` 로 대신) |
| 5 | M2 | `m2_process/verify_flow_detail.py` | spark-submit | `flow_detail` 월평균 = anchor 검증 |
| 6 | M2-2 | `m2_process/batch_bg_detail.py` | 컨테이너 | 주민등록 · 센서스 · 공원 · 정류장 · 경계 → `bg_region_detail` (47개 항목) |
| 7 | M2 | `m2_process/batch_re_apt_trade.py` | 호스트 | 실거래가 XML + 좌표 캐시 → `re_apt_trade` |
| 8 | M3-1 | `m3_indicator/batch_bg_indicators.py` | 컨테이너 | `bg_region_detail` → `bg_region_indicator` (6개) |
| 9 | M3-3 | `m3_indicator/batch_bh_grid_indicators.py` | 컨테이너 | `flow_detail` → `bh_grid_indicator` (10개) |
| 10 | M3-2 | `m3_indicator/batch_bh_region_indicators.py` | 컨테이너 | `flow_detail` + `bg_region_detail` → `bh_region_indicator` (12개) |
| 11 | M4 | `m4_analysis/batch_region_result.py` | 호스트 | 배경 6 + 행동 12 → `region_result` (점수 · 등급 · 위험단계) |
| 12 | M4-3 | `m4_analysis/batch_grid_anomaly.py` | 호스트 | `bh_grid_indicator` → `bh_grid_anomaly` |
| 13 | 운영 | `ops/make_seed.py` | 호스트 | 결과 테이블 → `db/seed/R__*.sql` (서버 반영, 아래) |

- 첫 달(전월 없음)은 변화 지표 4개(h26 · h29 · h30 · h31)가 NULL → 행동 점수 · 단계를 내지 않고 `region_result` 에 넣지 않는다 (DA 방침).
- 모든 스크립트는 `--dry-run` 또는 `[OK]/[FAIL]` 검사를 찍는다. FAIL 이면 다음 단계로 가지 않는다.
- **한 번에 돌리기**: `data/.venv/Scripts/python data/pipeline/ops/run_month.py --months 2025-12` 가 13단계를 순서대로 실행한다(호스트 · 컨테이너 자동 구분). 실패하면 그 단계에서 멈추고, `--from 8` · `--only 11 12` · `--skip 3` 으로 일부만 다시 돌린다. 단계별 소요 시간 · 결과는 `data/processed/run_log/run_<시각>.json` 에 남는다.
- 재처리 리허설(2026-11-03, 2025-12 한 달 전체 재실행): 13단계 모두 통과, 총 4분(가상 유동 생성 111초 · 유동 적재 78초가 대부분). 결과 테이블 값은 재실행 전과 동일 (`re_apt_trade` 는 DELETE 후 INSERT 라 `trade_id` 만 새로 발급). `make_seed` 는 값이 바뀐 달이 있을 때만 커밋한다 (재실행만으로는 updated_at · trade_id 가 바뀌어 diff 가 커진다).
- **Airflow (`airflow/dags/eumi_monthly.py`)**: 위 1~12단계가 태스크 14개(가상 유동은 anchor · generate · validate 로 나뉨)로 들어 있다. 매월 5일 03:00 에 전월을 돌리며, 수집 → 실거래가 / 가상 유동 → 유동 상세 → 행동 지표 / 배경 상세 → 배경 지표 가지가 병렬로 돌고 M4 에서 합쳐진다. seed 생성(13)은 DAG 에 넣지 않는다.
  - 첫 태스크 `check_inputs`(`ops/check_month_inputs.py`)가 그 달의 SKT 월평균 · 주민등록 원본이 MinIO 에 있는지 보고, 없으면 그 실행 전체를 skip 한다. unpause 직후 Airflow 가 지난 스케줄 1건을 자동 실행하므로, 원본이 없는 달에 API 호출 · 적재가 일어나지 않게 하는 안전장치다.
  - 재처리: UI 의 Trigger DAG w/ config 또는 `docker compose --profile data exec pipeline airflow dags trigger eumi_monthly --conf '{"months": ["2025-12"]}'`. 실패한 태스크는 UI 에서 Clear 하면 그 태스크부터 다시 돈다.
  - 로그는 UI 또는 pipeline 컨테이너 `/opt/airflow/logs/dag_id=eumi_monthly/…` (볼륨 `airflowlogs`). 스크립트의 `[OK]/[FAIL]` 출력이 그대로 남아 실행 이력 역할을 한다.
  - 확인(2026-11-03): 12월 수동 실행 14개 태스크 성공, 실행 3분 50초.

## 모듈별 메모

### M1 수집
- 수동 업로드 원본(주민등록 · 센서스 · SGIS · SKT · 경계)은 `data/raw/` → `upload_raw.py`. API 자동 수집은 실거래가만 있다 (공원 · 정류장 API 는 아직 완성본 파일).
- 실거래가: 시군구(강남구 11680 · 춘천시 51110) × 월 × 매매/전월세를 페이지 끝까지 받아 XML 원본과 manifest(totalCount) 를 보관. 좌표는 단지(aptSeq)마다 한 번 Kakao 주소 검색 → `dim_region.geom` 포함 판정으로 행정동. 수동 보정은 `raw/apt_geocode/manual.csv`.
- 가상 유동(`m1_collect/synth_flow/`, 상세는 그 README): SKT 50m 월평균 중 **코호트 셀**(6개월 · 3파일 모두에 있는 79,618개, DA 분석과 같은 집합, `COHORT_FILE`)만 100m 격자로 합산해 월평균과 정확히 일치하는 시간 단위 값을 만든다. 6개월 29,613 격자, 약 5.5 GB. `replay.py` 가 시각 순서로 Kafka `flow_hourly` 에 발행하고 `send_eos.py` 가 마지막 하루 윈도를 닫는다.

### M2 정제
- 배경 상세: 주민등록(월) · 센서스(연, 비공개 셀은 합계 항등식으로 복원) · 공원 · 정류장 · 면적 → 47개 항목, 소수 6자리.
- 유동 상세: 월 배치는 Parquet 를 하루 단위로 집계해 그 달을 지운 뒤 넣고, 스트리밍은 Kafka → 1시간 워터마크 → 하루 윈도 → 증분 UPSERT. 검증 허용치는 상대오차 1e-5 + DECIMAL(16,4) 반올림 한계.
- 실거래가: 매매 해제 거래 제외, 전월세는 월세 0 이면 '전세'. 같은 계약월 DELETE 후 INSERT (`trade_id` 는 DB 발급).

### M3 지표
- 배경 6개 비율은 `bg_region_detail` 원값에서, 행동 지표는 `flow_detail` 일평균에서 산식(`common/bh_indicators.py`, 정의서 4.7 · 4.8)으로. 읍면동 행동 지표는 격자 지표 평균이 아니라 동 안 격자 유동을 합산한 뒤 산식을 적용하며 h20 · h21 분모는 주민 연령.
- DA 값과의 관계: 배경 지표는 1차 완성본과 일치. 격자 행동 지표는 DA 격자 입력과 일치(코호트 덕분). 읍면동 행동 지표는 동 배정 단위(100m 격자 vs 50m 점) 차이로 DA 와 최대 2% 다르다.

### M4 분석
- DA 재현 패키지의 고정 계수 · 학습 모델(`raw/model/<버전>/`)을 `common/m4_models.py` 가 읽는다 (sha256 검사, 패키지 고정 버전 numpy 2.3.5 · scipy 1.17.0 · scikit-learn 1.8.0 · joblib 1.5.3).
- 배경 점수 S = 고정 PCA 산식 → 도시별 고정 P20 · P80 으로 `bg_grade` 1~3. 행동 점수 B = 도시별 IsolationForest(−score_samples × 100) → 그 달 도시 안 P20 · P80 으로 `bh_grade` 1~3. `risk_grade` = 두 등급 합 − 1 (1~5, 5 = 최우선).
- DA 지표를 넣으면 DA 결과를 그대로 재현(차이 0). DB 지표로 내면 월 47개 동 중 0~4개의 단계가 한 칸 바뀌고, 격자는 상관 0.9999 · 상위 20% 겹침 99% 이상. 모델 학습(M4-1)은 DA 가 패키지로 비정기 실행. `bh_region_contribution` 은 비워 둔다(IsolationForest 는 기여도가 없음).

## 스트리밍 시연

```bash
# infra/ 에서 스트리밍 시작 (체크포인트 · 토픽을 비운 뒤)
docker compose --profile data exec pipeline spark-submit pipeline/m2_process/stream_flow_detail.py
# 호스트에서 12월 재생 (1시간치를 10초 간격으로) → 끝나면 종료 신호
data/.venv/Scripts/python data/pipeline/m1_collect/run_synth.py replay --months 2025-12 --speed 10
data/.venv/Scripts/python data/pipeline/m1_collect/send_eos.py --month 2025-12
```
`flow_detail` 이 쌓이는 것을 보고 M3-3 · M3-2 · M4 를 돌리면 지표 · 단계가 갱신된다. Kafka 는 월 배치 운영에는 필요 없다.

## 서버 DB 반영 (seed · 덤프)

서버(`k15b201.p.ssafy.io`)에는 아직 MinIO · Kafka · Spark 가 없어 파이프라인은 로컬에서 돌고, 결과 테이블은 두 길로 옮긴다.

- **seed (기본)**: `ops/make_seed.py` 가 데이터 파트 테이블 10개를 `db/seed/R__01_dim_region.sql`, `R__10_…`~`R__18_….sql` 로 내보낸다(약 41 MB). 커밋 → `develop` → `master` 배포 때 Flyway 가 V 마이그레이션 다음에 적용한다. 로컬도 `docker compose up -d flyway` 로 같은 파일을 쓴다. 임시 테이블에 COPY 후 `ON CONFLICT DO NOTHING` 이라 있는 행은 두고 새 행만 넣는다 (값이 바뀐 행을 바꾸려면 서버에서 해당 달을 지운 뒤 재배포).
- **덤프 (flow_detail 만)**: 760만 행 · 500 MB 라 seed 로 넣지 않는다. 서버에 필요해지면 한 테이블만 옮긴다.

```bash
docker compose -f infra/docker-compose.yml exec -T postgres sh -c "pg_dump -U postgres -d eumi --data-only -Fc -t analysis.flow_detail -f /tmp/flow.dump"
docker cp eumi-dev-postgres-1:/tmp/flow.dump data/processed/dump/flow_detail_YYYYMMDD.dump
# 서버(인프라 담당): pg_restore -U postgres -d eumi --data-only --disable-triggers flow_detail_YYYYMMDD.dump
```

## 저장소 규칙 (인수인계 요약)

- 키: 동 `adm_cd10`(행안부 10자리), 격자 `grid_cd`(SGIS 100m), 기준월 `period_start`(월 1일), 연 자료 `ref_year`. 좌표계 EPSG:5179 (`dim_region.geom` 은 GeoJSON 문자열, PostGIS 없음).
- 등급: `bg_grade` · `bh_grade` 1~3 (3 = 위험), `risk_grade` 1~5 (5 = 최우선).
- 계산 못 한 지표는 NULL (0 금지). 저장 범위를 넘는 값(격자 변화율 %p ≥ 1e4)도 NULL.
- 원본 · 생성 데이터 · 모델 자산은 git 에 넣지 않는다 (`data/raw/`, `data/processed/`). 노트북은 출력을 지우고 커밋한다. 개인정보가 든 파일은 어디에도 커밋하지 않는다.
- Kafka 토픽 `flow_hourly`: 키 grid_cd, 값 JSON (ts, grid_cd, 성 · 연령 12칸).

## 결정 기록

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-10-30 | `dim_region.geom` 은 TEXT(GeoJSON, EPSG:5179 MultiPolygon, 좌표 소수 2자리), PostGIS 없음 | `postgres:17` 이미지에 PostGIS 확장이 없다. 웹 지도용이면 `load_dim_region.py --srid 4326` |
| 2026-10-30 | 등급 방향은 인수인계 기준: `bg_grade` · `bh_grade` 1~3 (3 = 위험), `risk_grade` 1~5 (5 = 최우선) | 정의서(1 = 높음) · V5 주석 · 프론트 타입이 서로 달라 데이터 파트가 확정. 백엔드 · 프론트에 공유 |
| 2026-10-30 | MinIO 는 `bitnamilegacy/minio:2025.7.23` | MinIO 커뮤니티 이미지 배포 중단 (infra/README.md) |
| 2026-10-30 | `bg_region_detail` 에 `pop_female` · `pop_M_65P` · `pop_F_65P` 는 넣지 않음 | 완성본에 없음 (65세+ 는 `pop_total` − 0~64세 합으로 계산) |
| 2026-11-02 | `bg_region_detail.value` 를 NUMERIC(18,6) 으로 확대 (`V20261102_01`) | 면적(㎢)이 2자리로 잘리면 공원 비율 · 정류장 밀도가 둘째 자리에서 어긋남 |
| 2026-11-02 | 가상 유동은 생성기 기본 설정(float32, 반올림 없음) | 월평균 상대오차 1e-7. 용량을 줄이려면 `synth_flow/config.py` VALUE_DECIMALS=4 |
| 2026-11-02 | 제공 생성기 `io_util.py` 두 군데 수정: `list_files` 의 s3 접두사 복원, Parquet ts 를 마이크로초로 | MinIO 경로에서 validate · replay 가 파일을 못 찾았고, 나노초 ts 는 Spark 3.5 가 못 읽음. 값 규칙은 그대로 |
| 2026-11-02 | 호스트용 Kafka · DB 주소는 `127.0.0.1` | `localhost` 가 IPv6(::1)로 먼저 풀려 연결 실패 · 지연 |
| 2026-11-02 | `flow_detail` 검증 허용치에 DECIMAL(16,4) 반올림 한계(0.00005/day_count)를 더함 | 값이 작은 칸은 4자리 반올림만으로 상대오차 1e-5 를 넘음 |
| 2026-11-02 | 실거래가: 2025-07~12, 매매 · 전세 · 월세 모두. 좌표는 Kakao 주소 검색(단지당 1회), 행정동은 경계 포함 판정. 전월세 해제 거래는 제외 못 함 | API 가 좌표를 주지 않고 법정동 ≠ 행정동. 전월세 API 에 해제 항목이 없다 |
| 2026-11-03 | 가상 유동은 DA 분석과 같은 50m 코호트 셀만 합산해 생성. 행동 지표는 우리 코드 값으로 적재 | DA 격자 · 읍면동 모델이 이 셀 집합을 쓴다. 격자 합은 DA 와 일치, 읍면동은 동 배정 단위 차이로 최대 2% |
| 2026-11-03 | M4 점수 · 단계는 DA 패키지의 고정 계수 · 학습 모델(`raw/model/v20261102`)로 파이프라인이 산출. 첫 달(7월)은 `region_result` 에 넣지 않음 | DA 결과 CSV 적재 대신 새 달도 같은 방법으로. 단계가 한 칸 바뀌는 동이 월 0~4개 있음을 확인하고 허용. 7월은 변화 지표 NULL (DA 방침) |
| 2026-11-03 | 서버 반영은 Flyway seed(`db/seed/R__*`), `flow_detail` 만 덤프 | 서버에 파이프라인 런타임이 없다. 760만 행은 git · Flyway 로 무리 |
| 2026-11-03 | `pipeline/` 를 모듈 폴더(common · m1_collect · m2_process · m3_indicator · m4_analysis · ops · legacy)로 정리 | 월 배치 순서 · 실행 위치를 폴더와 docstring 태그로 드러내 Airflow DAG 와 맞춤 |
