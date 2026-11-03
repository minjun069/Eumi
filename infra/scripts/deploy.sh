#!/usr/bin/env bash
# ==========================================================================
# 서비스 하나를 새 이미지 태그로 바꾸고 헬스체크를 기다린다. 실패하면 이전 태그로 되돌린다.
#
# 사용법 (jenkins 계정으로):  sudo -u jenkins /srv/eumi/scripts/deploy.sh <backend|web> <태그>
#   롤백도 같은 명령에 이전 태그를 주면 된다.
#   보관 중인 태그 보기:  docker images eumi-backend
#   배포 기록:            /srv/eumi/deploy-history.log
#
# 교체하는 몇 초~1분 동안은 해당 서비스 응답이 끊길 수 있다 (무중단 배포는 쓰지 않는다).
# ai · pipeline은 compose에 서비스를 추가할 때 아래 case에도 한 줄씩 추가한다.
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)

USAGE="사용법: deploy.sh <backend|web> <태그>"
SVC="${1:?$USAGE}"
TAG="${2:?$USAGE}"

case "$SVC" in
  backend) KEY=BACKEND_TAG ;;
  web)     KEY=WEB_TAG ;;
  *) echo "[deploy] 알 수 없는 서비스: $SVC ($USAGE)" >&2; exit 1 ;;
esac

if ! docker image inspect "eumi-$SVC:$TAG" >/dev/null 2>&1; then
  echo "[deploy] 이미지가 없습니다: eumi-$SVC:$TAG — 보관 중인 태그:" >&2
  docker images "eumi-$SVC" --format '  {{.Tag}}  ({{.CreatedSince}})' >&2
  exit 1
fi

PREV="$(grep -E "^$KEY=" .env.tags | cut -d= -f2- || true)"
set_tag() {
  if grep -qE "^$KEY=" .env.tags; then
    sed -i "s|^$KEY=.*|$KEY=$1|" .env.tags
  else
    echo "$KEY=$1" >> .env.tags
  fi
}
log() { echo "$(date '+%F %T')  $SVC  ${PREV:-none} -> $TAG  $1" >> deploy-history.log; }

# 이미지에 정의된 HEALTHCHECK가 healthy가 될 때까지 기다린다 (3초 × 60 = 최대 3분)
wait_healthy() {
  local id status
  for _ in $(seq 1 60); do
    id="$("${COMPOSE[@]}" ps -q "$SVC")"
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo missing)"
    case "$status" in
      healthy)   return 0 ;;
      unhealthy) return 1 ;;
      none)      echo "[deploy] 이미지에 HEALTHCHECK가 없습니다 — 실행 중이면 성공으로 봅니다" >&2
                 [ "$(docker inspect -f '{{.State.Running}}' "$id")" = "true" ] && return 0 || return 1 ;;
    esac
    sleep 3
  done
  return 1
}

# 실패 · 중단 시 이전 태그로 되돌린다 (컨테이너 생성 실패, 헬스체크 실패, Jenkins 중단 모두)
rollback() {
  trap - INT TERM
  echo "[deploy] $SVC 실패 — 이전 태그(${PREV:-없음})로 되돌립니다" >&2
  "${COMPOSE[@]}" logs --tail=80 "$SVC" >&2 || true
  set_tag "${PREV:-none}"
  if [ -n "$PREV" ] && [ "$PREV" != "none" ]; then
    if "${COMPOSE[@]}" up -d --no-deps "$SVC"; then
      log "failed (rolled back to $PREV)"
    else
      log "failed (rollback to $PREV also failed)"
      echo "[deploy] 되돌리기도 실패했습니다 — 06 문서 런북 R1" >&2
    fi
  else
    "${COMPOSE[@]}" stop "$SVC" || true
    log "failed (no previous tag, stopped)"
  fi
}
trap 'rollback; exit 1' INT TERM

echo "[deploy] $SVC: ${PREV:-없음} → $TAG"
set_tag "$TAG"

# if 조건 안에서는 set -e가 멈추지 않으므로, up 실패도 아래 rollback으로 간다
if "${COMPOSE[@]}" up -d --no-deps "$SVC" && wait_healthy; then
  trap - INT TERM
  echo "[deploy] $SVC 정상 동작 ($TAG)"
  log ok
  exit 0
fi

rollback
exit 1
