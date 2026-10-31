#!/usr/bin/env bash
# ==========================================================================
# 운영 compose 명령을 짧게 쓰기 위한 도우미. 상태 보기용이다.
#
# 사용법 (jenkins 계정으로):
#   sudo -u jenkins /srv/eumi/scripts/dc.sh ps
#   sudo -u jenkins /srv/eumi/scripts/dc.sh logs --tail=100 backend
#   sudo -u jenkins /srv/eumi/scripts/dc.sh exec postgres psql -U postgres -d eumi
# 줄여 쓰기 (ubuntu의 ~/.bashrc에 한 줄):  alias eumi='sudo -u jenkins /srv/eumi/scripts/dc.sh'
#
# 금지: dc.sh down -v (external 볼륨이라 DB는 지워지지 않지만 업로드 볼륨이 지워진다) — 이 도우미가 막는다
#       서비스 교체는 up 대신 deploy.sh로 한다 (헬스체크 · 되돌림 · 기록이 빠진다)
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# down · rm 에 -v(--volumes)를 붙이면 막는다 (exec ... psql -v 같은 다른 명령의 -v는 통과)
SUB=""
for a in "$@"; do
  case "$a" in -*) ;; *) SUB="$a"; break ;; esac
done
if [ "$SUB" = "down" ] || [ "$SUB" = "rm" ]; then
  for a in "$@"; do
    if [ "$a" = "-v" ] || [ "$a" = "--volumes" ]; then
      echo "[dc] $SUB -v 는 이 도우미로 실행하지 않습니다 (06 문서 런북 참고)" >&2
      exit 1
    fi
  done
fi

exec docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags "$@"
