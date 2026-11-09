#!/usr/bin/env bash
# ==========================================================================
# 서비스별로 배포 이미지(master-*, manual-*) 중 최근 KEEP(기본 3)개만 남긴다.
# 남긴 이미지가 곧 롤백할 수 있는 버전이다. 실행 중인 컨테이너가 쓰는 이미지는 docker가 지우지 않는다.
#
# 사용법:  sudo -u jenkins /srv/eumi/scripts/cleanup-images.sh   (Jenkins Cleanup 단계가 배포마다 실행)
#
# 금지: docker image prune -a, docker system prune -a
#       (태그가 있어도 지워서 롤백할 이미지가 모두 사라진다. -a 없이 쓰면 이름 없는 이미지만 지운다)
# 금지: docker volume prune, docker system prune --volumes (DB 볼륨 삭제 위험)
# ==========================================================================
set -euo pipefail

KEEP="${KEEP:-3}"

for svc in ai backend web; do
  repo="eumi-$svc"
  # docker images는 최신순이다 → 앞의 KEEP개를 건너뛰고 나머지를 지운다
  docker images "$repo" --format '{{.Tag}}' \
    | grep -E '^(master|manual)-' \
    | tail -n +$((KEEP + 1)) \
    | while read -r tag; do
        if docker rmi "$repo:$tag" >/dev/null 2>&1; then
          echo "[cleanup] 삭제: $repo:$tag"
        else
          echo "[cleanup] 건너뜀(사용 중): $repo:$tag"
        fi
      done || true
done

# 이름 없는 이미지와 1주일 넘은 빌드 캐시만 정리한다
docker image prune -f >/dev/null
docker builder prune -f --filter "until=168h" >/dev/null || true

echo "[cleanup] 완료 — 서비스별 최근 ${KEEP}개 유지"
df -h / | tail -1 | awk '{print "[cleanup] 디스크 사용: " $3 " / " $2 " (" $5 ")"}'
