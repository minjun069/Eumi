"""3~4단계: anchor → 시간 단위 가상 유동 (격자 × 시각 × 성연령 12).

조건(모두 월평균 기준으로 정확히 일치):
  시간대별 날짜 평균 = h_**,  요일별 날짜 평균 = w_* × k_wkdy,  성연령별 날짜 평균 = a_* × k_age
"""
import numpy as np, pandas as pd, time
from config import (ANCHOR_DIR, HOURLY_DIR, AGE_COLS, GEN_VERSION, BASE_SEED, HOLIDAY_MODE, HOLIDAYS,
                    DAY_NOISE_SD, DAY_NOISE_CLIP, HOUR_NOISE_SD, HOUR_NOISE_CLIP, hour_age_weight,
                    IPF_TOL, IPF_MAX_ITER, VALUE_DECIMALS, VALUE_DTYPE)
from calendar_util import month_days
from io_util import read_parquet, write_parquet
from anchor import H_COLS, W_COLS, A_COLS

def _ipf2(Y, row_t, col_t, tol=IPF_TOL, max_iter=IPF_MAX_ITER):
    """Y: (G, R, C). 행 합 → row_t (G,R), 열 합 → col_t (G,C). 양쪽 합이 같아야 수렴."""
    for it in range(max_iter):
        rs = Y.sum(axis=2); f = np.divide(row_t, rs, out=np.ones_like(rs), where=rs > 0); Y *= f[:, :, None]
        cs = Y.sum(axis=1); g = np.divide(col_t, cs, out=np.ones_like(cs), where=cs > 0); Y *= g[:, None, :]
        err = max(np.abs(f - 1).max(), np.abs(g - 1).max())
        if err < tol: break
    return Y, it + 1, err

def day_totals(W, wd, cnt, days, rng):
    """(G,7) 요일 일평균 → (G,D) 날짜별 총량. 요일별 날짜 평균은 W와 정확히 같음."""
    G, D = W.shape[0], len(days)
    base = W[:, wd]                                           # (G,D)
    if HOLIDAY_MODE:
        hol = np.array([d.isoformat() in HOLIDAYS for d in days])
        if hol.any(): base = base.copy(); base[:, hol] = W[:, 6][:, None]   # 일요일 총량으로 초기화
    eps = np.clip(rng.normal(0, DAY_NOISE_SD, (G, D)), -DAY_NOISE_CLIP, DAY_NOISE_CLIP)
    R = base * (1 + eps)
    for w in range(7):
        m = wd == w
        if not m.any(): continue
        mean = R[:, m].mean(axis=1)
        f = np.divide(W[:, w], mean, out=np.zeros_like(mean), where=mean > 0)
        R[:, m] *= f[:, None]
    return R

def generate_month(period: str, chunk=1500, verbose=True):
    t0 = time.time()
    anc = read_parquet(f"{ANCHOR_DIR}/period={period}.parquet")
    days, wd, cnt = month_days(period)
    D, G = len(days), len(anc)
    y, m = map(int, period.split("-"))
    rng = np.random.default_rng(BASE_SEED + y * 100 + m)
    H = anc[H_COLS].to_numpy(float)                       # (G,24)
    W = anc[W_COLS].to_numpy(float) * anc.k_wkdy.to_numpy()[:, None]
    A = anc[A_COLS].to_numpy(float) * anc.k_age.to_numpy()[:, None]
    t_h = H.sum(axis=1)
    # ---- 3단계: 날짜 × 시간
    R = day_totals(W, wd, cnt, days, rng)                 # (G,D)
    shape = H / t_h[:, None]
    eta = np.clip(rng.normal(0, HOUR_NOISE_SD, (G, D, 24)), -HOUR_NOISE_CLIP, HOUR_NOISE_CLIP)
    Y = R[:, :, None] * shape[:, None, :] * (1 + eta)
    Y, n1, e1 = _ipf2(Y, R, H * D)
    # ---- 4단계: 성연령 12 쪼개기 (격자 chunk 단위)
    HW = hour_age_weight()                                 # (24,12)
    hour_of_slot = np.tile(np.arange(24), D)               # (744,)
    out = np.empty((G, D * 24, 12), dtype=np.float64 if VALUE_DTYPE == "float64" else np.float32)
    n2max, e2max = 0, 0.0
    for s in range(0, G, chunk):
        e = min(s + chunk, G)
        Yc = Y[s:e].reshape(e - s, D * 24)                 # (g,744)
        share = A[s:e] / np.maximum(A[s:e].sum(axis=1, keepdims=True), 1e-12)
        P0 = share[:, None, :] * HW[hour_of_slot][None, :, :]
        P0 /= P0.sum(axis=2, keepdims=True)
        X = Yc[:, :, None] * P0
        X, n2, e2 = _ipf2(X, Yc, A[s:e] * D)
        out[s:e] = X if VALUE_DTYPE == "float64" else (np.round(X, VALUE_DECIMALS) if VALUE_DECIMALS else X).astype(np.float32)
        n2max, e2max = max(n2max, n2), max(e2max, e2)
    # ---- 저장: 하루 1파일
    grid = anc.grid_cd.to_numpy()
    for di, d in enumerate(days):
        block = out[:, di * 24:(di + 1) * 24, :]           # (G,24,12)
        ts = pd.DatetimeIndex([pd.Timestamp(d) + pd.Timedelta(hours=h) for h in range(24)], tz="Asia/Seoul")
        df = pd.DataFrame(block.reshape(G * 24, 12), columns=AGE_COLS)
        df.insert(0, "grid_cd", np.repeat(grid, 24))
        df.insert(0, "ts", np.tile(ts.to_numpy(), G))
        df["gen_version"] = GEN_VERSION
        write_parquet(df, f"{HOURLY_DIR}/period={period}/day={d.day:02d}.parquet")
    if verbose:
        print(f"[generate] {period}: 격자 {G:,} × {D}일 × 24h = {G*D*24:,}행 | IPF1 {n1}회(err {e1:.1e}) IPF2 최대 {n2max}회(err {e2max:.1e}) | {time.time()-t0:.0f}s")

def run(months, **kw):
    for p in months: generate_month(p, **kw)
