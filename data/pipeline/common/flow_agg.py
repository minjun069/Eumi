"""2차 5.2 공통 — 시간 단위 유동(격자 × 시각 × 성·연령 12칸) → flow_detail 증분 행.

규칙 (synth_flow README "Spark 스트리밍 집계 규칙")
  hour    : dim_value '00'~'23',  flow_sum = 12칸 합,  day_count = 반영 날짜 수
  weekday : dim_value MON~SUN,    flow_sum = 12칸 합,  day_count = 그 요일의 날짜 수
  sex_age : dim_value M_10~F_60P, flow_sum = 칸 값,    day_count = 반영 날짜 수
일평균 = flow_sum / day_count. 입력은 "날짜 단위로 완결된" 행이어야 day_count 가 정확하다
(배치는 한 달 전체, 스트리밍은 하루 윈도가 닫힌 뒤 넘어온 행).
"""
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

AGE_COLS = ["m_10", "m_20", "m_30", "m_40", "m_50", "m_60p", "f_10", "f_20", "f_30", "f_40", "f_50", "f_60p"]
SEX_AGE_VALUE = {c: c.upper() for c in AGE_COLS}           # m_60p → M_60P
WEEKDAY_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]  # Spark dayofweek: 1=일 … 7=토
TZ = "Asia/Seoul"


def with_day_fields(df: DataFrame, ts_col: str = "ts") -> DataFrame:
    """ts(timestamp) → d(date), hour('00'~'23'), weekday(MON~SUN), period_start(월 1일), total(12칸 합).
    날짜·시각은 Spark 세션 시간대로 계산하므로 spark.sql.session.timeZone = Asia/Seoul 이어야 한다 (spark-defaults.conf)."""
    local = F.col(ts_col)
    wd = F.array(*[F.lit(n) for n in WEEKDAY_NAMES])
    return (df.withColumn("d", F.to_date(local))
              .withColumn("hour", F.lpad(F.hour(local).cast("string"), 2, "0"))
              .withColumn("weekday", F.element_at(wd, F.dayofweek(local)))
              .withColumn("period_start", F.trunc(local, "month").cast("date"))
              .withColumn("total", sum(F.col(c) for c in AGE_COLS)))


def daily_to_detail(df: DataFrame) -> DataFrame:
    """with_day_fields 를 거친 행 → (period_start, grid_cd, dim_type, dim_value, flow_sum, day_count)."""
    keys = ["period_start", "grid_cd"]
    hour = (df.groupBy(*keys, F.col("hour").alias("dim_value"))
              .agg(F.sum("total").alias("flow_sum"), F.countDistinct("d").alias("day_count"))
              .withColumn("dim_type", F.lit("hour")))
    weekday = (df.groupBy(*keys, F.col("weekday").alias("dim_value"))
                 .agg(F.sum("total").alias("flow_sum"), F.countDistinct("d").alias("day_count"))
                 .withColumn("dim_type", F.lit("weekday")))
    stack_expr = "stack({n}, {pairs}) as (dim_value, v)".format(
        n=len(AGE_COLS), pairs=", ".join(f"'{SEX_AGE_VALUE[c]}', {c}" for c in AGE_COLS))
    sex_age = (df.select(*keys, "d", F.expr(stack_expr))
                 .groupBy(*keys, "dim_value")
                 .agg(F.sum("v").alias("flow_sum"), F.countDistinct("d").alias("day_count"))
                 .withColumn("dim_type", F.lit("sex_age")))
    cols = ["period_start", "grid_cd", "dim_type", "dim_value", "flow_sum", "day_count"]
    return hour.select(cols).unionByName(weekday.select(cols)).unionByName(sex_age.select(cols))
