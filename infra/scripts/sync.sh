#!/usr/bin/env bash
# ==========================================================================
# 저장소(받아 둔 폴더)의 운영 파일을 서버 운영 폴더(/srv/eumi)로 복사한다.
#   복사하는 것: compose 파일, 스크립트, db/(migration · roles · seed), postgres-init/
#   건드리지 않는 것: .env.config(비밀값), .env.tags(배포 태그), backups/, Nginx 설정
#
# 사용법 (jenkins 계정으로):
#   sudo -u jenkins bash <저장소>/infra/scripts/sync.sh <저장소 루트>     ← 사람이 처음 한 번
#   bash infra/scripts/sync.sh "$WORKSPACE"                                ← Jenkins Sync 단계
# ==========================================================================
set -euo pipefail

SRC="${1:?사용법: sync.sh <저장소 루트 폴더>}"
APP_DIR="${APP_DIR:-/srv/eumi}"
SRC="$(cd "$SRC" && pwd)"

for f in infra/deploy/docker-compose.prod.yml infra/postgres-init/01-eumi-roles.sh db/roles/eumi_db_roles.sql; do
  [ -f "$SRC/$f" ] || { echo "[sync] 저장소에 $f 가 없습니다: $SRC" >&2; exit 1; }
done
[ -d "$APP_DIR" ] || { echo "[sync] $APP_DIR 가 없습니다 (04 문서 2번)" >&2; exit 1; }
[ -f "$APP_DIR/.env.config" ] || { echo "[sync] $APP_DIR/.env.config 가 없습니다 (04 문서 3번)" >&2; exit 1; }

# 설정 · SQL은 컨테이너(postgres, flyway 사용자)가 읽어야 하므로 읽기 권한을 열어 둔다.
# 비밀값 · 백업만 jenkins 전용으로 닫는다.
umask 022

install -m 644 "$SRC/infra/deploy/docker-compose.prod.yml" "$APP_DIR/docker-compose.prod.yml"

mkdir -p "$APP_DIR/scripts"
install -m 755 "$SRC"/infra/scripts/*.sh "$APP_DIR/scripts/"
sed -i 's/\r$//' "$APP_DIR"/scripts/*.sh          # Windows 줄바꿈(CRLF)이 섞여 들어와도 실행되게

mkdir -p "$APP_DIR/postgres-init"
install -m 755 "$SRC/infra/postgres-init/01-eumi-roles.sh" "$APP_DIR/postgres-init/01-eumi-roles.sh"
sed -i 's/\r$//' "$APP_DIR/postgres-init/01-eumi-roles.sh"

# db/는 통째로 바꾼다 (저장소에서 지운 파일이 서버에 남지 않게). 새 폴더를 다 만든 뒤 바꿔치기한다.
rm -rf "$APP_DIR/db.new"
mkdir -p "$APP_DIR/db.new"
cp -r "$SRC/db/migration" "$SRC/db/roles" "$APP_DIR/db.new/"
if [ -d "$SRC/db/seed" ]; then cp -r "$SRC/db/seed" "$APP_DIR/db.new/"; else mkdir -p "$APP_DIR/db.new/seed"; fi
chmod -R u=rwX,go=rX "$APP_DIR/db.new"
rm -rf "$APP_DIR/db.old"
[ -d "$APP_DIR/db" ] && mv "$APP_DIR/db" "$APP_DIR/db.old"
mv "$APP_DIR/db.new" "$APP_DIR/db"
rm -rf "$APP_DIR/db.old"

# 처음 한 번: 배포 태그 파일 (deploy.sh가 갱신한다)
if [ ! -f "$APP_DIR/.env.tags" ]; then
  printf 'BACKEND_TAG=none\nWEB_TAG=none\n' > "$APP_DIR/.env.tags"
fi

mkdir -p "$APP_DIR/backups/deploy" "$APP_DIR/backups/daily" "$APP_DIR/backups/manual"
chmod 600 "$APP_DIR/.env.config" "$APP_DIR/.env.tags"
chmod 700 "$APP_DIR/backups" "$APP_DIR"/backups/*/

echo "[sync] $SRC → $APP_DIR 복사 완료"
