"""5단계: 시간 단위 파일을 월평균으로 묶어 anchor와 대조."""
import numpy as np, pandas as pd, time
from config import ANCHOR_DIR, HOURLY_DIR, CHECK_DIR, AGE_COLS, CHECK_ATOL, CHECK_RTOL
from calendar_util import month_days
from io_util import read_parquet, write_csv, list_files
from anchor import H_COLS, W_COLS, A_COLS

def validate_month(period: str):
    t0 = time.time()
    anc = read_parquet(f"{ANCHOR_DIR}/period={period}.parquet").set_index("grid_cd")
    days, wd, cnt = month_days(period); D = len(days)
    files = list_files(f"{HOURLY_DIR}/period={period}")
    assert len(files) == D, f"{period}: 파일 {len(files)}개, 날짜 {D}일"
    G = len(anc); idx = {g: i for i, g in enumerate(anc.index)}
    hour_sum = np.zeros((G, 24)); wk_sum = np.zeros((G, 7)); age_sum = np.zeros((G, 12))
    for f in files:
        df = read_parquet(f)
        gi = df.grid_cd.map(idx).to_numpy(); ts = pd.DatetimeIndex(df.ts).tz_convert("Asia/Seoul")
        v = df[AGE_COLS].to_numpy(float); tot = v.sum(axis=1)
        np.add.at(hour_sum, (gi, ts.hour.to_numpy()), tot)
        np.add.at(wk_sum, (gi, ts.weekday.to_numpy()), tot)
        np.add.at(age_sum, gi, v)
    h_mean = hour_sum / D
    w_mean = wk_sum / cnt[None, :]
    a_mean = age_sum / D
    H = anc[H_COLS].to_numpy(float); W = anc[W_COLS].to_numpy(float) * anc.k_wkdy.to_numpy()[:, None]
    A = anc[A_COLS].to_numpy(float) * anc.k_age.to_numpy()[:, None]
    def errs(got, want):
        d = np.abs(got - want); big = want >= 0.01
        rel = np.where(big, d / np.maximum(want, 1e-12), 0).max(axis=1)
        ab = np.where(~big, d, 0).max(axis=1)
        return d.max(axis=1), rel, ab
    eh, rh, ah = errs(h_mean, H); ew, rw, aw = errs(w_mean, W); ea, ra, aa = errs(a_mean, A)
    rep = pd.DataFrame({"grid_cd": anc.index, "t_h": anc.t_h.values,
                        "err_hour": eh, "err_wkdy": ew, "err_age": ea,
                        "rel_hour": rh, "rel_wkdy": rw, "rel_age": ra})
    rep["ok"] = (np.maximum.reduce([rh, rw, ra]) <= CHECK_RTOL) & (np.maximum.reduce([ah, aw, aa]) <= CHECK_ATOL)
    write_csv(rep, f"{CHECK_DIR}/period={period}.csv")
    # 대표 지표 대조 (원본 월평균 vs 생성값 월평균)
    def h12(h): return h[:, 18:22].mean(axis=1) / np.maximum(h[:, 9:18].mean(axis=1), 1e-12)
    def ent(p):
        p = p / np.maximum(p.sum(axis=1, keepdims=True), 1e-12); q = np.where(p > 0, p, 1)
        return -(p * np.log(q)).sum(axis=1)
    big = anc.t_h.values >= 1
    d12 = np.abs(h12(h_mean) - h12(H))[big].max(); d14 = np.abs(ent(h_mean) - ent(H))[big].max()
    d15 = np.abs(ent(w_mean) - ent(W))[big].max()
    m60 = a_mean[:, 5] / np.maximum(a_mean[:, 5] + a_mean[:, 11], 1e-12); m60o = A[:, 5] / np.maximum(A[:, 5] + A[:, 11], 1e-12)
    d18 = np.abs(m60 - m60o)[big].max()
    print(f"[validate] {period}: 격자 {G:,} | 최대 절대오차 시간대 {rep.err_hour.max():.1e} 요일 {rep.err_wkdy.max():.1e} 성연령 {rep.err_age.max():.1e} | 최대 상대오차 {max(rh.max(), rw.max(), ra.max()):.1e} (허용 {CHECK_RTOL}) | 통과 {rep.ok.mean():.2%} | 지표 차이(t_h≥1) H12 {d12:.1e} H14 {d14:.1e} H15 {d15:.1e} H18 {d18:.1e} | {time.time()-t0:.0f}s")
    return rep

def run(months):
    for p in months: validate_month(p)
