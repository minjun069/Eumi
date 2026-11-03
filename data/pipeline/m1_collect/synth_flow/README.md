# synth_flow — 가상 시간 단위 유동 생성기

SKT 월별 유동 3종(시간대·요일·성연령, 50m 셀 × 월 일평균)을 100m 격자로 묶고,
그 월평균과 **정확히 일치**하는 시간 단위(격자 × 시각 × 성·연령 12칸) 값을 만들어 Parquet로 저장한다.
실제 데이터가 아니라 월평균을 재현한 값이다. 날짜별 흔들림과 연령 × 시간대 패턴은 만들어 넣은 것이므로 해석에 쓰지 않는다.

## 파일

| 파일 | 역할 |
|---|---|
| config.py | 경로·월·공휴일·노이즈·저장 형식 설정 |
| anchor.py | 1~2단계: 코호트 셀만 골라 50m → 100m 합산, 세 파일 총량 보정(k_wkdy, k_age), 빠진 파일은 동 평균 패턴으로 대체 |
| generate.py | 3~4단계: 날짜 × 시간 표(IPF) → 성·연령 12칸(IPF) → 하루 1파일 Parquet |
| validate.py | 5단계: 시간 단위 파일을 월평균으로 묶어 anchor와 대조, 격자별 오차 CSV |
| replay.py | 시연용: Parquet를 시각 순서로 Kafka에 발행 |
| run.py | 실행 진입점 |

## 실행

```bash
pip install -r requirements.txt

# 로컬 경로
export SKT_TIME=raw/skt_flow_time/flow_time_pop_202507_202512.xlsx
export SKT_WKDY=raw/skt_flow_wkdy/flow_wkdy_pop_202507_202512.xlsx
export SKT_AGE=raw/skt_flow_age/flow_age_pop_202507_202512.csv
export GRID_FILE=raw/dim_grid100.csv          # grid_cd, adm_cd10, adm_cd8, gx, gy, city
export SYNTH_OUT=synth

# MinIO
export MINIO_ENDPOINT=http://localhost:9000 MINIO_ACCESS_KEY=... MINIO_SECRET_KEY=...
export SKT_TIME=s3://sgi/raw/skt_flow_time/flow_time_pop_202507_202512.xlsx   # 나머지도 같은 식
export SYNTH_OUT=s3://sgi/synth

python run.py all                      # anchor → generate → validate, 6개월
python run.py generate --months 2025-12
python replay.py --months 2025-12 --speed 10   # 1시간치를 10초마다 Kafka로
```

SKT xlsx 원본은 읽는 데 파일당 2분 정도 걸린다. csv로 바꿔 두면 빠르다.

## 출력

### `synth/flow_hourly/period=YYYY-MM/day=DD.parquet` (본체)

한 행 = 100m 격자 × 1시간. 하루 1파일, 약 34~36k 격자 × 24행 ≈ 85만 행.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| ts | timestamp (Asia/Seoul) | 시작 시각. 2025-12-01 08:00 = 8시~9시 |
| grid_cd | string | 100m 격자코드 |
| m_10 … m_60p | float32 | 남성 10대·20대·30대·40대·50대·60세 이상 유동 |
| f_10 … f_60p | float32 | 여성 (같은 구간) |
| gen_version | string | 생성 규칙 버전 |

- 합계는 12칸 합. 날짜·시간대·요일은 ts에서 계산.
- 유동이 전혀 없는 격자(시간대 파일에 없는 격자)는 행이 없다.

### `synth/anchor/period=YYYY-MM.parquet` (격자별 기준값)

| 컬럼 | 설명 |
|---|---|
| period_start, grid_cd, adm_cd8, city | 키·소속 |
| h_00 … h_23 | 시간대 일평균 (시간대 파일, 50m 4칸 합) |
| w_mon … w_sun | 요일 일평균 (요일 파일 원값) |
| a_m_10 … a_f_60p | 성·연령 일평균 (성연령 파일 원값) |
| t_h | 하루 총량 = Σh (기준 총량) |
| k_wkdy, k_age | 요일·성연령 값에 곱해 총량을 t_h에 맞추는 계수 (대부분 1.00 ± 0.01) |
| src_flag | none / age_dong / wkdy_dong … (빠진 파일을 동 평균 분포로 대체한 격자) |
| n_cells_time | 합산된 50m 셀 수 (1~4) |

