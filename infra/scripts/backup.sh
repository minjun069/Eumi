#!/usr/bin/env bash
# ==========================================================================
# 운영 DB(eumi)를 통째로 백업한다 → /srv/eumi/backups/<종류>/eumi-<날짜-시각>.sql.gz
#
# 사용법 (jenkins 계정으로):  sudo -u jenkins /srv/eumi/scripts/backup.sh <종류>
#   deploy  배포 직전 (migrate.sh가 부른다)      최근 10개 보관
#   daily   매일 새벽 (/etc/cron.d/eumi-backup)  최근 7개 보관
#   manual  사람이 위험한 작업 전에              지우지 않음
#
# 복원이 되는지 확인: scripts/restore-test.sh (운영 DB는 건드리지 않는다)
# 백업 파일에는 개인정보가 들어갈 수 있다. 서버 밖 사본은 인프라 담당만 보관하고 공유하지 않는다.
# ==========================================================================
set -euo pipefail

KIND="${1:-manual}"
case "$KIND" in
  deploy) KEEP=10 ;;
  daily)  KEEP=7 ;;
  manual) KEEP=0 ;;
  *) echo "[backup] 종류는 deploy | daily | manual 중 하나입니다: $KIND" >&2; exit 1 ;;
esac

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)

DIR="backups/$KIND"
mkdir -p "$DIR"
chmod 700 backups "$DIR"
umask 077

OUT="$DIR/eumi-$(date +%Y%m%d-%H%M%S).sql.gz"
TMP="$OUT.part"
trap 'rm -f "$TMP"' EXIT

# 컨테이너 안에서 슈퍼유저로 덤프한다 (컨테이너 내부 소켓 접속이라 비밀번호가 필요 없다).
# stdin을 /dev/null로 막는다: Jenkins · cron에서 exec가 입력을 기다리지 않게
"${COMPOSE[@]}" exec -T postgres pg_dump -U postgres -d eumi </dev/null | gzip > "$TMP"

# 빈 파일 · 깨진 파일을 백업으로 남기지 않는다
gzip -t "$TMP"
if [ "$(gunzip -c "$TMP" | head -c 100 | wc -c)" -lt 100 ]; then
  echo "[backup] 덤프 내용이 비어 있습니다 — 실패로 처리합니다" >&2
  exit 1
fi
mv "$TMP" "$OUT"
trap - EXIT

echo "[backup] $APP_DIR/$OUT ($(du -h "$OUT" | cut -f1))"

if [ "$KEEP" -gt 0 ]; then
  ls -1t "$DIR"/eumi-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f --
fi
