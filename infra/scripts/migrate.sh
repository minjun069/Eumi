#!/usr/bin/env bash
# ==========================================================================
# 운영 DB를 띄우고 → 백업한 뒤 → Flyway로 db/migration의 새 파일만 적용한다.
#   처음 실행이면 postgres가 빈 볼륨에 계정 4개와 eumi DB를 만든다 (postgres-init/).
#   이미 적용된 파일은 Flyway가 건너뛰므로 여러 번 실행해도 안전하다.
#   Flyway가 실패하면 여기서 멈춘다 → Jenkins는 Deploy 단계로 가지 않고, 기존 서비스가 그대로 돈다.
#
# 사용법 (jenkins 계정으로):  sudo -u jenkins /srv/eumi/scripts/migrate.sh
# Jenkins Migrate 단계도 같은 파일을 실행한다.
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)

if ! docker volume inspect eumi-pgdata >/dev/null 2>&1; then
  echo "[migrate] DB 볼륨 eumi-pgdata가 없습니다. 처음이라면 04 문서 4번(docker volume create eumi-pgdata)부터 합니다." >&2
  echo "          처음이 아닌데 이 메시지가 나오면 멈추고 백업부터 확인하세요 (06 문서 런북)." >&2
  exit 1
fi

echo "[migrate] postgres · mailpit 기동 (healthy까지 최대 3분 대기)"
"${COMPOSE[@]}" up -d --wait --wait-timeout 180 postgres mailpit

echo "[migrate] 배포 전 백업"
"$APP_DIR/scripts/backup.sh" deploy

echo "[migrate] Flyway 적용"
"${COMPOSE[@]}" run --rm -T flyway migrate </dev/null

echo "[migrate] 적용 결과"
"${COMPOSE[@]}" run --rm -T flyway info </dev/null | tail -n 20

echo "[migrate] 완료"
