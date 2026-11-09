# AI 개발 문서

기준일: 2026-11-06.

데이터 분석 결과 해석·데이터 시각화·사용자 요청 처리 Agent의 설계 명세와 개발 안내를 관리한다. 설계 기준과 현재 구현 상태를 구분하며, 설치·기본 실행은 [AI README](../README.md)에서 확인한다.

## 설계 명세

업무 범위 → 아키텍처 → 기능 명세 → 실행 흐름 → State 순서로 읽는다. API의 확정 내용과 협의 중인 항목은 연동 문서의 상태 표시를 따른다.

| 문서 | 다루는 내용 |
| --- | --- |
| [업무 범위](ieumi-workflow-agent-context.md) | 사용자, 문제, 지원 범위, 담당자 역할 |
| [아키텍처](ai-agent-architecture.md) | 시스템 구성·담당 범위, 실행 API·상태 공유·공유 DB 구조 |
| [백엔드 연동 API](ai-runtime-api-20261029.md) | INT-01·02·05·07·08, 행 저장·알림, 시간·재요청·실패 처리 |
| [기능 명세](ieumi-agent-components.md) | 용어, 도구 입출력, Agent별 역할·명세 |
| [실행 흐름](ieumi-agent-workflow-design.md) | 시작 이벤트, 호출 순서, 중간 응답·화면 전달, 질문·재개·종료·오류 처리 |
| [State](ieumi-agent-state.md) | 필드·자료형·노드별 쓰기 범위·실행 상태 |
| [컨텍스트](ai-agent-context.md) | 정보 보관 위치·쓰기 범위와의 구분·추후 컨텍스트 정책 |
| [데이터](ieumi-agent-data.md) | 활용 자료·접근 방식·출처·갱신 |
| [작업 지침](ai-agent-instructions.md) | 지침 작성·적용·관리·검증 |
| [평가](ieumi-agent-evaluation.md) | 도구·개별 노드·Agent 전체 평가, 서비스 연동 검증, 업무 효과 |
| [모니터링](ai-agent-monitoring.md) | Langfuse 구현 의도·상태, 관측 항목·해석 기준 |
| [실행 시나리오](ai-agent-scenarios.md) | 장면별 입력·처리·시연 문구·산출물·예외 |

## 구현·실행 안내

| 문서 | 다루는 내용 |
| --- | --- |
| [설치·실행](../README.md) | 환경 설정, 현재 API 동작과 제약, 로컬 데모 |
| [컨텍스트 구성](context-composition.md) | 현재 모델 입력 조립, 노드·역할별 정보 제공, 구현 경계 |
| [Tableau 시각화](TABLEAU.md) | 등록 뷰·입력 검사, Agent 연결, 프론트 전달 계약 |
| [API 왕복 검증](api-roundtrip.md) | 파일 저장소·실제 모델·HTTP 알림 검증의 실행·모니터링·실패 확인 |

## 개발·작성 지침

| 문서 | 다루는 내용 |
| --- | --- |
| [AI 코드 작업 지침](CODING_GUIDELINES.md) | 설계 준수, State 전달, 구현 책임, 변경·검증 절차 |
| [작성 지침](ai-agent-writing-guide.md) | 문서 문체·서식·내용 검수 기준 |

같은 명세는 한 문서에서 관리하고 다른 문서에서는 링크로 참조한다. 서비스 공통 API와 결정 기록은 [공통 문서 목록](../../docs/README.md)에서 확인한다.
