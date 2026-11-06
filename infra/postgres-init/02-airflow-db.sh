#!/bin/sh
# Airflow 메타 DB (pgdata 볼륨을 처음 만들 때만 실행). 이미 있는 DB 에는 infra/README.md 의 수동 명령으로 같은 것을 만든다.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE airflow LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
CREATE DATABASE airflow OWNER airflow;
SQL
