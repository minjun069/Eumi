"""1~2단계: SKT 50m 월별 3종 → 100m 격자 기준값(anchor).

anchor 한 행 = 격자 × 월. 컬럼:
  period_start, grid_cd, adm_cd8, city,
  h_00..h_23 (시간대 일평균, 시간대 파일 4칸 합),
  w_mon..w_sun (요일 일평균, 요일 파일),  a_m_10..a_f_60p (성연령 일평균, 성연령 파일),
  t_h (하루 총량 = Σh), k_wkdy, k_age (요일·성연령 총량을 t_h에 맞추는 보정계수),
  src_flag (none / wkdy_dong / wkdy_city / age_dong / age_city), n_cells_time (합산된 50m 셀 수)
COHORT_FILE 이 있으면 그 목록(BLOCK_CD, X_COORD, Y_COORD)에 있는 50m 셀만 합산한다 (DA 분석과 같은 셀 집합).
"""
import numpy as np, pandas as pd, fsspec
from config import SKT_FILES, GRID_FILE, COHORT_FILE, ANCHOR_DIR, AGE_COLS, storage_options
from calendar_util import month_days
from io_util import write_parquet

T_SRC = [f"TMST_{i:02d}" for i in range(24)]
W_SRC = ["FLOW_POP_CNT_MON","FLOW_POP_CNT_TUS","FLOW_POP_CNT_WED","FLOW_POP_CNT_THU","FLOW_POP_CNT_FRI","FLOW_POP_CNT_SAT","FLOW_POP_CNT_SUN"]
A_SRC = ["MAN_FLOW_POP_CNT_10G","MAN_FLOW_POP_CNT_20G","MAN_FLOW_POP_CNT_30G","MAN_FLOW_POP_CNT_40G","MAN_FLOW_POP_CNT_50G","MAN_FLOW_POP_CNT_60GU",
         "WMAN_FLOW_POP_CNT_10G","WMAN_FLOW_POP_CNT_20G","WMAN_FLOW_POP_CNT_30G","WMAN_FLOW_POP_CNT_40G","WMAN_FLOW_POP_CNT_50G","WMAN_FLOW_POP_CNT_60GU"]
H_COLS = [f"h_{i:02d}" for i in range(24)]
W_COLS = ["w_mon","w_tue","w_wed","w_thu","w_fri","w_sat","w_sun"]
A_COLS = [f"a_{c}" for c in AGE_COLS]

def load_skt(kind: str) -> pd.DataFrame:
    path = SKT_FILES[kind]
    opts = storage_options(path)
    if path.endswith(".pkl"):
        df = pd.read_pickle(path)
    elif path.endswith(".csv"):
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"BLOCK_CD": str}, storage_options=opts)
    else:
        df = pd.read_excel(path, sheet_name=0, dtype={"BLOCK_CD": str}, storage_options=opts)
    df["STD_YM"] = df["STD_YM"].astype(int)
    # 완전 중복 행 제거 (12월 원본에 전체 행 중복이 있었음)
    df = df.drop_duplicates()
    if COHORT_FILE:
        before = len(df)
        df["kx"], df["ky"] = df.X_COORD.round(3), df.Y_COORD.round(3)
        df = df.merge(load_cohort(), on=["BLOCK_CD", "kx", "ky"], how="inner", validate="many_to_one").drop(columns=["kx", "ky"])
        print(f"[anchor] {kind}: 코호트 필터 {before:,} → {len(df):,}행")
    return df

_cohort = None
def load_cohort() -> pd.DataFrame:
    """코호트 목록 (BLOCK_CD, X_COORD, Y_COORD). 좌표는 소수 3자리로 맞춰 조인한다."""
    global _cohort
    if _cohort is None:
        c = pd.read_csv(COHORT_FILE, encoding="utf-8-sig", dtype={"BLOCK_CD": str}, storage_options=storage_options(COHORT_FILE))
        c["kx"], c["ky"] = c.X_COORD.round(3), c.Y_COORD.round(3)
        _cohort = c[["BLOCK_CD", "kx", "ky"]].drop_duplicates()
    return _cohort

