# data — 데이터 분석·적재 파이프라인

| 폴더 | 용도 |
|---|---|
| `notebooks/` | 탐색·분석 노트북 |
| `pipeline/` | 월 데이터 적재·분석 스크립트 (운영자 실행, 기능명세서 2.2.1). Spark 컨테이너에서 `spark-submit pipeline/<잡>.py` |
| `raw/` | 원본 데이터 (**커밋하지 않음**) |
| `processed/` | 가공 데이터 (**커밋하지 않음**) |

## 실행 환경

- MinIO · Kafka · Spark는 `infra/docker-compose.yml`의 profile `data`. 켜는 법과 접속 정보는 [infra/README.md](../infra/README.md).
- 환경변수는 `infra/.env` 한 곳에서 관리한다. Spark 컨테이너에는 compose가 넣어 주고, 호스트에서 도는 스크립트는 python-dotenv로 `infra/.env`를 읽는다.
- `pipeline/check_infra.py`: 인프라 연결 확인 (s3a 쓰기·읽기, 테이블 11개, JDBC, DML 권한, Kafka 메시지 1건 왕복).
- 호스트 스크립트용 가상환경 (처음 한 번): `python -m venv data/.venv` 후 `data/.venv/Scripts/python -m pip install -r data/requirements.txt`
- 원본 파일은 `data/raw/` 아래에 MinIO 레이아웃(인수인계 3장)과 같은 구조로 둔다. 커밋되지 않는다.

## 적재 스크립트 (1차)

순서대로 실행한다. 각 스크립트는 입력을 검사하고 적재한 뒤 행 수를 확인해 마지막 줄에 `... PASS`를 찍는다.

| 단계 | 스크립트 | 입력 → 대상 | 확인 |
|---|---|---|---|
| 4.3 | `pipeline/load_dim_region.py` | admdongkor geojson + `dim_grid100.csv` → `public.dim_region` (UPSERT) | 47행 (강남구 22 · 춘천시 25), adm_cd8·geom 모두 채움 |
| 4.3 | `pipeline/load_dim_grid100.py` | `dim_grid100.csv` → `analysis.dim_grid100` (UPSERT) | 40,942행, 모든 격자의 adm_cd10이 dim_region에 있음 |
| 4.4 | `pipeline/upload_raw.py` | `data/raw/` 전체 → MinIO `sgi/raw/` (같은 경로로 미러링, `*.md` 제외). SKT xlsx 2개는 csv로 변환(`data/processed/skt_csv/`)해 같은 폴더에 추가 | 버킷 파일 수·크기가 로컬과 같음 (42개). 값은 바꾸지 않고 중복 제거도 하지 않음(2차) |
| 4.5 | `pipeline/load_bg_region.py` | `배경데이터셋_최종.xlsm` 읍면동_월_통합표 → `analysis.bg_region_indicator`(비율 6개) + `analysis.bg_region_detail`(정의서 5.1 항목 47개) | 282행 / 13,182행. 빈 셀은 행을 넣지 않음. 임의 동·월 값이 원본과 일치 |
| 4.5 | `pipeline/load_bh_region.py` | `행동_데이터셋_최종.xlsx` 행동_최종본 → `analysis.bh_region_indicator`(H 지표 12개) | 282행. 7월 h26·h29·h30·h31은 NULL. `activity_daily`는 완성본에 없어 NULL |
| 4.5 | `pipeline/load_bg_grid.py` | `grid100_sgis2024_강남춘천.csv` → `analysis.bg_grid_indicator`(ref_year 2024, INT 7개) | 40,942행, 컬럼별 합계가 원본과 일치 |
| 4.6 | `pipeline/run_synth.py` (+ 제공 생성기 `pipeline/synth_flow/`) | MinIO `raw/`의 SKT csv 3개 + `dim_grid100.csv` → `synth/anchor/`(격자별 월 기준값), `synth/flow_hourly/period=YYYY-MM/day=DD.parquet`(격자 × 시각 × 성·연령 12칸), `synth/check/`(검증) | anchor가 제공 zip과 같음, check 전 격자 통과. Kafka 발행(replay)은 2차 |

```bash
data/.venv/Scripts/python data/pipeline/load_dim_region.py
data/.venv/Scripts/python data/pipeline/load_dim_grid100.py
data/.venv/Scripts/python data/pipeline/upload_raw.py
data/.venv/Scripts/python data/pipeline/load_bg_region.py
data/.venv/Scripts/python data/pipeline/load_bh_region.py
data/.venv/Scripts/python data/pipeline/load_bg_grid.py
data/.venv/Scripts/python data/pipeline/run_synth.py all      # anchor → generate → validate, 6개월
```

