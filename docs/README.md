# 문서

| 문서 | 파일 | 상태 |
|---|---|---|
| AI 개발 문서 | [../ai/docs/README.md](../ai/docs/README.md) | 설계 명세·구현 안내·개발 지침 |
| AI 런타임 API | [../ai/docs/runtime/api.md](../ai/docs/runtime/api.md) | 연동 계약·검증 절차. 공통 API와의 차이는 본문의 연동 대조 참고 |
| 기준 문서: 테이블 정의서 · API 명세 · 기능명세 | [spec/](spec/README.md) (md 원본 + 엑셀) | 테이블 정의서 2.4.1 · API 명세 2.5.1 · 기능명세 2.4.0 (11/10 AI-b 인사이트 보고서 · 보고서 2단계 V20261110_02, 11/10 C4 형식 변경, 11/11 A2 구현 반영). DB 기준은 `db/migration` |
| ERD | [spec/table-definition.md](spec/table-definition.md) | 최종 구조는 테이블 정의서에 있음. 그림은 저장소 밖 ERDCloud |
| 확정 계약 목록 | [api/README.md](api/README.md) | 확정된 계약만 둠 |
| API 공통 규칙 (응답 · 오류 · 세션 · 입력값 · 페이지) | [api/공통_응답_및_세션_규칙.md](api/공통_응답_및_세션_규칙.md) | 확정 (11/7 정리) |
| API 계약 (OpenAPI) | [api/openapi.json](api/openapi.json) | 2.4.0 (11/10, AI-b: API-11 · 12 새 형식 · INT-05 dongCodes · INT-08) |
| AI 에이전트 패널 동작 | [api/ai-agent-panel.md](api/ai-agent-panel.md) | 확정 (11/2, A 방식 · 11/9 AI-a 연결 반영) |
| 인사이트 보고서 내부 연동 | [api/insight-report.md](api/insight-report.md) | 확정 (11/10, AI 구현에 맞춤. AI 구현이 아직 다른 곳은 0절) |
| 저장소 초기 설정 | [gitlab-setup.md](gitlab-setup.md) | - |
| 결정 기록: 로그인 방식 · 에이전트 흐름 전달 | [decisions/login-sse.md](decisions/login-sse.md) | 확정 (11/2 수정: 에이전트 흐름 SSE → 1초 조회) |
| 결정 기록: 내부 연동 (BE · AI · 파이프라인) | [decisions/internal-integration.md](decisions/internal-integration.md) | 확정 (11/6, 11/7 보완). 구현은 [계획](work-ref/내부_연동_변경_계획.md)대로 진행 |
| 작업 참고 | [work-ref/](work-ref/README.md) | 작업 계획에 딸린 참고 문서. 계획이 끝나면 바뀐 계약을 api/에 반영하고 지움 |

본문의 기준일·수정일과 상태를 갱신합니다. 현재 문서는 한 곳에서 관리하며 이전 판은 Git 기록으로 확인합니다. AI 문서의 구조·파일명·검수 기준은 [AI 문서 작성 지침](../ai/docs/writing-guide.md)을 따릅니다.

- 기준 문서(`spec/`)는 md를 고치고, 엑셀은 `python docs/spec/build_xlsx.py`로 다시 만듭니다. 엑셀만 따로 고치지 않습니다 ([spec/README.md](spec/README.md)).
- 확정 계약(`api/`)에는 확정된 계약만 둡니다. 계약을 바꾸는 작업은 작업 참고(`work-ref/`)의 계획으로 진행하고, 계획이 끝나는 MR에서 `api/`를 작업한 내용대로 고친 뒤 `work-ref/`의 해당 문서를 지웁니다 ([api/README.md](api/README.md), [work-ref/README.md](work-ref/README.md)).
