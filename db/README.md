# db — PostgreSQL 스키마

백엔드(Spring Boot), AI 서버(FastAPI), 데이터 파이프라인이 같은 DB를 쓰므로 스키마를 이 폴더 한 곳에서 관리합니다.

| 폴더 | 용도 |
|---|---|
| `migration/` | 스키마 변경 SQL. 번호 순서대로 적용 |
| `seed/` | 지역·기관 기준 정보, 테스트 데이터 |

## 규칙

- 파일 이름: `V{번호}__{설명}.sql` (예: `V1__init.sql`, `V2__add_client_index.sql`)
- 이미 `develop`에 병합된 migration 파일은 고치지 않고, 새 번호의 파일로 변경합니다.
- 스키마를 바꾸는 MR은 백엔드 담당자 리뷰를 받습니다.
- 적용 도구(Flyway 등)는 정해지면 여기에 적습니다.
