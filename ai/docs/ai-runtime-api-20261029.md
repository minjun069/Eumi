# AI 런타임 연동 API

수정일: 2026-11-09. 이번 백엔드 요청과 사용자 결정 기준이다. 기존 패널 계약은 적용하지 않는다.
AI 코드·문서만 변경하며 백엔드·DB·인프라 반영 여부는 별도로 검증한다.

## 1. 연결

백엔드가 Member 질문을 커밋한 뒤 AI 실행을 요청한다. AI는 단계별 진행·종료 행을
`ai_message`에 직접 커밋하고 INT-07로 알린다. 보고서도 AI가 직접 저장하며
요청의 전체 처리가 끝나면 INT-08로 알린다. INT-03 상태 조회·INT-06 보고서 PUT은 사용하지 않는다.

| ID | 방향 | 요청 | 본문 | 정상 응답 |
| --- | --- | --- | --- | --- |
| INT-01 | BE → AI | POST `/internal/agent/runs` | `{conversationId, messageId, context?: {dongCode?, month?}}` | 빈 202 |
| INT-02 | BE → AI | POST `/internal/agent/runs/{conversationId}/cancel` | 없음 | 빈 202 |
| INT-05 | BE → AI | POST `/internal/insight-reports/runs` | `{requestId, month, dongCodes}` | 빈 202 |
| INT-07 | AI → BE | POST `/api/internal/agent/notifications` | `{conversationId, messageId}` | 빈 204 |
| INT-08 | AI → BE | POST `/api/internal/analysis/insight-report-completions` | `{requestId, month, savedCount, failedDongCodes}` | 빈 204 |

INT-04 파이프라인 → BE의 월 분석 완료 요청은 백엔드 담당이며 AI에는 INT-05로 전달된다.
INT-07·08에는 `Authorization: Bearer <SETTINGS_BACKEND_TOKEN>`을 보낸다.
AI 수신 API는 내부망에서 제공하며 별도 인증을 추가하지 않는다.

## 2. 사용자 요청

`conversationId`는 UUID, `messageId`는 양의 int64다. INT-01의 ID는 Member 질문 행,
INT-07의 ID는 방금 커밋한 AI 행이다. DB의 `question_id`는 계속 Member 질문 ID를 가리킨다.
`context`는 선택 입력이다. 동 코드는 10자리 숫자 문자열, 월은 유효한 `YYYY-MM`이다.
정의되지 않은 필드·잘못된 형식은 본문 없는 400으로 거절한다. 질문이 없거나 대화가 다르면 400이다.
접수 중 DB 장애는 503이며 아직 작업을 접수한 것으로 보지 않는다.

| 상황 | 처리 |
| --- | --- |
| 같은 질문이 실행·조회 중 | 추가 실행 없이 202 |
| 같은 대화의 다른 질문이 실행 중 | 409 |
| 이미 끝 행이 있는 질문 재요청 | 추가 실행·행 저장·알림 없이 202 |
| 단계 시작 | 진행 행 저장·커밋 → INT-07 |
| 중간 결과 작성 | 진행 행의 details·artifacts 저장·커밋 → INT-07 |
| 완료·부분 완료 | 완료 행에 내용·산출물 저장 → INT-07 |
| 사용자 정보 필요 | 되묻기를 완료 행에 저장 → INT-07. 이번 질문은 끝남 |
| 다음 사용자 입력 | DB 대화 기록을 읽고 새 State·새 예산으로 실행. AI가 이어갈 내용·새 요청을 판단 |
| 취소·시간 초과·실행 오류 | 취소 또는 실패 끝 행 저장 → INT-07 |
| 취소 대상 실행 없음·이미 종료 | 추가 행 없이 202 |

새 질문에서 이전 내부 State·도구 결과·중단 지점을 복원하지 않는다.
실행 중 중복 방지는 단일 프로세스의 State와 Task로 처리하며 DB의 끝 행 제약도 유지한다.
먼저 커밋한 끝 행을 보존한다. 종료 중의 늦은 실행·취소는 새 끝 행으로 덮어쓰지 않는다.

INT-01 원본 입력은 `results`의 `run_request` 기록에 둔다. 화면 문맥은 기존
`request.constraints.preferred`에 표시하고 모델의 목적 파악에 제공한다.
업무 자료·판단·응답의 원본은 기존 State이며 별도 요청 캐시를 두지 않는다.

## 3. 보고서 생성

`requestId`는 비어 있지 않은 문자열, `dongCodes`는 중복 없는 10자리 코드의 비어 있지 않은 목록이다.
입력 오류는 빈 400이다. 정상 요청은 항상 빈 202로 접수하고, 자료 조회·생성·저장은 뒤에서 실행한다.
기존 실행이 있어도 접수한다. 409 거절·204 생략·시점 비교는 제거했다.
같은 요청을 다시 보내도 생성한다. 동별 생성 병렬 수는 모든 보고서 요청이 공유하는
`SETTINGS_REPORT_CONCURRENCY`로 제한한다(기본 2).

