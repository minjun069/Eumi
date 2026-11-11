#!/usr/bin/env bash
# ==========================================================================
# Grafana(파이프라인 모니터링)를 띄우거나, 바뀐 설정을 다시 읽게 한다.
#   공식 이미지를 그대로 써서 빌드 · 태그가 없다 → deploy.sh <서비스> <태그> 대상이 아니다.
#   설정은 전부 /srv/eumi/grafana/provisioning 의 파일이다 (sync.sh가 저장소 infra/grafana/provisioning 을 복사).
#
# 사용법 (jenkins 계정으로):
#   sudo -u jenkins /srv/eumi/scripts/grafana.sh              처음 띄우기, .env.config 값을 바꾼 뒤 (바뀐 게 없으면 그대로 둔다)
#   sudo -u jenkins /srv/eumi/scripts/grafana.sh --restart    설정 파일이 바뀐 뒤 (알림 설정은 다시 띄워야 반영된다)
#   --skip-if-unconfigured   비밀값이나 DB 계정이 아직 없으면 실패하지 않고 건너뛴다 (Jenkins가 쓴다)
#
# 다시 띄운 직후 약 1분은 이전에 저장된 알림 설정(보낼 곳 · 제목)이 쓰인다.
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)

RESTART=no
SKIP=no
for a in "$@"; do
  case "$a" in
    --restart)              RESTART=yes ;;
    --skip-if-unconfigured) SKIP=yes ;;
    *) echo "[grafana] 알 수 없는 옵션: $a (사용법: grafana.sh [--restart] [--skip-if-unconfigured])" >&2; exit 1 ;;
  esac
done

# 준비가 안 됐을 때: 건너뛰거나(Jenkins) 멈춘다(사람)
not_ready() {
  if [ "$SKIP" = yes ]; then
    echo "[grafana] $1 — 이번에는 띄우지 않습니다 (infra/README.md \"데이터 파이프라인 · Grafana (운영)\")"
    exit 0
  fi
  echo "[grafana] $1" >&2
  exit 1
}

# 관리자 비밀번호가 비면 Grafana가 기본값(admin)으로 뜨므로, 값이 있을 때만 띄운다 (MATTERMOST_WEBHOOK_URL은 없어도 된다)
for k in GRAFANA_ADMIN_PASSWORD EUMI_MONITOR_PASSWORD; do
  grep -qE "^$k=.+" .env.config || not_ready ".env.config에 $k 값이 없습니다"
done
[ -d grafana/provisioning ] || not_ready "grafana/provisioning 폴더가 없습니다 (sync.sh가 복사한다)"
if [ "$("${COMPOSE[@]}" exec -T postgres psql -U postgres -Atc "select count(*) from pg_roles where rolname='eumi_monitor'" </dev/null 2>/dev/null || true)" != "1" ]; then
  not_ready "DB에 eumi_monitor 계정이 없거나 DB에 닿지 않습니다"
fi

BEFORE="$("${COMPOSE[@]}" ps -q grafana 2>/dev/null || true)"
"${COMPOSE[@]}" up -d --no-deps grafana
AFTER="$("${COMPOSE[@]}" ps -q grafana)"
# up이 컨테이너를 새로 만들었으면(처음이거나 compose · 비밀값이 바뀜) 이미 새 설정을 읽었다. 그대로였을 때만 다시 띄운다
if [ "$RESTART" = yes ] && [ -n "$BEFORE" ] && [ "$BEFORE" = "$AFTER" ]; then
  echo "[grafana] 설정을 다시 읽도록 재시작"
  "${COMPOSE[@]}" restart grafana
fi

# compose에 정의한 헬스체크가 healthy가 될 때까지 (3초 × 40 = 최대 2분)
for _ in $(seq 1 40); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$AFTER" 2>/dev/null || echo missing)"
  case "$status" in
    healthy)   echo "[grafana] 정상 동작 — https://k15b201.p.ssafy.io/grafana/ (Nginx /grafana/ 블록이 반영돼 있어야 열린다)"; exit 0 ;;
    unhealthy) break ;;
  esac
  sleep 3
done

echo "[grafana] healthy가 되지 않았습니다 — 최근 로그:" >&2
"${COMPOSE[@]}" logs --tail=60 grafana >&2 || true
exit 1
