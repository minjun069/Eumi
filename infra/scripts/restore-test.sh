#!/usr/bin/env bash
# ==========================================================================
# 백업 파일이 실제로 복원되는지 시험한다. 운영 DB(eumi)는 건드리지 않는다.
#   임시 DB(eumi_restore_test)를 만들어 복원 → 운영 DB와 테이블 수 · 마이그레이션 기록 비교 → 임시 DB 삭제
#
# 사용법 (jenkins 계정으로):
#   sudo -u jenkins /srv/eumi/scripts/restore-test.sh              ← 가장 최근 백업
#   sudo -u jenkins /srv/eumi/scripts/restore-test.sh <백업 파일>
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)
TEST_DB=eumi_restore_test

FILE="${1:-$(ls -1t backups/*/eumi-*.sql.gz 2>/dev/null | head -1 || true)}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "[restore-test] 백업 파일이 없습니다" >&2; exit 1; }
echo "[restore-test] 대상: $FILE"

psql_su() { "${COMPOSE[@]}" exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -X -q "$@"; }
drop_test_db() { psql_su -d postgres -c "DROP DATABASE IF EXISTS $TEST_DB" </dev/null || true; }
trap drop_test_db EXIT

drop_test_db
psql_su -d postgres -c "CREATE DATABASE $TEST_DB OWNER eumi_owner" </dev/null

echo "[restore-test] 복원 중"
gunzip -c "$FILE" | psql_su -d "$TEST_DB" >/dev/null

SUMMARY_SQL="
SELECT 'tables=' || count(*) FROM information_schema.tables
 WHERE table_schema IN ('public','analysis') AND table_type = 'BASE TABLE'
UNION ALL
SELECT 'views=' || count(*) FROM information_schema.views WHERE table_schema IN ('public','analysis')
UNION ALL
SELECT 'migrations=' || count(*) || ' (last V' || coalesce(
         (SELECT version FROM public.flyway_schema_history
           WHERE success AND version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1), '-') || ')'
  FROM public.flyway_schema_history WHERE success;
"

echo "[restore-test] 비교 (백업 시점 이후 바뀐 내용이 있으면 다를 수 있다)"
echo "  운영 eumi       : $(psql_su -d eumi      -t -A -c "$SUMMARY_SQL" </dev/null | paste -sd' ')"
echo "  복원 $TEST_DB : $(psql_su -d "$TEST_DB" -t -A -c "$SUMMARY_SQL" </dev/null | paste -sd' ')"
echo "[restore-test] 성공 — 임시 DB는 지웁니다"