### `synth/check/period=YYYY-MM.csv` (검증)

격자별 최대 절대·상대 오차(시간대·요일·성연령)와 통과 여부. 생성 직후 전 격자 통과가 정상이다.

## 생성 규칙 (config.py)

| 항목 | 기본값 | 뜻 |
|---|---|---|
| BASE_SEED | 20250701 | 난수 시드. 월별 시드 = BASE_SEED + 연월. 같은 시드·버전이면 같은 값이 다시 나옴 |
| COHORT_FILE | raw/skt_cohort/2025-07_2025-12/skt_cohort_50m.csv | 합산에 쓸 50m 셀 목록(BLOCK_CD, X_COORD, Y_COORD). 6개월·3파일 모두에 있는 79,618개로, DA 분석과 같은 셀 집합. 빈 문자열이면 필터 없음 |
| HOLIDAY_MODE, HOLIDAYS | True, 2025-08-15 · 10-03 · 10-05~10-09 · 12-25 | 공휴일 하루 총량을 일요일 수준으로 초기화. 요일 평균은 그대로 유지됨 |
| DAY_NOISE_SD / CLIP | 0.08 / 0.25 | 하루 총량의 날짜별 흔들림 |
| HOUR_NOISE_SD / CLIP | 0.05 / 0.20 | 시간대 모양의 날짜별 흔들림 |
| hour_age_weight() | 60+ 낮 1.3·밤 0.6, 20~30대 저녁 1.25, 40~50대 출퇴근 1.15, 10대 수업시간 1.2 | 성·연령 × 시간대 초기 가중 (IPF가 월평균에 맞게 조정) |
| VALUE_DTYPE / VALUE_DECIMALS | float32 / None | 저장 정밀도. 아래 표 참조 |

### 저장 정밀도와 크기 (12월 기준, 33,814 격자)

| 설정 | 월 파일 크기 | 월평균 오차 | 지표 차이 |
|---|---|---|---|
| float32, 반올림 없음 (기본) | 933 MB | 상대 4e-8 | 1e-9 |
| float32, 소수 4자리 | 444 MB | 절대 ≤ 0.005 | ≤ 3e-3 |
| float64 | 1.6 GB | 1e-11 | 1e-12 |

6개월 전체는 기본 설정으로 약 5.5 GB, 생성 시간은 월당 2~3분(2코어 기준).

## 월평균이 맞는 원리

1. 세 파일의 하루 총량이 조금씩 다르므로(소수 둘째 자리 반올림) 시간대 파일 총량 t_h를 기준으로 요일·성연령 값을 비례 보정한다(k_wkdy, k_age). 비율 지표는 영향받지 않는다.
2. 날짜 × 시간 표: 초기값 = 그날 요일의 총량 × 시간대 비중 × 노이즈. 반복 비례 조정(IPF)으로 "시간대별 날짜 평균 = h", "요일별 날짜 평균 = w × k_wkdy"를 동시에 맞춘다. 수렴 오차 1e-10.
3. 각 칸을 성·연령 12칸으로 쪼갠다: 초기 비중 = 성연령 비중 × 시간대 가중. IPF로 "칸 합 = 2단계 값", "구간별 744시간 평균 = a × k_age"를 맞춘다.
4. 검증: 생성값을 월평균으로 묶어 1단계 입력과 대조한다.

## Spark 스트리밍 집계 규칙 (유동 상세 테이블)

메시지 1건(격자, 시각, 12칸)이 들어오면 `flow_detail`(period_start, grid_cd, dim_type, dim_value)에 다음과 같이 누적한다.

| dim_type | dim_value | flow_sum 에 더하는 값 | day_count |
|---|---|---|---|
| hour | 시각의 hour ('00'~'23') | 12칸 합 | 그 (격자, 시간대)에 반영된 날짜 수 |
| weekday | 날짜의 요일 (MON~SUN) | 12칸 합 | 그 요일의 반영 날짜 수 |
| sex_age | 칸 이름 (M_10 … F_60P) | 그 칸 값 | 반영 날짜 수 |

일평균 = flow_sum ÷ day_count. 월말에 이 값이 anchor(h, w × k_wkdy, a × k_age)와 같아진다.
같은 메시지를 두 번 더하지 않도록 (grid_cd, ts) 기준으로 중복을 걸러야 한다.