def to_grid100(df: pd.DataFrame, cols, grid: pd.DataFrame) -> pd.DataFrame:
    """50m 셀 → 100m 격자 합산. 연구지역(grid 목록) 안의 격자만 남김."""
    df = df.copy()
    df["gx"] = (df.X_COORD // 100 * 100).astype(int)
    df["gy"] = (df.Y_COORD // 100 * 100).astype(int)
    g = df.groupby(["STD_YM", "gx", "gy"])[cols].sum().reset_index()
    g["n_cells"] = df.groupby(["STD_YM", "gx", "gy"]).size().values
    return g.merge(grid[["gx", "gy", "grid_cd", "adm_cd8", "city"]], on=["gx", "gy"], how="inner")

def _fallback_shares(g: pd.DataFrame, cols, keys):
    """dong(adm_cd8) 또는 city 단위 분포 비중. 반환: keys → (len(cols),) 비중"""
    s = g.groupby(keys)[cols].sum()
    tot = s.sum(axis=1).replace(0, np.nan)
    return s.div(tot, axis=0)

def build_anchor(period: str, gt: pd.DataFrame, gw: pd.DataFrame, ga: pd.DataFrame) -> pd.DataFrame:
    ym = int(period.replace("-", ""))
    days, wd, cnt = month_days(period)
    D = len(days)
    t = gt[gt.STD_YM == ym].copy()
    t["t_h"] = t[T_SRC].sum(axis=1)
    t = t[t.t_h > 0]
    w = gw[gw.STD_YM == ym].set_index("grid_cd")
    a = ga[ga.STD_YM == ym].set_index("grid_cd")
    # 요일 · 성연령 값 붙이기 (없으면 NaN)
    W = np.array(w[W_SRC].reindex(t.grid_cd).to_numpy(dtype=float), copy=True)
    A = np.array(a[A_SRC].reindex(t.grid_cd).to_numpy(dtype=float), copy=True)
    t_h = t.t_h.to_numpy()
    flag = np.array(["none"] * len(t), dtype=object)
    # ---- 요일 fallback: 격자에 요일 값이 없거나 전부 0이면 동 → 도시 비중 × t_h
    tw = np.nan_to_num(W, nan=0.0) @ cnt / D
    need = ~(tw > 0)
    if need.any():
        for level, keys in (("dong", "adm_cd8"), ("city", "city")):
            if not need.any(): break
            sh = _fallback_shares(w[w.index.isin(t.grid_cd)], W_SRC, keys)   # 요일별 합 비중
            m = t[keys].map(lambda k: k in sh.index).to_numpy() & need
            if m.any():
                shares = sh.reindex(t.loc[m, keys]).to_numpy()
                # 비중 → 일평균 요일값: 요일별 합 비중 s_w 를 n_w 로 나눠 "하루 평균" 비중으로 바꾸고 t_h 에 맞춤
                daily = shares / cnt
                daily = daily / (daily @ cnt / D)[:, None]
                W[m] = daily * t_h[m, None]
                flag[m] = np.where(flag[m] == "none", f"wkdy_{level}", flag[m] + f"+wkdy_{level}")
                need = need & ~m
    # ---- 성연령 fallback
    ta = np.nan_to_num(A, nan=0.0).sum(axis=1)
    need = ~(ta > 0)
    if need.any():
        for level, keys in (("dong", "adm_cd8"), ("city", "city")):
            if not need.any(): break
            sh = _fallback_shares(a[a.index.isin(t.grid_cd)], A_SRC, keys)
            m = t[keys].map(lambda k: k in sh.index).to_numpy() & need
            if m.any():
                A[m] = sh.reindex(t.loc[m, keys]).to_numpy() * t_h[m, None]
                flag[m] = np.where(flag[m] == "none", f"age_{level}", flag[m] + f"+age_{level}")
                need = need & ~m
    tw = W @ cnt / D
    ta = A.sum(axis=1)
    out = pd.DataFrame({"period_start": pd.Timestamp(f"{period}-01").date(), "grid_cd": t.grid_cd.values,
                        "adm_cd8": t.adm_cd8.values, "city": t.city.values})
    out[H_COLS] = t[T_SRC].to_numpy()
    out[W_COLS] = W
    out[A_COLS] = A
    out["t_h"] = t_h
    out["k_wkdy"] = t_h / tw
    out["k_age"] = t_h / ta
    out["src_flag"] = flag
    out["n_cells_time"] = t.n_cells.values
    return out

def run(months, grid_path=GRID_FILE):
    grid = pd.read_csv(grid_path, dtype={"grid_cd": str, "adm_cd8": str}, storage_options=storage_options(grid_path)) \
        if not grid_path.endswith(".pkl") else pd.read_pickle(grid_path)
    gt = to_grid100(load_skt("time"), T_SRC, grid)
    gw = to_grid100(load_skt("wkdy"), W_SRC, grid)
    ga = to_grid100(load_skt("age"), A_SRC, grid)
    for p in months:
        anc = build_anchor(p, gt, gw, ga)
        write_parquet(anc, f"{ANCHOR_DIR}/period={p}.parquet")
        fb = anc.src_flag.value_counts().to_dict()
        print(f"[anchor] {p}: 격자 {len(anc):,} | t_h 합 {anc.t_h.sum():,.0f} | k_wkdy 중앙값 {anc.k_wkdy.median():.4f} | k_age 중앙값 {anc.k_age.median():.4f} | fallback {fb}")
