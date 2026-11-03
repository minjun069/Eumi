"""가상 시간 단위 유동 생성기 설정.

모든 경로는 로컬 디렉터리 또는 s3://bucket/prefix (MinIO) 를 쓸 수 있다.
MinIO를 쓸 때는 환경변수 MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY 를 설정한다.
"""
import os

GEN_VERSION = "synth_v1"          # 생성 규칙 버전. 규칙(노이즈·가중·공휴일)을 바꾸면 올린다
BASE_SEED = 20250701              # 난수 시드. 월별 시드 = BASE_SEED + (연*100+월)

# ---- 입력: SKT 월별 원본 (50m 셀 × 월)
SKT_FILES = {
    "time": os.environ.get("SKT_TIME", "raw/skt_flow_time/flow_time_pop_202507_202512.xlsx"),
    "wkdy": os.environ.get("SKT_WKDY", "raw/skt_flow_wkdy/flow_wkdy_pop_202507_202512.xlsx"),
    "age":  os.environ.get("SKT_AGE",  "raw/skt_flow_age/flow_age_pop_202507_202512.csv"),
}
GRID_FILE = os.environ.get("GRID_FILE", "raw/dim_grid100.csv")   # grid_cd, gx, gy, adm_cd8 (100m 격자 기준)
# 50m 코호트 (6개월 · 3파일 모두에 있는 위치, DA 분석과 같은 셀 집합). 지정하면 이 목록에 있는 셀만 합산한다. "" 이면 필터 없음
COHORT_FILE = os.environ.get("COHORT_FILE", "raw/skt_cohort/2025-07_2025-12/skt_cohort_50m.csv")

# ---- 출력
OUT_ROOT = os.environ.get("SYNTH_OUT", "synth")   # 예: s3://sgi/synth
ANCHOR_DIR = f"{OUT_ROOT}/anchor"                 # anchor/period=YYYY-MM.parquet
HOURLY_DIR = f"{OUT_ROOT}/flow_hourly"            # flow_hourly/period=YYYY-MM/day=DD.parquet
CHECK_DIR  = f"{OUT_ROOT}/check"                  # check/period=YYYY-MM.csv

MONTHS = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]

# ---- 공휴일: 초기값을 일요일 총량으로 둔다 (요일 평균은 IPF가 그대로 유지)
HOLIDAY_MODE = True
HOLIDAYS = ["2025-08-15", "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25"]

# ---- 날짜·시간 변동 (월평균에는 영향 없음, 날마다 조금씩 다르게 보이도록)
DAY_NOISE_SD, DAY_NOISE_CLIP = 0.08, 0.25     # 하루 총량 ±8% 수준
HOUR_NOISE_SD, HOUR_NOISE_CLIP = 0.05, 0.20   # 시간대 모양 ±5% 수준

# ---- 성·연령 × 시간대 초기 가중 (만들어 넣은 패턴. 해석에 쓰지 말 것)
AGE_COLS = ["m_10","m_20","m_30","m_40","m_50","m_60p","f_10","f_20","f_30","f_40","f_50","f_60p"]
def hour_age_weight():
    import numpy as np
    w = np.ones((24, 12))
    teen  = [0, 6]; young = [1, 2, 7, 8]; mid = [3, 4, 9, 10]; old = [5, 11]
    for h in range(24):
        if 8 <= h <= 16: w[h, teen] = 1.2
        if h <= 5:       w[h, teen] = 0.6; w[h, old] = 0.6
        if 18 <= h <= 23: w[h, young] = 1.25
        if h in (7, 8, 9, 17, 18, 19): w[h, mid] = 1.15
        if 9 <= h <= 16: w[h, old] = 1.3
        if h >= 21:      w[h, old] = 0.6
    return w

# ---- 점수·검증
IPF_TOL, IPF_MAX_ITER = 1e-10, 200
VALUE_DTYPE = "float32"       # "float32": 7자리 유효숫자, 월평균 상대오차 ~1e-7 (권장) / "float64": 오차 1e-11, 파일 3.5배
VALUE_DECIMALS = None         # float32일 때 소수 반올림 자리. None이면 반올림 없음(권장). 4로 두면 절대오차 ≤0.005
CHECK_RTOL = 1e-6 if VALUE_DTYPE == "float64" else 1e-5   # 검증 허용 상대오차 (|생성 월평균 − 입력| ÷ 입력, 입력 ≥ 0.01인 칸)
CHECK_ATOL = 1e-6 if VALUE_DTYPE == "float64" else (5e-3 if VALUE_DECIMALS else 1e-4)  # 절대오차 허용 (입력 < 0.01인 칸)

# ---- 파일시스템 (fsspec)
def storage_options(path: str):
    if str(path).startswith("s3://"):
        return {
            "key": os.environ.get("MINIO_ACCESS_KEY"),
            "secret": os.environ.get("MINIO_SECRET_KEY"),
            "client_kwargs": {"endpoint_url": os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")},
        }
    return None
