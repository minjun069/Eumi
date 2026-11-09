"""[운영 | pipeline-init] Grafana 계정(eumi_monitor)에 Airflow 메타 DB 의 실행 이력 테이블 읽기 권한을 준다.

테이블은 `airflow db migrate` 뒤에 생기므로 compose 의 pipeline-init 이 migrate 다음에 이 스크립트를 부른다 (몇 번 실행해도 같다).
읽는 테이블만 허용한다 (dag · dag_run · task_instance · job). 접속 정보 · 변수 테이블은 주지 않는다.
eumi_monitor 계정이 없는 DB(모니터링을 안 켠 환경)에서는 아무것도 하지 않는다.
"""
import os
import sys

import psycopg

TABLES = ("dag", "dag_run", "task_instance", "job")


def main() -> None:
    dsn = os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"].replace("postgresql+psycopg2://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'eumi_monitor'").fetchone() is None:
            print("grant_monitor: eumi_monitor 계정 없음 → 건너뜀")
            return
        conn.execute("GRANT USAGE ON SCHEMA public TO eumi_monitor")
        conn.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO eumi_monitor")
    print(f"grant_monitor: eumi_monitor 에 SELECT 부여 ({', '.join(TABLES)})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 권한 부여 실패가 Airflow 초기화를 막지 않도록 메시지만 남긴다
        print(f"grant_monitor: 실패 ({e})", file=sys.stderr)
