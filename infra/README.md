# infra — 실행 환경

예정 파일:

| 파일 | 용도 |
|---|---|
| `docker-compose.yml` | 로컬 개발용 PostgreSQL과 각 서버 실행 |
| `.env.example` | 필요한 환경 변수 목록 (값은 비워 둠) |

- 실제 값이 들어간 `.env`는 커밋하지 않습니다.
- CI/CD 도구(GitLab CI 또는 Jenkins)와 배포 서버는 정해지면 여기에 적습니다.
