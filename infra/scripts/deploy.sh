#!/usr/bin/env bash
# ==========================================================================
# 서비스 하나를 새 이미지 태그로 바꾸고 헬스체크를 기다린다. 실패하면 이전 태그로 되돌린다.
#
# 사용법 (jenkins 계정으로):  sudo -u jenkins /srv/eumi/scripts/deploy.sh <ai|backend|web|pipeline> <태그>
#   롤백도 같은 명령에 이전 태그를 주면 된다.
#   보관 중인 태그 보기:  docker images eumi-backend
#   배포 기록:            /srv/eumi/deploy-history.log
#
# 교체하는 몇 초~1분 동안은 해당 서비스 응답이 끊길 수 있다 (무중단 배포는 쓰지 않는다).
#
# pipeline은 컨테이너가 여러 개다. 같은 태그로 다음 순서로 띄운다 (Grafana는 태그가 없어 grafana.sh가 따로 띄운다):
#   minio · kafka 기동(healthy) → kafka-init(토픽) → pipeline-init(Airflow DB 마이그레이션 · 관리자 · Grafana 읽기 권한)
#   → pipeline(스케줄러) · pipeline-web(Airflow 화면) 교체 → 둘 다 healthy 확인
#   실패하면 pipeline · pipeline-web만 이전 태그로 되돌린다 (minio · kafka는 그대로 둔다. 앱 서비스와 eumi DB에는 영향이 없다)
# ==========================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.config --env-file .env.tags)

USAGE="사용법: deploy.sh <ai|backend|web|pipeline> <태그>"
SVC="${1:?$USAGE}"
TAG="${2:?$USAGE}"

UNITS=("$SVC")      # 교체하고 헬스체크를 기다릴 compose 서비스 (pipeline만 2개)
WAIT_TRIES=60       # 3초 × 60 = 최대 3분
case "$SVC" in
  ai)       KEY=AI_TAG ;;
  backend)  KEY=BACKEND_TAG ;;
  web)      KEY=WEB_TAG ;;
  pipeline) KEY=PIPELINE_TAG; UNITS=(pipeline pipeline-web); WAIT_TRIES=120 ;;   # Airflow는 뜨는 데 1~2분 걸린다 (최대 6분)
  *) echo "[deploy] 알 수 없는 서비스: $SVC ($USAGE)" >&2; exit 1 ;;
esac

# ai의 비밀값은 compose가 :? 없이 넘기므로(profile 서비스라도 :?는 모든 compose 명령을 멈춘다) 여기서 먼저 확인한다
if [ "$SVC" = ai ]; then
  for k in EUMI_AI_PASSWORD EUMI_LLM_API_KEY EUMI_AI_TOKEN; do
    if ! grep -qE "^$k=.+" .env.config; then
      echo "[deploy] .env.config에 $k 값이 없습니다 — ai를 배포하지 않습니다 (.env.config.example 참고)" >&2
      exit 1
    fi
  done
fi

# pipeline도 같은 이유로 여기서 확인한다: 비밀값 9개, 원본 저장소 볼륨, Airflow 메타 DB (infra/README.md "데이터 파이프라인 · Grafana (운영)")
if [ "$SVC" = pipeline ]; then
  for k in MINIO_ROOT_USER MINIO_ROOT_PASSWORD AIRFLOW_DB_PASSWORD AIRFLOW_ADMIN_USER AIRFLOW_ADMIN_PASSWORD AIRFLOW_SECRET_KEY \
           EUMI_PIPELINE_PASSWORD DATA_GO_KR_SERVICE_KEY KAKAO_REST_KEY; do
    if ! grep -qE "^$k=.+" .env.config; then
      echo "[deploy] .env.config에 $k 값이 없습니다 — pipeline을 배포하지 않습니다 (.env.config.example 참고)" >&2
      exit 1
    fi
  done
  if ! docker volume inspect eumi-miniodata >/dev/null 2>&1; then
    echo "[deploy] 볼륨 eumi-miniodata가 없습니다 — docker volume create eumi-miniodata 로 먼저 만듭니다" >&2
    exit 1
  fi
  if [ "$("${COMPOSE[@]}" exec -T postgres psql -U postgres -Atc "select count(*) from pg_database where datname='airflow'" </dev/null 2>/dev/null || true)" != "1" ]; then
    echo "[deploy] postgres에 airflow DB가 없거나 DB에 닿지 않습니다 — README의 계정 · DB 생성 명령을 먼저 실행합니다" >&2
    exit 1
  fi
