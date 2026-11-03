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

`run_synth.py`는 `infra/.env`의 MinIO 접속 정보를 읽어 입력·출력 경로를 MinIO로 지정한 뒤 `synth_flow/run.py`를 그대로 실행한다. 코호트 목록(`COHORT_FILE`, MinIO `raw/skt_cohort/2025-07_2025-12/skt_cohort_50m.csv`)에 있는 50m 셀만 합산한다(2차, 결정 기록 참고). 월을 고르려면 `generate --months 2025-12`처럼 인자를 넘긴다. 생성 규칙·출력 형식·Spark 스트리밍 집계 규칙은 [pipeline/synth_flow/README.md](pipeline/synth_flow/README.md).

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

## 2차 5.2 유동 파이프라인

```
synth/flow_hourly (Parquet) ──replay.py──▶ Kafka flow_hourly ──stream_flow_detail.py──▶ analysis.flow_detail ──batch_bh_grid_indicators.py (M3-3)──▶ bh_grid_indicator
                                                                                 └─batch_bh_region_indicators.py (M3-2, + bg_region_detail)──▶ bh_region_indicator
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
| `pipeline/batch_bh_grid_indicators.py` | M3-3: flow_detail → `bh_grid_indicator` (지표 10개 + activity). 그 달 삭제 후 재적재 | `python3 pipeline/batch_bh_grid_indicators.py --months 2025-12 [--dry-run]` |
| `pipeline/batch_bh_region_indicators.py` | M3-2: flow_detail(동 안 격자 합산) + bg_region_detail(주민 연령) → `bh_region_indicator` (지표 12개 + activity). 12개 + activity 전부 UPSERT. 산식은 `bh_indicators.py` 공통 | `python3 pipeline/batch_bh_region_indicators.py --months 2025-12 [--dry-run]` |

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

## 2차 5.3 실거래가 수집 (M1-1)

국토교통부 아파트 매매 상세(`RTMSDataSvcAptTradeDev`)·전월세(`RTMSDataSvcAptRent`) API를 월 단위로 호출해 원본 XML을 MinIO에 보관하고, 단지별 좌표를 붙여 `analysis.re_apt_trade`에 적재한다. 대상은 강남구(법정동 시군구 11680)·춘천시(51110), 호출은 호스트 `data/.venv`에서 한다(월 수천 행이라 Spark 없이 pandas). 키는 `infra/.env`의 `DATA_GO_KR_SERVICE_KEY`(공공데이터포털 '일반 인증키 (Decoding)')와 `KAKAO_REST_KEY`.

| 순서 | 스크립트 | 하는 일 | 확인 |
|---|---|---|---|
| 1 | `pipeline/collect_apt_trade.py` | 시군구 × 월 × 종류별로 페이지 끝까지 받아 응답 그대로 `raw/apt_trade/<YYYYMM>/<LAWD>_p<NN>.xml`, `raw/apt_rent/…`에 저장. `_manifest.json`에 totalCount·건수·시각. 인자 없으면 전월 한 달, 이미 받은 달은 건너뜀(`--force`) | 받은 건수 = totalCount. 2025-07~12 매매 3,343 + 전월세 16,071 = 19,414건 |
| 2 | `pipeline/geocode_apt.py` | 원본에 나온 단지(aptSeq)마다 한 번만 Kakao 주소 검색(도로명 → 실패 시 지번)으로 WGS84 좌표를 받고, EPSG:5179로 바꿔 `dim_region.geom` 포함 판정으로 행정동을 붙여 `raw/apt_geocode/apt_geocode.csv`에 캐시. 경계 밖이면 200m 안 가장 가까운 동(`nearest`). `raw/apt_geocode/manual.csv`(apt_seq, lon, lat)로 수동 보정 | 단지 731개 전부 `ok`(경계 안). Kakao가 주는 행정동명과 729개 일치, 2개는 경계(0.9m)·대단지 출입구 차이 |
| 3 | `pipeline/batch_re_apt_trade.py` | 원본 + 좌표 캐시 → 같은 계약월 DELETE 후 INSERT(`trade_id`는 DB 발급). 매매 해제 거래(`cdealType='O'`) 제외, 전월세는 월세 0이면 '전세'. `--dry-run` | 넣은 행 = 원본 − 해제 − 좌표없음. 6개월 19,178행(해제 236 제외, 좌표 없음 0), 재실행해도 행 수 동일 |

```bash
data/.venv/Scripts/python data/pipeline/collect_apt_trade.py --months 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12
data/.venv/Scripts/python data/pipeline/geocode_apt.py      --months 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12
data/.venv/Scripts/python data/pipeline/batch_re_apt_trade.py --months 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12
```

새 달은 세 스크립트를 인자 없이 차례로 돌리면 전월 한 달이 처리된다(실거래 신고 기한이 30일이라 계약월 다음다음 달 초에 돌리는 것을 권장. 스케줄러 연결은 배포 환경에서). 공원·정류장 API 수집은 아직 없다(1차 완성본 파일로 적재).
## 2차 M4 분석 (점수 · 위험단계)

DA 재현 패키지의 고정 계수와 학습된 모델을 그대로 써서 M3 지표 테이블에서 점수와 단계를 낸다. 모델 학습(M4-1)은 DA 가 패키지로 비정기 실행하고, 파이프라인은 그 결과물만 쓴다.

| 스크립트 | 입력 → 출력 | 방법 |
|---|---|---|
| `pipeline/m4_models.py` | MinIO `raw/model/<버전>/` (기본 `v20261102`) | 모델 4개(`.joblib`, sha256 검사) · 배경 PCA 계수 · 배경 고정 임계값 · 지표 순서를 읽는 공통 모듈 |
| `pipeline/batch_region_result.py` | `bg_region_indicator`(6) + `bh_region_indicator`(12) → `public.region_result` | M4-2 배경 점수 S = 고정 PCA 산식, 도시별 고정 P20·P80 → `bg_grade` 1~3. M4-3 행동 점수 B = 도시별 IsolationForest, −score_samples×100 → `bh_score`. M4-4 그 달 도시 안 B 의 P20·P80 → `bh_grade` 1~3, `risk_grade` = 두 등급 합 − 1. UPSERT 만 |
| `pipeline/batch_grid_anomaly.py` | `bh_grid_indicator`(10) → `analysis.bh_grid_anomaly` | 도시별 격자 IsolationForest. 그 달 삭제 후 적재 |

```bash
data/.venv/Scripts/python data/pipeline/batch_region_result.py --months 2025-08 2025-09 2025-10 2025-11 2025-12   # 인자 없으면 전월
data/.venv/Scripts/python data/pipeline/batch_grid_anomaly.py  --months 2025-08 2025-09 2025-10 2025-11 2025-12
```

- 행동 지표가 하나라도 NULL 인 동 · 격자(첫 달은 변화 지표 4개가 NULL)는 점수를 내지 않고 행도 넣지 않는다. 그래서 7월은 `region_result` 에 없다 (DA 와 같은 방침).
- 모델 자산은 `data/raw/model/<버전>/`(git 제외)에 두고 `upload_raw.py` 또는 직접 MinIO 에 올린다. 새 버전은 폴더를 새로 만들고 `MODEL_VERSION` 으로 고른다. 패키지 고정 버전(numpy 2.3.5 · scipy 1.17.0 · scikit-learn 1.8.0 · joblib 1.5.3)은 `requirements.txt` 에 있다.
- 검증(2026-11-03): DA 지표 파일을 넣으면 DA 점수 · 등급 · 단계를 그대로 재현(차이 0). DB 지표(M3)로 내면 읍면동은 월 47개 중 0~4개 동의 단계가 한 칸 바뀌고(행동 지표의 동 배정 차이), 위험 4~5단계 집합은 월마다 13~15개 중 13~14개가 같다. 격자는 DA 와 점수 상관 0.9999, 상위 20% 겹침 99% 이상.
- `bh_region_contribution` 은 비워 둔다 (IsolationForest 는 지표별 기여도를 주지 않음. 배경 점수 S 의 지표별 기여도는 `m4_models.background_score()` 가 돌려주므로 필요하면 적재 가능).

## 서버 DB 반영 (seed · 덤프)

서버(`k15b201.p.ssafy.io`)에는 MinIO · Kafka · Spark 가 없어 파이프라인은 로컬에서 돌고, 결과 테이블은 두 길로 옮긴다.

- **seed (기본)**: `data/.venv/Scripts/python data/pipeline/make_seed.py` 가 로컬 DB 의 데이터 파트 테이블 10개를 `db/seed/R__01_dim_region.sql`, `R__10_…`~`R__18_….sql` 로 내보낸다(약 41 MB). 커밋 → `develop` → `master` 배포 때 Flyway 가 V 마이그레이션 다음에 적용한다. 로컬도 `docker compose up -d flyway` 로 같은 파일을 쓴다. R 파일은 내용이 바뀌면 다시 실행되며 `ON CONFLICT DO NOTHING` 이라 있는 행은 두고 새 행만 넣는다 (값이 바뀐 행을 바꾸려면 서버에서 해당 달을 지운 뒤 재배포).
- **덤프 (flow_detail 만)**: 760만 행 · 500 MB 라 seed 로 넣지 않는다. 서버에 필요해지면 아래처럼 한 테이블만 옮긴다.

```bash
docker compose -f infra/docker-compose.yml exec -T postgres sh -c "pg_dump -U postgres -d eumi --data-only -Fc -t analysis.flow_detail -f /tmp/flow.dump"
docker cp eumi-dev-postgres-1:/tmp/flow.dump data/processed/dump/flow_detail_YYYYMMDD.dump
# 서버(인프라 담당): pg_restore -U postgres -d eumi --data-only --disable-triggers flow_detail_YYYYMMDD.dump
```

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
| 2026-11-02 | 생성기 `io_util.write_parquet`가 ts 를 마이크로초로 저장하도록 수정 | pandas 기본(나노초) Parquet 를 Spark 3.5 가 읽지 못함. 6개월 재생성(값 동일) |
| 2026-11-02 | 호스트용 Kafka 주소는 `127.0.0.1:9092` | `localhost` 가 IPv6(::1)로 먼저 풀려 kafka-python 이 연결 실패 |
| 2026-11-02 | `flow_detail` 검증 허용치에 DECIMAL(16,4) 반올림 한계(0.00005/day_count)를 더함 | 값이 작은 칸은 4자리 반올림만으로 상대오차 1e-5 를 넘음. 자릿수 변경은 DA 와 협의 |
| 2026-11-02 | 실거래가 좌표는 Kakao 주소 검색(단지 aptSeq 당 1회), 행정동은 좌표를 `dim_region.geom`에 포함 판정 | API는 법정동·주소만 주고 좌표가 없다. 법정동 ≠ 행정동이라 좌표를 거쳐야 하며, 격자(`dim_grid100`)와 같은 경계 데이터 기준으로 동을 정한다. Kakao 행정동명과 731개 중 2개 차이는 경계 0.9m·대단지 출입구 위치 |
| 2026-11-02 | 실거래가 수집 기간 2025-07~2025-12, 매매·전세·월세 모두. 전월세 해제 거래는 제외하지 않음 | 다른 데이터와 기간을 맞춤. 전월세 API에는 해제 항목이 없다 |
| 2026-11-02 | 호스트용 DB 주소도 `127.0.0.1` | Kafka 와 같은 IPv6 문제로 `localhost` 접속이 2분 넘게 걸림 |
| 2026-11-03 | 가상 유동은 DA 분석과 같은 50m 코호트 셀(6개월·3파일 모두에 있는 79,618개, `raw/skt_cohort/`)만 합산해 생성. 행동 지표는 우리 코드 값으로 적재 | DA 격자·읍면동 모델이 이 셀 집합을 쓴다. 격자 합은 DA 격자 패널과 일치(1e-12). 읍면동은 동 배정 단위(100m 격자 vs 50m 점) 차이로 DA 값과 최대 2% 안에서 다르며, 산식·셀 집합은 같다 |
| 2026-11-03 | M4 점수 · 단계는 DA 패키지의 고정 계수 · 학습 모델(`raw/model/v20261102`)로 파이프라인이 산출. 입력은 DB 의 M3 지표 | DA 결과 CSV 적재(`load_region_result.py` 등) 대신 새 달도 같은 방법으로 낼 수 있게. 입력 지표가 DA 와 조금 달라(동 배정 단위) 단계가 한 칸 바뀌는 동이 월 0~4개 있음을 확인하고 허용 |
| 2026-11-03 | 첫 달(7월)은 행동 점수 · 단계를 내지 않고 `region_result` 에 넣지 않음 | 전월이 없어 변화 지표 4개가 NULL. DA 와 같은 방침. `region_result` 의 bh_score · risk_grade 가 NOT NULL |

- 완성본 지표는 소수점 6자리인데 `bg_region_indicator`는 DECIMAL(5,2)·(7,2)라 2자리로 반올림되어 들어간다. `bg_region_detail.value`는 V20261102_01 마이그레이션으로 NUMERIC(18,6)이 되어 원값(면적 1.740451 ㎢ 등)이 그대로 들어간다. 2차 산출값과 비교할 때는 지표만 2자리로 반올림해 비교한다.
- 원본 데이터 공유 위치: 팀 공유 폴더에서 받아 `data/raw/`에 둔다 (MinIO 업로드는 4.4)
- 노트북은 실행 결과(출력)를 지우고 커밋하는 것을 권장합니다. 결과에 데이터가 그대로 남을 수 있습니다.
- 개인정보가 포함된 파일은 어떤 폴더에도 커밋하지 않습니다.
