import calendar, datetime as dt
import numpy as np

def month_days(period: str):
    """period 'YYYY-MM' → (날짜 리스트, 요일 인덱스 배열(월=0..일=6), 요일별 날짜 수(7,))"""
    y, m = map(int, period.split("-"))
    nd = calendar.monthrange(y, m)[1]
    days = [dt.date(y, m, d) for d in range(1, nd + 1)]
    wd = np.array([d.weekday() for d in days])
    cnt = np.bincount(wd, minlength=7).astype(float)
    return days, wd, cnt