fi

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

# HEALTHCHECK(이미지 또는 compose에 정의)가 healthy가 될 때까지 기다린다 (3초 × WAIT_TRIES)
wait_one() {
  local unit="$1" id status
  for _ in $(seq 1 "$WAIT_TRIES"); do
    id="$("${COMPOSE[@]}" ps -q "$unit")"
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo missing)"
    case "$status" in
      healthy)   return 0 ;;
      unhealthy) return 1 ;;
      none)      echo "[deploy] $unit: HEALTHCHECK가 없습니다 — 실행 중이면 성공으로 봅니다" >&2
                 [ "$(docker inspect -f '{{.State.Running}}' "$id")" = "true" ] && return 0 || return 1 ;;
    esac
    sleep 3
  done
  return 1
}
wait_healthy() {
  local unit
  for unit in "${UNITS[@]}"; do
    wait_one "$unit" || { echo "[deploy] $unit 가 healthy가 되지 않았습니다" >&2; return 1; }
  done
}

# 교체 전에 할 일 (pipeline만): 저장소 · 큐를 띄우고, 토픽과 Airflow 메타 DB를 새 태그로 맞춘다. 여러 번 실행해도 안전하다
prepare() {
  [ "$SVC" = pipeline ] || return 0
  echo "[deploy] pipeline: minio · kafka 기동 (healthy까지 최대 4분)"
  "${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 240 minio kafka || return 1
  echo "[deploy] pipeline: kafka-init (토픽 flow_hourly)"
  "${COMPOSE[@]}" run --rm -T --no-deps kafka-init </dev/null || return 1
  echo "[deploy] pipeline: pipeline-init (Airflow DB 마이그레이션 · 관리자 계정 · Grafana 읽기 권한)"
  "${COMPOSE[@]}" run --rm -T --no-deps pipeline-init </dev/null || return 1
}

# 실패 · 중단 시 이전 태그로 되돌린다 (컨테이너 생성 실패, 헬스체크 실패, Jenkins 중단 모두)
rollback() {
  trap - INT TERM
  echo "[deploy] $SVC 실패 — 이전 태그(${PREV:-없음})로 되돌립니다" >&2
  "${COMPOSE[@]}" logs --tail=80 "${UNITS[@]}" >&2 || true
  set_tag "${PREV:-none}"
  if [ -n "$PREV" ] && [ "$PREV" != "none" ]; then
    if "${COMPOSE[@]}" up -d --no-deps "${UNITS[@]}"; then
      log "failed (rolled back to $PREV)"
    else
      log "failed (rollback to $PREV also failed)"
      echo "[deploy] 되돌리기도 실패했습니다 — 06 문서 런북 R1" >&2
    fi
  else
    "${COMPOSE[@]}" stop "${UNITS[@]}" || true
    log "failed (no previous tag, stopped)"
  fi
}
trap 'rollback; exit 1' INT TERM

echo "[deploy] $SVC: ${PREV:-없음} → $TAG"
set_tag "$TAG"

# if 조건 안에서는 set -e가 멈추지 않으므로, 준비 · up 실패도 아래 rollback으로 간다
if prepare && "${COMPOSE[@]}" up -d --no-deps "${UNITS[@]}" && wait_healthy; then
  trap - INT TERM
  echo "[deploy] $SVC 정상 동작 ($TAG)"
  log ok
  exit 0
fi

rollback
exit 1