`run_synth.py`는 `infra/.env`의 MinIO 접속 정보를 읽어 입력·출력 경로를 MinIO로 지정한 뒤 `synth_flow/run.py`를 그대로 실행한다. 월을 고르려면 `generate --months 2025-12`처럼 인자를 넘긴다. 생성 규칙·출력 형식·Spark 스트리밍 집계 규칙은 [pipeline/synth_flow/README.md](pipeline/synth_flow/README.md).

## 2차 5.1 배경 배치

원본(주민등록 · 등록센서스 · 공원 · 정류장 · 경계 · SGIS)에서 배경 상세·지표를 코드로 다시 만들어 1차 완성본 값과 일치하는지 확인한 뒤 적재한다. Spark 컨테이너에서 실행하며 입력은 모두 MinIO `raw/`.

| 스크립트 | 입력 → 대상 | 확인 |
|---|---|---|
| `pipeline/bg_sources.py` | 주민등록(행정동 10자리, 월) · 센서스(통계청 8자리, 연, 'X' 역산) · 공원·정류장(패키지 매핑표 `park_allocations` · `bus_stops`) · 동 면적(geojson EPSG:5179) → 동 × 월 × 항목 47개 | 모듈 |
| `pipeline/batch_bg_detail.py` (M2-2) | 위 원값 → `bg_region_detail`(그 달 삭제 후 적재) | `--dry-run`: 1차 값과 원값 13,182행 일치(2자리 기준), 센서스 복원 38셀 = 완성본 '결측복원근거' |
| `pipeline/batch_bg_indicators.py` (M3) | `bg_region_detail` → 비율 6개 → `bg_region_indicator`(UPSERT) | `--dry-run`: 지표 282행 × 6개 모두 1차와 일치 |
| `pipeline/batch_bg_grid.py` | SGIS 100m csv 15개(`raw/sgis_grid/<연도>/`) → `bg_grid_indicator`(그 연도 삭제 후 적재, 기록 없는 격자 0) | `--dry-run`: 40,942 격자 7개 값 모두 1차와 일치 |

```bash
docker compose --profile data exec spark python3 pipeline/batch_bg_detail.py --months 2025-07 2025-08 ... [--dry-run]
docker compose --profile data exec spark python3 pipeline/batch_bg_indicators.py --months 2025-07 2025-08 ... [--dry-run]
docker compose --profile data exec spark spark-submit pipeline/batch_bg_grid.py --year 2024 [--dry-run]
```

- 센서스 비공개('X') 셀은 행 합계식(총계 = Σ구성)과 시군구 합계식(시군구 = Σ동)으로 역산한다. 미확정 셀이 하나면 나머지 값, 나머지가 0이면 전부 0. 못 풀면 행을 넣지 않는다(5인·6인 이상 가구 2개 동).
- 새 달 운영: 주민등록 csv를 `raw/resident_pop/<기간>/`에 올리면 그 달을 지정해 돌린다. 센서스·공원·정류장·면적은 최근 값을 매달 반복한다.
- 공원·정류장의 동 귀속표는 모델 패키지(`raw/model_package/.../analysis/background_checks/data/environment/`)의 것을 쓴다. Spark 이미지에 shapely · pyproj 를 추가했다(동 면적 계산).

## 저장소 규칙 (인수인계 요약)

- MinIO 버킷 `sgi`: `raw/<소스>/<기준시점>/<파일명>`, 완성본은 `raw/final_sets/`, 가상 유동은 `synth/`
- Kafka 토픽 `flow_hourly`: 키 grid_cd, 값 JSON (ts, grid_cd, 성·연령 12칸)
- DB: `dim_region`·`region_result`는 `public`, 나머지 파이프라인 테이블은 `analysis` 스키마. 계정 `eumi_pipeline`은 TRUNCATE·DROP·CREATE 권한이 없다 → Spark `overwrite` 금지, "그 달 삭제 후 append" 또는 `INSERT ... ON CONFLICT`. `dim_region`은 DELETE 권한도 없으므로 UPSERT만
- 키: 동 `adm_cd10`, 격자 `grid_cd`, 기준월 `period_start`(월 1일), 연 자료 `ref_year`. 좌표계 EPSG:5179
- 계산 못 한 지표는 NULL (0 금지)

