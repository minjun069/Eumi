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

## 2차 5.2 유동 파이프라인

```
synth/flow_hourly (Parquet) ──replay.py──▶ Kafka flow_hourly ──stream_flow_detail.py──▶ analysis.flow_detail ──batch_bh_indicators.py──▶ bh_grid_indicator · bh_region_indicator
                            └──batch_flow_detail.py (Kafka 없이 과거분 적재)──▶ analysis.flow_detail
```

| 스크립트 | 역할 | 실행 |
|---|---|---|
| `pipeline/flow_agg.py` | 시간 단위 행 → flow_detail 증분(hour·weekday·sex_age, day_count) 공통 집계 | 모듈 |
| `pipeline/flow_detail_db.py` | 임시 테이블 + UPSERT 로 flow_detail 에 더하기 (TRUNCATE·CREATE 권한 없음) | 모듈 |
| `pipeline/batch_flow_detail.py` | 월 Parquet → flow_detail (그 달 삭제 후 적재). 과거분·재적재용 | `docker compose --profile data exec spark spark-submit pipeline/batch_flow_detail.py --months 2025-07` |
| `pipeline/stream_flow_detail.py` | Kafka → flow_detail 스트리밍. (grid_cd, ts) 중복 제거 → 하루 윈도가 닫히면 누적 | `docker compose --profile data exec -d spark sh -c 'spark-submit pipeline/stream_flow_detail.py > /opt/eumi/data/processed/stream.log 2>&1'` |
| `pipeline/run_synth.py replay` | Parquet 를 Kafka 에 발행 (`--days 01 02`, `--speed 10`) | `data/.venv/Scripts/python data/pipeline/run_synth.py replay --months 2025-12 --speed 10` |
| `pipeline/send_eos.py` | 재생을 마친 뒤 마지막 하루 윈도를 닫는 종료 신호 | `data/.venv/Scripts/python data/pipeline/send_eos.py --month 2025-12` |
| `pipeline/verify_flow_detail.py` | flow_detail 일평균 = anchor 확인 (상대오차 1e-5 + DECIMAL(16,4) 반올림 한계) | `spark-submit pipeline/verify_flow_detail.py --months 2025-07` |
| `pipeline/batch_bh_indicators.py` | flow_detail → 행동 지표. `--dry-run` 으로 1차 값과 비교 | `python3 pipeline/batch_bh_indicators.py --months 2025-12 [--dry-run]` |

- 적재 현황: 7~12월 flow_detail 은 batch 로 넣고 anchor 대조 통과. 스트리밍은 12월 1~2일로 검증(행·day_count 일치, 값은 메시지 반올림 오차 내).
- 시연 준비: 12월 flow_detail 삭제(`DELETE FROM analysis.flow_detail WHERE period_start = '2025-12-01'`), 토픽 비우기(`kafka-topics.sh --delete --topic flow_hourly` 후 `docker compose --profile data up -d kafka-init`), 체크포인트 삭제(`rm -rf /opt/eumi/checkpoint/flow_detail`).
- 시연 순서: 스트리밍 잡 시작 → `replay --months 2025-12 --speed 10`(1시간치를 10초마다, 하루 4분) → 끝나면 `send_eos.py --month 2025-12` → `verify_flow_detail.py --months 2025-12`.
- 호스트 kafka-python 발행 속도는 약 4.5천 건/초라 한 달(2,500만 건)을 `--speed 0`으로 밀어 넣으면 90분쯤 걸린다. 과거분은 batch 로 넣는 편이 빠르다.
- 격자 지표 중 전월 대비 변화율(h26·h29)은 유동이 극히 적은 격자에서 DECIMAL(10,6) 범위(|값| < 10⁴)를 넘을 수 있어 그 값은 NULL 로 둔다(월 1~85개). 전월에 없던 격자도 NULL.
- 스트리밍은 하루 윈도가 닫힐 때(다음 날 01:00 메시지 이후) DB 에 반영되고, 재시작 시 마지막 배치가 두 번 더해질 수 있으면 그 달을 batch 로 다시 적재한다.

## 모델 결과 적재 (분석 재현 패키지)

모델 담당이 전달한 `dual_analysis_reproducible_20261102/`(점수·단계·모델·기준값)는 `data/raw/model_package/`에 두고 MinIO `raw/model_package/`에 올린다(1.1 GB, git 제외).

| 스크립트 | 입력 → 대상 | 확인 |
|---|---|---|
| `pipeline/load_region_result.py` | `data/dong_priority_monthly.csv` → `public.region_result` (bg_score·bg_grade 1~3·bh_score·bh_grade 1~3·risk_grade 1~5) | 8~12월 235행, 월별 4·5단계 수가 패키지와 같음. 7월은 B·단계 결측이라 제외 |
| `pipeline/load_bh_grid_anomaly.py` | `data/grid_scores_monthly.csv.gz` → `analysis.bh_grid_anomaly` | 격자 중심 좌표로 `grid_cd`를 붙인다(정렬 검사 게이트). 원본 패키지 격자는 SGIS 격자와 59m 어긋나 있어, 데이터 파트가 격자 원점을 SGIS에 맞춘 재실행본(`raw/model_package_sgis/`)으로 적재했다: 27,388 격자 전부 `dim_grid100`에 1:1 매핑, 8~12월 130,177행 |

