"""Eumi 월 배치 DAG — data/README.md "월 배치 순서" 1~12단계 (seed 생성은 제외).

- 스케줄: 매월 5일 03:00 (Asia/Seoul). 기준월은 전월 (실거래 신고 기한 30일을 고려).
- 수동 실행(재처리): Airflow UI "Trigger DAG w/ config" 또는 CLI 에서 {"months": ["2025-12"]} (여러 달 가능). 비우면 스케줄과 같은 규칙.
- 첫 태스크 check_inputs 가 그 달 원본(SKT 월평균 · 주민등록)이 있는지 보고, 없으면 종료 코드 99 → 전체를 skip 한다
  (unpause 직후 Airflow 가 지난 스케줄 1건을 자동 실행하는데, 원본이 없는 달이면 API 호출 없이 건너뛰도록).
- 태스크는 pipeline 컨테이너 안에서 python3 / spark-submit 로 스크립트를 그대로 호출한다 (ops/run_month.py 와 같은 순서).
  실패한 단계만 UI 에서 Clear 하면 그 단계부터 다시 돈다. 모든 스크립트는 같은 달을 다시 돌려도 안전하다(그 달 삭제 후 적재 · UPSERT).
"""
from __future__ import annotations

import datetime as dt

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator

DATA_DIR = "/opt/eumi/data"
TZ = pendulum.timezone("Asia/Seoul")


def target_months(dag_run, data_interval_end) -> str:
    """--months 에 넣을 'YYYY-MM …'. 수동 실행 conf 의 months 가 있으면 그것, 없으면 실행 구간 끝의 전월."""
    conf = (dag_run.conf or {}) if dag_run else {}
    months = conf.get("months")
    if months:
        return " ".join(months)
    end = data_interval_end.in_timezone(TZ)
    prev = end.replace(day=1) - dt.timedelta(days=1)
    return prev.strftime("%Y-%m")


MONTHS = "{{ target_months(dag_run, data_interval_end) }}"

# (task_id, 실행기, 스크립트) — 모듈 폴더 순서
STEPS = {
    "collect_apt_trade":   ("python3",      "m1_collect/collect_apt_trade.py"),
    "geocode_apt":         ("python3",      "m1_collect/geocode_apt.py"),
    "synth_anchor":        ("python3",      "m1_collect/run_synth.py anchor"),
    "synth_generate":      ("python3",      "m1_collect/run_synth.py generate"),
    "synth_validate":      ("python3",      "m1_collect/run_synth.py validate"),
    "flow_detail":         ("spark-submit", "m2_process/batch_flow_detail.py"),
    "verify_flow_detail":  ("spark-submit", "m2_process/verify_flow_detail.py"),
    "bg_detail":           ("python3",      "m2_process/batch_bg_detail.py"),
    "re_apt_trade":        ("python3",      "m2_process/batch_re_apt_trade.py"),
    "bg_indicators":       ("python3",      "m3_indicator/batch_bg_indicators.py"),
    "bh_grid_indicators":  ("python3",      "m3_indicator/batch_bh_grid_indicators.py"),
    "bh_region_indicators": ("python3",     "m3_indicator/batch_bh_region_indicators.py"),
    "region_result":       ("python3",      "m4_analysis/batch_region_result.py"),
    "grid_anomaly":        ("python3",      "m4_analysis/batch_grid_anomaly.py"),
}

with DAG(
    dag_id="eumi_monthly",
    description="Eumi 데이터 파이프라인 월 배치 (수집 → 정제 → 지표 → 분석)",
    schedule="0 3 5 * *",
    start_date=pendulum.datetime(2025, 8, 1, tz=TZ),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": dt.timedelta(minutes=5), "execution_timeout": dt.timedelta(hours=2)},
    user_defined_macros={"target_months": target_months},
    tags=["eumi", "data"],
    doc_md=__doc__,
) as dag:
    check_inputs = BashOperator(
        task_id="check_inputs",
        bash_command=f"python3 pipeline/ops/check_month_inputs.py --months {MONTHS}",
        cwd=DATA_DIR,
        append_env=True,
        skip_on_exit_code=99,  # 원본 없음 → 이 달은 건너뜀 (아래 태스크 전부 skipped)
    )
    t = {}
    for task_id, (runner, script) in STEPS.items():
        t[task_id] = BashOperator(
            task_id=task_id,
            bash_command=f"{runner} pipeline/{script} --months {MONTHS}",
            cwd=DATA_DIR,
            append_env=True,
        )

    check_inputs >> [t["collect_apt_trade"], t["synth_anchor"], t["bg_detail"]]
    # M1 수집 → M2 실거래가
    t["collect_apt_trade"] >> t["geocode_apt"] >> t["re_apt_trade"]
    # M1 가상 유동 → M2 유동 상세 → M3 행동 지표
    t["synth_anchor"] >> t["synth_generate"] >> t["synth_validate"] >> t["flow_detail"] >> t["verify_flow_detail"]
    t["verify_flow_detail"] >> [t["bh_grid_indicators"], t["bh_region_indicators"]]
    # M2 배경 상세 → M3 배경 지표 (읍면동 행동 지표의 주민 연령 분모도 배경 상세)
    t["bg_detail"] >> [t["bg_indicators"], t["bh_region_indicators"]]
    # M4
    [t["bg_indicators"], t["bh_region_indicators"]] >> t["region_result"]
    t["bh_grid_indicators"] >> t["grid_anomaly"]