## 결정 기록

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-10-30 | `dim_region.geom`은 TEXT(GeoJSON), PostGIS 없음 | DB가 `postgres:17` 이미지라 PostGIS 확장이 없다 (`SELECT PostGIS_Version()` 실패, `pg_available_extensions`에도 없음). 테이블 정의서의 GEOMETRY 표기는 TEXT로 고친다 |
| 2026-10-30 | 등급 방향은 인수인계 기준: `bg_grade`·`bh_grade` 1~3 (3 = 위험), `risk_grade` 1~5 (5 = 최우선) | 정의서(1 = 높음)·V5 주석(1~5)·프론트 타입(1~5)이 서로 달라 데이터 파트가 확정. V5의 CHECK(1~5)는 그대로 통과한다. 백엔드·프론트에 공유 필요 |
| 2026-10-30 | MinIO는 `bitnamilegacy/minio:2025.7.23` | MinIO 커뮤니티 이미지 배포 중단 (infra/README.md 참고) |
| 2026-11-02 | `bg_region_detail.value`를 NUMERIC(18,6)으로 확대 (`db/migration/V20261102_01__bg_region_detail_value_scale.sql`) | DECIMAL(14,2)로는 동 면적이 1.74로 잘려 M3가 DB에서 계산한 공원 비율·정류장 밀도가 1차와 둘째 자리에서 어긋남. 확대 후 전부 일치 |
| 2026-10-30 | `dim_region.geom`은 EPSG:5179 좌표의 GeoJSON MultiPolygon 문자열 (좌표 소수점 2자리) | 정의서 공통 규칙(좌표계 5179)과 인수인계 4.3을 따름. 웹 지도에서 바로 쓰려면 `load_dim_region.py --srid 4326`으로 다시 적재하면 된다 |
| 2026-10-30 | 1차 지표 적재는 완성본 값을 그대로 옮기고 점수·등급(`region_result`, `bh_grid_anomaly`)은 비워 둠 | 인수인계 1차 범위. 완성본의 `vulnerability_score`·`behavior_anomaly_score`·`grade_*`는 모델 담당 결과라 넣지 않음 |
| 2026-10-30 | `bh_region_indicator.activity_daily`는 1차에서 NULL | 완성본에 24시간 유동 합이 없음(h01 = 평균/주민 비율만 있음). 2차에서 flow_detail로 산출 |
| 2026-10-30 | `bg_region_detail`에 `pop_female`·`pop_M_65P`·`pop_F_65P`는 넣지 않음 | 완성본에 없음(65세+는 `pop_total_0_64`와의 차이로만 존재). 인수인계 미결 "65세+ 세부 구간"과 함께 결정 |
| 2026-11-02 | 가상 유동은 생성기 기본 설정(float32, 반올림 없음, 6개월 약 5.5GB)으로 생성 | 생성기 README 권장값. 월평균 상대오차 1e-7. 용량을 줄이려면 `synth_flow/config.py`의 VALUE_DECIMALS=4 (약 2.6GB, 절대오차 0.005) |
| 2026-11-02 | 제공 생성기 `synth_flow/io_util.py`의 `list_files`를 한 줄 고침 (s3 목록에 `s3://` 접두사 복원) | 원본 코드는 로컬 경로로만 검증돼 MinIO 경로에서 validate·replay가 파일을 로컬에서 찾다 실패했음. 생성 규칙·값에는 영향 없음 (anchor·check가 제공 zip과 일치) |

- 완성본 지표는 소수점 6자리인데 `bg_region_indicator`는 DECIMAL(5,2)·(7,2)라 2자리로 반올림되어 들어간다. `bg_region_detail.value`는 V20261102_01 마이그레이션으로 NUMERIC(18,6)이 되어 원값(면적 1.740451 ㎢ 등)이 그대로 들어간다. 2차 산출값과 비교할 때는 지표만 2자리로 반올림해 비교한다.
- 원본 데이터 공유 위치: 팀 공유 폴더에서 받아 `data/raw/`에 둔다 (MinIO 업로드는 4.4)
- 노트북은 실행 결과(출력)를 지우고 커밋하는 것을 권장합니다. 결과에 데이터가 그대로 남을 수 있습니다.
- 개인정보가 포함된 파일은 어떤 폴더에도 커밋하지 않습니다.
