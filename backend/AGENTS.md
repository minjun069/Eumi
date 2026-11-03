# 백엔드 작업 기록 진입점

상위 AGENTS.md와 사용자의 승인 범위를 우선한다. 이 파일은 backend 기록을 찾기 위한 안내다.

- 2026-10-31 이후 이어갈 때는 [11월 1일 재개 안내](docs/g1/2026-11-01_이어가기.md)를 먼저 확인한다. 최신 develop 반영·운영 설정 보완은 미완료이며 오늘은 작업 브랜치 보관을 우선하기로 했다.
- 작업을 이어갈 때 [README.md](README.md), [G1 범위와 인계](docs/g1/README.md), [구현 결정](docs/g1/decisions.md), [검증 기록](docs/g1/verification.md)을 먼저 읽는다.
- 문서의 날짜·커밋·검사 결과를 현재 소스·Git 상태와 대조한다. 예상 결과를 실행 결과로 취급하지 않는다.
- 실제 PostgreSQL·HTTP·Mailpit 검사와 fixture 검사를 구분하고, 코드 변경 후 관련 기록을 갱신한다.
- clone·fetch·pull·commit·push·merge는 이번 작업에서 사용자가 직접 실행하기로 했다. 권한이 변경되지 않았다면 대신 실행하지 않는다.
- 기록에 비밀값·쿠키 값·인증 코드·가입 증명 원문을 남기지 않는다.
