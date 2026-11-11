# Grafana 서버 배포 인계 (데이터 파트 → 인프라 담당)

작성 2026-11-10, 데이터 파트(강병민). 운영 서버에 Grafana(대시보드 2개 + Mattermost 알림 8종)를 올릴 때 인프라 담당이 넣어야 하는 것을 정리한다. 비밀값은 여기 적지 않는다.

## 1. 요약

- **언제**: 데이터 파이프라인 서버 구성(11/3 에 되돌린 `606d28f` 를 다시 적용)과 같이 올린다. Grafana 는 Airflow 실행 이력(`airflow` DB)과 결과 테이블(`eumi` DB)을 읽으므로, Airflow 없이 올리면 실행 현황 패널과 배치 알림이 비어 있다.
- **무엇**: 컨테이너 1개(`grafana/grafana-oss:12.4.3`). 설정은 전부 저장소의 `infra/grafana/provisioning/` 파일이라 서버 화면에서 손으로 설정할 것은 없다.
- **`606d28f` 에는 Grafana 가 없다.** 그 커밋 뒤에 만든 것이라 아래 2~5 를 새로 넣어야 한다.
- **확인된 것**: 아래 compose 의 환경변수 그대로 임시 컨테이너를 띄워 `/grafana/` 하위 경로 · 데이터소스 2개 연결 · 대시보드 2개 · 알림 제목 "[운영]" · Airflow 링크를 확인했다 (로컬, 11/10).
- **확인하지 못한 것**: Nginx 블록, `sync.sh` · Jenkins 변경은 서버에서만 확인할 수 있어 초안이다.

## 2. 운영 compose 에 넣을 서비스 (초안)

`infra/deploy/docker-compose.prod.yml` 의 `services:` 와 `volumes:` 에 넣는다.

```yaml
  # 파이프라인 모니터링: 대시보드 2개 + Mattermost 알림 8종. 설정은 전부 ./grafana/provisioning 의 파일이다
  #   - 호스트 3000 은 web 이 쓰므로 3001 에 묶는다. 밖에서는 Nginx /grafana/ 로만 들어온다 (로그인 필요)
  #   - DB 는 읽기 전용 계정 eumi_monitor 로 읽는다 (eumi DB 결과 테이블 + airflow DB 실행 이력)
  #   - 관리자 비밀번호가 비면 Grafana 기본값(admin)으로 뜨므로 :? 로 막는다
  grafana:
    image: grafana/grafana-oss:12.4.3
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?.env.config에 GRAFANA_ADMIN_PASSWORD가 필요합니다}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_NEWS_NEWS_FEED_ENABLED: "false"
      GF_DATE_FORMATS_DEFAULT_TIMEZONE: Asia/Seoul
      # Nginx 하위 경로. 알림 메시지의 "대시보드 열기" 링크도 이 주소로 만들어진다
      GF_SERVER_ROOT_URL: https://k15b201.p.ssafy.io/grafana/
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
      # provisioning/datasources/eumi.yml 이 읽는 값
      EUMI_MONITOR_PASSWORD: ${EUMI_MONITOR_PASSWORD:?.env.config에 EUMI_MONITOR_PASSWORD가 필요합니다}
      # provisioning/alerting/contact-points.yml 이 읽는 값. 웹훅이 비면 닿지 않는 주소로 보내다 실패하고 끝난다
      MATTERMOST_WEBHOOK_URL: ${MATTERMOST_WEBHOOK_URL:-http://127.0.0.1:9/eumi-alert-webhook-not-set}
      EUMI_ALERT_ENV: 운영
      EUMI_AIRFLOW_URL: https://k15b201.p.ssafy.io/airflow/
      TZ: Asia/Seoul
    ports:
      - "127.0.0.1:3001:3000"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - grafanadata:/var/lib/grafana
    depends_on:
      postgres:
        condition: service_healthy
    mem_limit: 512m
    logging: *logging
```

```yaml
volumes:
  grafanadata:
    name: eumi-grafanadata      # 알림 상태 · 보낸 기록. 지워져도 설정은 파일에서 다시 만들어진다
```

