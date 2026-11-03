"""2차 M3 행동 지표 공통 — flow_detail 일평균 읽기, 산식, 저장 변환. batch_bh_grid_indicators.py(M3-3) · batch_bh_region_indicators.py(M3-2) 가 쓴다.

산식 (정의서 4.7·4.8, 완성본 컬럼정의)
  activity_daily = Σ 시간대 일평균(24)      h12 = 평균(18~21시)/평균(9~17시)    h13 = 평균(7,8,9,17,18,19시)/평균(10~16시)
  h14·h15·h19 = 비중 엔트로피(자연로그)      h18 = 남60+/(남60++여60+)           h20 = (유동60+/유동전체)/(주민60+/주민전체)
  h21 = (유동 남50++남60+)/유동전체 ÷ 주민 남50+/주민전체                          h26·h29 = 전월 대비 변화율 격차(%p)
  h30·h31 = 전월 대비 JS 거리(밑 2)         분모 0 또는 전월 없음 → NULL (0 금지)
"""
import warnings
from decimal import Decimal

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")  # psycopg 연결로 read_sql 을 써도 동작한다

H = [f"{i:02d}" for i in range(24)]
W = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
A = ["M_10", "M_20", "M_30", "M_40", "M_50", "M_60P", "F_10", "F_20", "F_30", "F_40", "F_50", "F_60P"]
GRID_COLS = ["activity_daily", "h12_evening_day_ratio", "h13_commute_ratio", "h14_hour_entropy", "h15_weekday_entropy",
             "h18_senior_male_share", "h19_age_entropy", "h26_weekend_weekday_change_gap", "h29_senior_gender_change_gap",
             "h30_hour_profile_distance", "h31_weekday_profile_distance"]
REGION_COLS = GRID_COLS[:7] + ["h20_senior_representation", "h21_male50plus_representation"] + GRID_COLS[7:]


def prev_month(m: str) -> str:
    y, mm = (int(x) for x in m.split("-"))
    return f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"


def load_means(conn, m: str):
    """격자 × (hour 24 + weekday 7 + sex_age 12) 일평균. 그 달 자료가 없으면 None."""
    df = pd.read_sql("SELECT grid_cd, dim_type, dim_value, flow_sum / day_count AS mean FROM analysis.flow_detail "
                     "WHERE period_start = %s AND day_count > 0", conn, params=(f"{m}-01",))
    if df.empty:
        return None
    return df.pivot(index="grid_cd", columns="dim_value", values="mean").astype(float).reindex(columns=H + W + A)


def entropy(x):
    tot = x.sum(axis=1, keepdims=True)
    p = np.divide(x, tot, out=np.zeros_like(x), where=tot > 0)
    e = -(np.where(p > 0, p * np.log(np.where(p > 0, p, 1)), 0)).sum(axis=1)
    return np.where(tot[:, 0] > 0, e, np.nan)


def js_distance(x, y):
    def shares(v):
        tot = v.sum(axis=1, keepdims=True)
        return np.divide(v, tot, out=np.full_like(v, np.nan), where=tot > 0)
    p, q = shares(x), shares(y)
    mm = (p + q) / 2

    def kl(a, b):
        return (np.where(a > 0, a * np.log2(np.where(a > 0, a, 1) / np.where(b > 0, b, 1)), 0)).sum(axis=1)
    return np.sqrt(np.clip((kl(p, mm) + kl(q, mm)) / 2, 0, None))


def ratio(num, den):
    return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def indicators(cur, prev):
    """일평균 표(격자 또는 동 단위) → 공통 지표 10개 + activity_daily. prev 가 없으면 변화 지표(h26·h29·h30·h31)는 NULL."""
    h, w, a = cur[H].to_numpy(), cur[W].to_numpy(), cur[A].to_numpy()
    out = pd.DataFrame(index=cur.index)
    out["activity_daily"] = h.sum(axis=1)
    out["h12_evening_day_ratio"] = ratio(h[:, 18:22].mean(axis=1), h[:, 9:18].mean(axis=1))
    out["h13_commute_ratio"] = ratio(h[:, [7, 8, 9, 17, 18, 19]].mean(axis=1), h[:, 10:17].mean(axis=1))
    out["h14_hour_entropy"] = entropy(h)
    out["h15_weekday_entropy"] = entropy(w)
    out["h18_senior_male_share"] = ratio(a[:, 5], a[:, 5] + a[:, 11])
    out["h19_age_entropy"] = entropy(a[:, :6] + a[:, 6:])
    for c in GRID_COLS[7:]:
        out[c] = np.nan
    if prev is not None:
        pv = prev.reindex(cur.index)
        ph, pw, pa = pv[H].to_numpy(), pv[W].to_numpy(), pv[A].to_numpy()
        wk_t, wd_t = w[:, 5:7].mean(axis=1), w[:, :5].mean(axis=1)
        wk_p, wd_p = pw[:, 5:7].mean(axis=1), pw[:, :5].mean(axis=1)
        out["h26_weekend_weekday_change_gap"] = 100 * ((ratio(wk_t, wk_p) - 1) - (ratio(wd_t, wd_p) - 1))
        out["h29_senior_gender_change_gap"] = 100 * ((ratio(a[:, 5], pa[:, 5]) - 1) - (ratio(a[:, 11], pa[:, 11]) - 1))
        out["h30_hour_profile_distance"] = js_distance(h, ph)
        out["h31_weekday_profile_distance"] = js_distance(w, pw)
    return out


# 저장 가능 범위: H 지표 DECIMAL(10,6) → |값| < 10^4 (유동이 극히 적은 격자의 변화율 %p 가 넘길 수 있다 → 저장 불가라 NULL),
#                activity_daily 는 격자 DECIMAL(12,2) · 읍면동 DECIMAL(14,2)
def limit_of(col):
    return 1e10 if col == "activity_daily" else 1e4


def to_dec(v, limit=1e4):
    return None if pd.isna(v) or abs(v) >= limit else Decimal(f"{v:.6f}")


def report_overflow(name, df):
    over = {c: int((df[c].abs() >= limit_of(c)).sum()) for c in df.columns if (df[c].abs() >= limit_of(c)).any()}
    if over:
        print(f"[bh]   {name}: 저장 범위를 넘어 NULL 처리한 값 {over}", flush=True)


def max_diff_text(new: pd.DataFrame, old: pd.DataFrame, cols) -> str:
    """컬럼마다 기존 값과의 최대 절대 차이. 기존이 모두 NULL 이면 '기존NULL'."""
    parts = []
    for c in cols:
        if old[c].notna().any():
            d = np.abs(new[c].to_numpy(float) - old[c].to_numpy(float))
            parts.append(f"{c.split('_')[0]}={float(np.nanmax(d)) if np.isfinite(d).any() else float('nan'):.1e}")
        else:
            parts.append(f"{c.split('_')[0]}=기존NULL")
    return ", ".join(parts)
