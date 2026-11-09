#!/bin/sh
# 로컬 DB를 처음 만들 때 한 번만 실행된다 (pgdata 볼륨이 비어 있을 때).
# db/roles/eumi_db_roles.sql을 슈퍼유저로 실행해 계정 4개와 eumi DB를 만든다.
# .sql은 변수를 받지 못하므로 이 .sh가 비밀번호를 넘긴다.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$EUMI_OWNER_PASSWORD" \
  -v app_pw="$EUMI_APP_PASSWORD" \
  -v pipeline_pw="$EUMI_PIPELINE_PASSWORD" \
  -v ai_pw="$EUMI_AI_PASSWORD" \
  -v monitor_pw="${EUMI_MONITOR_PASSWORD:-monitor_local}" \
  -f /eumi/roles/eumi_db_roles.sql