AI가 `region_insight_report`에 직접 UPSERT한다. `result_updated_at`은 조회한 분석 결과의
수정 시각을 기록하는 기존 컬럼으로 남기며, 생성 생략이나 저장 허용 여부 판단에는 쓰지 않는다.
부분 보고서의 미완성 항목은 NULL이다. 생성·검토·재처리 규칙은
[보고서 생성 흐름](temp/analysis-report-workflow.md)을 따른다.

| INT-08 필드 | 집계 기준 |
| --- | --- |
| requestId·month | 접수 입력 그대로 |
| savedCount | 이번 요청에서 DB 커밋이 성공한 동 수. 부분 보고서도 커밋됐으면 포함 |
| failedDongCodes | 자료 없음·생성/저장 오류 등으로 커밋하지 못한 동 목록 |

모든 동의 처리·저장 재시도가 끝난 뒤 알린다. 집계 원본은 동별 State의 저장 성공 기록이다.
보고서별 완료 상태와 저장 여부는 구분하며, 전부 실패한 요청도 0과 실패 목록으로 알린다.
같은 동·월 요청이 겹치면 마지막으로 저장한 결과가 남는다. 시점에 따른 거절은 없다.

## 4. 실행 시간·알림 실패

대화와 보고서는 [공통 실행 설정](../README.md#설치설정)을 사용한다.
현재 일반 실행 300초, 종료 응답 최대 30초, LLM 요청 30초다.
사용자 요청은 접수 준비의 DB 읽기 시간을 포함해 전체 330초 안에 끝 행을 커밋하도록
남은 시간으로 실행을 제한하고 마지막 3초를 커밋에 남긴다. 진행·종료 행 DB 저장도 최대 3초다.
취소는 추가 모델 호출 없이 취소 행을 저장한다. BE 제안값은 execution-limit=330초,
grace-period=5초, unresponsive-after=40초, cancel-wait=3초다.
5초는 AI 실행을 늘리는 시간이 아니라 BE의 추가 여유로 사용한다.
설정을 바꾸면 `runtime_timeout+30`, `llm_timeout+10`으로 BE 값을 다시 전달한다.

보고서는 동별 업무 노드의 누적 활성 시간에 일반 실행 한도를 적용한다.
동별 재처리는 남은 예산을 이어 쓰며, 실행 자리 대기·최초 분석 결과 확인·최종 DB 저장과
완료 알림 시간은 이 예산에 포함하지 않는다. 보고서 요청 전체의 완료 기한은 별도로 제한하지
않으며, INT-08까지 걸리는 시간은 동 수·대기열·저장 재시도에 따라 달라진다.

알림은 커밋 뒤 전송하며 timeout은 기본 1초다. 연결 장애·timeout·5xx만 같은 본문으로
즉시 1회 추가 시도한다. 4xx(404 포함)·잘못된 204 응답은 재시도하지 않는다.
실패는 State의 notification 기록과 서버 로그에 남긴다. 알림만 실패해도 저장된 결과를
삭제하거나 모델을 다시 실행하지 않는다. 영속 전송 큐·재시작 후 자동 재알림은 없다.
로그의 보고서 파일은 재개용 체크포인트가 아니다.

## 5. 배포와 남은 연결

설정·컨테이너 명령은 [AI README](../README.md), 검증 방법은 [API 왕복 검증](api-roundtrip.md)을 따른다.

- BE: INT-01·02 호출, INT-07·08 수신과 토큰·시간 설정을 실제 AI와 검증해야 한다.
- DB: eumi_ai 보고서 INSERT·UPDATE 부여는 BE 측 변경 예정이다. 기존 부분 NULL 금지 제약은 AI에서 변경하지 않는다.
- AI의 시점 비교를 제거했으므로 분석 갱신과 생성이 겹치면 이전 자료로 작성한 보고서가 나중에 저장될 수 있다. 기존 DB 뷰의 result_updated_at 일치 조건은 AI 범위 밖이라 그대로이며, 화면에서 해당 결과가 숨겨질 수 있다.
- DB 장애·프로세스 강제 종료에서는 끝 행 커밋을 보장할 수 없다. 동기 작업이 이벤트 루프를 막는 동안에는 timeout 처리도 지연될 수 있다.
- 40초는 LLM timeout에 근거한 BE 설정이다. 긴 도구 작업에는 별도 주기적 진행 알림이 없으므로 실제 데이터로 진행 행 간격을 확인해야 한다.
- 여러 워커·재시작 복구는 지원하지 않는다. Docker는 1 worker로 실행한다.
- 실제 모델·PostgreSQL·BE 왕복과 2GB 메모리 상한 검증은 배포 환경에서 수행한다.
