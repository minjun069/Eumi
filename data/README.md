# data — 데이터 분석·적재 파이프라인

| 폴더 | 용도 |
|---|---|
| `notebooks/` | 탐색·분석 노트북 |
| `pipeline/` | 월 데이터 적재·분석 스크립트 (운영자 실행, 기능명세서 2.2.1). Spark 컨테이너에서 `spark-submit pipeline/<잡>.py` |
| `raw/` | 원본 데이터 (**커밋하지 않음**) |
| `processed/` | 가공 데이터 (**커밋하지 않음**) |

## 실행 환경

- MinIO · Kafka · Spark는 `infra/docker-compose.yml`의 profile `data`. 켜는 법과 접속 정보는 [infra/README.md](../infra/README.md).
- 환경변수는 `infra/.env` 한 곳에서 관리한다. Spark 컨테이너에는 compose가 넣어 주고, 호스트에서 도는 스크립트는 python-dotenv로 `infra/.env`를 읽는다.
- `pipeline/check_infra.py`: 인프라 연결 확인 (s3a 쓰기·읽기, 테이블 11개, JDBC, DML 권한, Kafka 메시지 1건 왕복).

## 저장소 규칙 (인수인계 요약)

- MinIO 버킷 `sgi`: `raw/<소스>/<기준시점>/<파일명>`, 완성본은 `raw/final_sets/`, 가상 유동은 `synth/`
- Kafka 토픽 `flow_hourly`: 키 grid_cd, 값 JSON (ts, grid_cd, 성·연령 12칸)
- DB: `dim_region`·`region_result`는 `public`, 나머지 파이프라인 테이블은 `analysis` 스키마. 계정 `eumi_pipeline`은 TRUNCATE·DROP·CREATE 권한이 없다 → Spark `overwrite` 금지, "그 달 삭제 후 append" 또는 `INSERT ... ON CONFLICT`. `dim_region`은 DELETE 권한도 없으므로 UPSERT만
- 키: 동 `adm_cd10`, 격자 `grid_cd`, 기준월 `period_start`(월 1일), 연 자료 `ref_year`. 좌표계 EPSG:5179
- 계산 못 한 지표는 NULL (0 금지)

## 결정 기록

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-10-30 | `dim_region.geom`은 TEXT(GeoJSON), PostGIS 없음 | DB가 `postgres:17` 이미지라 PostGIS 확장이 없다 (`SELECT PostGIS_Version()` 실패, `pg_available_extensions`에도 없음). 테이블 정의서의 GEOMETRY 표기는 TEXT로 고친다 |
| 2026-10-30 | 등급 방향은 인수인계 기준: `bg_grade`·`bh_grade` 1~3 (3 = 위험), `risk_grade` 1~5 (5 = 최우선) | 정의서(1 = 높음)·V5 주석(1~5)·프론트 타입(1~5)이 서로 달라 데이터 파트가 확정. V5의 CHECK(1~5)는 그대로 통과한다. 백엔드·프론트에 공유 필요 |
| 2026-10-30 | MinIO는 `bitnamilegacy/minio:2025.7.23` | MinIO 커뮤니티 이미지 배포 중단 (infra/README.md 참고) |

- 원본 데이터 공유 위치: (작성)
- 노트북은 실행 결과(출력)를 지우고 커밋하는 것을 권장합니다. 결과에 데이터가 그대로 남을 수 있습니다.
- 개인정보가 포함된 파일은 어떤 폴더에도 커밋하지 않습니다.