- SGIS 정렬 재실행(`data/raw/model_package_sgis/`, MinIO `raw/model_package_sgis/`): 패키지 사본에 전용 venv(Python 3.12, requirements.txt 고정 버전)를 만들고 `engines/grid/config/grid_build_protocol.json`의 격자 앵커·원점을 +50m(앵커 956633.991787/1939829.147389, 원점 956600/1939800)로 바꾼 뒤 `PYTHONUTF8=1 python run_pipeline.py --stage preprocess|analyze|export`를 돌렸다. 읍면동 경로 결과는 원본과 동일(차이 1e-14). Windows에서 두 가지를 손봤다: `PYTHONUTF8=1`(read_text 기본 인코딩), `src/common.py`의 fsync 핸들을 `rb+`로. 격자 모델 안정성 상태가 춘천시는 `exploratory_sensitive`(trim 민감도)로 나왔으니 DA 확인 필요.
- 기준값 `background_thresholds.json`·`behavior_thresholds.csv`와 모델 4개(`models/registry.json`)는 새 달 점수 산출(`src/inference.py`)에 그대로 쓴다. 패키지 의존성(scikit-learn 1.8.0 등)은 `requirements.txt` 참고.
- 읍면동 H 지표의 1차·2차 차이 원인: 패키지는 6개월·3파일 모두에 있는 50m 위치 79,618개(코호트)만 쓰고 50m 위치를 경계 폴리곤에 점 매핑(`crosswalk.csv.gz`)해 동을 배정한다. 2차 생성기에 같은 규칙을 적용하면 일치시킬 수 있다(미결).

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
| 2026-10-30 | `dim_region.geom`은 EPSG:5179 좌표의 GeoJSON MultiPolygon 문자열 (좌표 소수점 2자리) | 정의서 공통 규칙(좌표계 5179)과 인수인계 4.3을 따름. 웹 지도에서 바로 쓰려면 `load_dim_region.py --srid 4326`으로 다시 적재하면 된다 |
| 2026-10-30 | 1차 지표 적재는 완성본 값을 그대로 옮기고 점수·등급(`region_result`, `bh_grid_anomaly`)은 비워 둠 | 인수인계 1차 범위. 완성본의 `vulnerability_score`·`behavior_anomaly_score`·`grade_*`는 모델 담당 결과라 넣지 않음 |
| 2026-10-30 | `bh_region_indicator.activity_daily`는 1차에서 NULL | 완성본에 24시간 유동 합이 없음(h01 = 평균/주민 비율만 있음). 2차에서 flow_detail로 산출 |
| 2026-10-30 | `bg_region_detail`에 `pop_female`·`pop_M_65P`·`pop_F_65P`는 넣지 않음 | 완성본에 없음(65세+는 `pop_total_0_64`와의 차이로만 존재). 인수인계 미결 "65세+ 세부 구간"과 함께 결정 |
| 2026-11-02 | 가상 유동은 생성기 기본 설정(float32, 반올림 없음, 6개월 약 5.5GB)으로 생성 | 생성기 README 권장값. 월평균 상대오차 1e-7. 용량을 줄이려면 `synth_flow/config.py`의 VALUE_DECIMALS=4 (약 2.6GB, 절대오차 0.005) |
| 2026-11-02 | 제공 생성기 `synth_flow/io_util.py`의 `list_files`를 한 줄 고침 (s3 목록에 `s3://` 접두사 복원) | 원본 코드는 로컬 경로로만 검증돼 MinIO 경로에서 validate·replay가 파일을 로컬에서 찾다 실패했음. 생성 규칙·값에는 영향 없음 (anchor·check가 제공 zip과 일치) |
| 2026-11-02 | 생성기 `io_util.write_parquet`가 ts 를 마이크로초로 저장하도록 수정 | pandas 기본(나노초) Parquet 를 Spark 3.5 가 읽지 못함. 6개월 재생성(값 동일) |
| 2026-11-02 | 호스트용 Kafka 주소는 `127.0.0.1:9092` | `localhost` 가 IPv6(::1)로 먼저 풀려 kafka-python 이 연결 실패 |
| 2026-11-02 | `flow_detail` 검증 허용치에 DECIMAL(16,4) 반올림 한계(0.00005/day_count)를 더함 | 값이 작은 칸은 4자리 반올림만으로 상대오차 1e-5 를 넘음. 자릿수 변경은 DA 와 협의 |
| 2026-11-02 | 2차 산출 `bh_region_indicator` H 지표는 1차 완성본과 평균 0.25%·최대 2%(북산면) 차이 → 완성본 값 유지, `activity_daily` 만 채움 | 월 정렬·산식은 일치. 동 배정(BLOCK_CD 접두, 경계 폴리곤, dim_grid100)·셀 포함 범위 가설로는 재현 안 됨. DA 의 완성본 산출 코드 확인 필요 |

- 완성본 지표는 소수점 6자리인데 `bg_region_indicator`는 DECIMAL(5,2)·(7,2), `bg_region_detail.value`는 DECIMAL(14,2)라 2자리로 반올림되어 들어간다 (예: `area_km2` 1.740451 → 1.74). 2차 산출값과 비교할 때는 같은 자리수로 반올림해 비교한다. 자리수를 늘리려면 새 마이그레이션이 필요하다.
- 원본 데이터 공유 위치: 팀 공유 폴더에서 받아 `data/raw/`에 둔다 (MinIO 업로드는 4.4)
- 노트북은 실행 결과(출력)를 지우고 커밋하는 것을 권장합니다. 결과에 데이터가 그대로 남을 수 있습니다.
- 개인정보가 포함된 파일은 어떤 폴더에도 커밋하지 않습니다.