`postgres` 서비스의 `environment` 에도 한 줄을 넣는다. 볼륨을 새로 만들 때 `01-eumi-roles.sh` 가 이 값으로 `eumi_monitor` 를 만드는데, 값이 없으면 로컬 기본 비밀번호로 만들어진다.

```yaml
      EUMI_MONITOR_PASSWORD: ${EUMI_MONITOR_PASSWORD:?.env.config에 EUMI_MONITOR_PASSWORD가 필요합니다}
```

## 3. Nginx (초안)

`infra/deploy/nginx/eumi.conf` 의 443 서버 블록, Jenkins 블록 근처에 넣는다. Grafana 가 하위 경로를 직접 처리하므로(`SERVE_FROM_SUB_PATH`) 경로를 바꿔 쓰지 않는다.

```nginx
    # ---------- Grafana (127.0.0.1:3001, root_url /grafana/, 로그인 필요) ----------
    location = /grafana { return 301 /grafana/; }
    location /grafana/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
    # 화면의 실시간 갱신(웹소켓). 없어도 대시보드는 주기적으로 새로 읽는다
    location /grafana/api/live/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
    }
```

## 4. 비밀값 (`.env.config.example` 에 키 이름 추가)

| 키 | 값 | 비고 |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | 서버에서 `openssl rand -hex 24` | Grafana 화면 로그인 (계정 `admin`) |
| `EUMI_MONITOR_PASSWORD` | 서버에서 `openssl rand -hex 24` | DB 읽기 계정. 5-1 에서 계정을 만들 때 같은 값을 쓴다 |
| `MATTERMOST_WEBHOOK_URL` | 데이터 파트가 Mattermost 비공개로 전달 | 알림을 보낼 수신 웹훅. 비워 두면 알림을 보내지 않는다 |

`EUMI_ALERT_ENV` · `EUMI_AIRFLOW_URL` 은 비밀값이 아니라 compose 에 직접 적었다.

## 5. 서버에서 한 번 하는 일

### 5-1. DB 읽기 계정 (Grafana 를 띄우기 전, 파이프라인 첫 배포 전에)

서버 DB 볼륨은 이미 있어서 init 스크립트가 돌지 않는다. 계정이 있는지 먼저 본다.

```bash
sudo -u jenkins /srv/eumi/scripts/dc.sh exec postgres psql -U postgres -c "\du eumi_monitor"
```

없으면 만든다 (`EUMI_MONITOR_PASSWORD` 와 같은 값). 읽기만 하고, 동시 접속 10개 · 쿼리 30초로 제한된다.

```bash
sudo -u jenkins /srv/eumi/scripts/dc.sh exec postgres psql -U postgres -c "CREATE ROLE eumi_monitor LOGIN PASSWORD '<EUMI_MONITOR_PASSWORD 값>' CONNECTION LIMIT 10" -c "ALTER ROLE eumi_monitor SET statement_timeout = '30s'" -c "GRANT pg_read_all_stats TO eumi_monitor"
```

이미 있으면 비밀번호만 맞춘다: `ALTER ROLE eumi_monitor PASSWORD '<값>'`.

테이블 권한은 따로 주지 않아도 된다.

- `eumi` DB: 다음 Flyway 실행(`migrate.sh`) 때 `afterMigrate.sql` 이 준다 (계정이 있을 때만 주게 되어 있다).
- `airflow` DB: `pipeline-init` 이 `airflow db migrate` 뒤에 `grant_monitor.py` 로 준다. 그래서 계정을 **파이프라인 첫 배포 전에** 만든다. 순서가 바뀌었으면 `pipeline-init` 을 한 번 더 돌린다.

### 5-2. 설정 파일 복사 (`sync.sh`)

`infra/grafana/provisioning/` 을 서버 `/srv/eumi/grafana/provisioning/` 으로 복사한다. `db/` 처럼 통째로 바꿔치기해야 저장소에서 지운 파일이 서버에 남지 않는다.

```bash
rm -rf "$APP_DIR/grafana.new"
mkdir -p "$APP_DIR/grafana.new"
cp -r "$SRC/infra/grafana/provisioning" "$APP_DIR/grafana.new/"
chmod -R u=rwX,go=rX "$APP_DIR/grafana.new"
rm -rf "$APP_DIR/grafana.old"
[ -d "$APP_DIR/grafana" ] && mv "$APP_DIR/grafana" "$APP_DIR/grafana.old"
mv "$APP_DIR/grafana.new" "$APP_DIR/grafana"
rm -rf "$APP_DIR/grafana.old"
```

### 5-3. 띄우기 · 다시 띄우기

Grafana 는 공식 이미지를 그대로 써서 빌드 · 태그가 없다. `deploy.sh <서비스> <태그>` 대상이 아니다.

- 처음: `sudo -u jenkins /srv/eumi/scripts/dc.sh up -d grafana`
- 그 뒤: `infra/grafana/` 아래 파일이 바뀐 배포에서 `dc.sh restart grafana`. 대시보드 JSON 은 30초마다 다시 읽지만 **알림 설정은 다시 띄워야** 반영된다. Jenkins Deploy 단계에 "바뀐 파일에 `infra/grafana/` 가 있으면 restart" 를 넣으면 된다.
- 다시 띄운 직후 약 1분은 이전에 저장된 알림 설정(보낼 곳 · 제목)이 쓰인다 (로컬에서 확인). 웹훅 주소를 바꾼 직후에는 이 점을 감안한다.

## 6. 배포 뒤 확인 (데이터 파트와 같이)

1. `https://k15b201.p.ssafy.io/grafana/` 에 `admin` 으로 로그인된다.
2. Connections → Data sources 에서 `eumi` · `airflow` 를 각각 Test → 둘 다 OK.
3. Dashboards → Eumi 폴더의 "Eumi 파이프라인" · "Eumi 스트리밍" 이 열린다.
4. Alerting → Alert rules 의 Eumi 폴더에 규칙 8개가 있고 Normal 이다.
   - DAG `eumi_monthly` 를 unpause 하기 전에는 "월 배치가 돌지 않음" 이 울릴 수 있다 (6일 09:00 이 지났는데 전월 실행 기록이 없으므로). unpause 하면 지난 스케줄 1건이 건너뜀으로 끝나면서 꺼진다.
5. Alerting → Contact points → `eumi-mattermost` → Test 로 시험 알림 1건을 보내 채널에 "[운영] …" 이 오는지 본다.

## 7. 서버에서 로컬과 다른 점

- **유동 상세가 없다**: 서버 DB 에는 `analysis.flow_detail` 이 없다 (seed 에서 제외). 대시보드 "테이블 최신성" 에 유동 상세가 비어 보이는 것이 정상이다.
- **검사 기록이 없다**: `analysis.pipeline_check` 가 비어 있어 "검사 결과" 칸이 "기록 없음" 이다. 서버에서 월 배치가 처음 실제로 돌면 채워진다.
- **과거 달을 서버에서 다시 돌리지 않는다**: 유동 상세가 없는 상태로 2025-12 를 다시 돌리면 행동 지표의 변화 항목이 NULL 로 덮이고 격자 이상 점수가 지워진다. 필요하면 데이터 파트가 먼저 11 · 12월 유동 상세를 적재한다 (데이터 파트 결정 사항, 미정).
- **스트리밍 대시보드**: 스트리밍은 시연 때만 수동으로 돌리므로 평소에는 "멈춤" 이 정상이다.
- **알림 담당**: 서버가 알림을 보내기 시작하면 데이터 파트 로컬 `.env` 의 웹훅은 뺀다. 그 전까지 채널에 오는 알림은 제목이 "[로컬]" 로 시작한다.
- **자원**: 메모리 상한 512 MB 로 잡았다. 로컬에서는 약 114 MB 를 쓰고 있다 (11/10, 대시보드 2개 · 규칙 8개). 디스크는 거의 쓰지 않는다.

## 8. 끝나는 조건

운영 서버에 Grafana 가 뜨고 6번 확인이 끝나면, 그 MR 에서 `infra/README.md` 운영 절에 위 내용을 반영하고 이 문서와 `docs/work-ref/README.md` 표의 줄을 지운다.
