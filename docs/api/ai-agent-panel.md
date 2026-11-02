# AI 에이전트 패널 계약 (A 방식, 2026-11-02 확정)

BE가 질문을 저장하고, AI(FastAPI)가 진행 단계와 답변을 DB(`ai_message`)에 직접 저장하고, 화면은 1초마다 새 행을 조회한다. SSE는 쓰지 않는다.
API 형식은 `openapi.json` 2.3.0의 API-03·03-S1·03-S2·36~38, DB는 `db/migration/V20261102_02__ai_message.sql`이 기준이다.

## 1. 구성 요소

| 구성 요소 | 하는 일 |
|---|---|
| FE | 질문을 보내고, 1초마다 마지막으로 받은 행 이후를 조회해 붙인다. 끝 행(완료·실패·취소)을 받으면 조회를 멈춘다. 중단 버튼으로 취소를 요청한다 |
| BE (Spring) | 로그인·대화 소유자 확인, 질문의 개인정보를 가려 질문 행 저장, AI에 실행·취소 요청, 조회 API 제공. AI가 응답하지 않을 때만 실패·취소 행을 대신 쓴다 |
| AI (FastAPI) | 대화 ID와 질문 행 ID를 받아 DB에서 이전 대화와 질문을 읽고, 진행·완료·실패·취소 행을 행마다 커밋해 저장한다. BE로 결과를 보내지 않는다 |
| DB | 행을 순서대로 쌓는다. 한 질문에 끝 행은 하나만 받는다. 끝 행이 들어오면 대화의 실행 종료 일시와 삭제 예정일을 갱신한다(트리거) |

- 실행 ID = 대화 ID. 한 대화에서 실행은 동시에 하나다.
- 질문 행은 BE(`eumi_app`)가, AI 행은 AI(`eumi_ai`)가 쓴다. AI가 응답하지 않을 때의 실패·취소 행만 BE가 `role='AI'`로 대신 쓴다.
- 단계 하나 = 행 하나. AI는 단계를 시작할 때 진행 행을 한 번 저장하고, 단계별 완료 행은 두지 않는다. 다음 단계의 진행 행이나 끝 행이 들어오면 앞 단계가 끝난 것으로 본다.
- AI는 같은 대화의 이전 기록을 **전체** 읽는다 (최근 몇 개로 자르지 않음). 길어서 문제가 되면 그때 범위를 줄인다.
- AI 서버는 인증이 없고 Nginx에 열지 않는다. BE만 내부 네트워크로 부른다.
- 화면 문맥(screen)은 보내지 않는다. 실패 원인은 저장하지 않는다.

## 2. ai_message 한 행

| 컬럼 | API 필드 | 값 |
|---|---|---|
| message_id | messageId | 행 식별자이자 순서. 다음 조회의 after |
| conversation_id | (경로) | 대화 ID |
| question_id | questionId | AI 행이 답하는 질문 행의 message_id. 질문 행은 null |
| role | role | `Member` / `AI` (글자 그대로, DB CHECK) |
| status | status | `질문` / `진행` / `완료` / `실패` / `취소` (글자 그대로, DB CHECK) |
| content | content | 질문 행: 질문, 진행 행: 단계 이름, 완료 행: 최종 답변, 실패·취소 행: null |
| details | details | 진행 행의 단계 상세 설명. 질문 행은 null |
| artifacts | artifacts | 시각화 결과(표·그래프) JSON. 있을 때만. 형식은 AI·FE가 합의 (정해지기 전 FE는 무시) |
| created_at | createdAt | 저장 일시 |

예: 질문 두 번, 두 번째는 사용자가 중단

| messageId | role | status | questionId | content |
|---|---|---|---|---|
| 101 | Member | 질문 | | 이 동의 위험이 왜 올랐어? |
| 102 | AI | 진행 | 101 | 질문 이해 |
| 103 | AI | 진행 | 101 | 지표 조회 |
| 104 | AI | 완료 | 101 | 행동 이상 점수가 오른 이유는 … |
| 105 | Member | 질문 | | 주변 동과 비교해 줘 |
| 106 | AI | 진행 | 105 | 비교 자료 조회 |
| 107 | AI | 취소 | 105 | |

DB가 막는 것: 같은 question_id에 끝 행 두 개(부분 UNIQUE), 이미 끝난 질문에 들어오는 AI 행(트리거), 다른 대화의 질문을 가리키는 행(복합 FK), role·status 오타(CHECK). 막힐 때 오류는 SQLSTATE 23505(끝난 질문) 또는 23514(CHECK)·23503(FK).

## 3. API

| 구간 | 요청 | 하는 일 |
|---|---|---|
| FE → BE | `POST /api/agent/questions` (API-03) | `{conversationId \| null, question}` → 202 `{conversationId, questionId}`. 끝 행이 없는 질문이 있으면 409 `RUN_ALREADY_ACTIVE`, 남의·만료 대화 404 |
| FE → BE | `GET /api/agent/conversations/{id}/messages?after=` (API-03-S1) | after보다 큰 행을 오름차순으로 `{messages: [...]}`. 실행 중 1초마다, 대화를 열 때 after=0 |
| FE → BE | `POST /api/agent/conversations/{id}/cancel` (API-03-S2) | 204. 이미 끝났어도 204 |
| FE → BE | `GET /api/members/me/conversations` (API-36) | 대화 목록 (`v_conversation_summary`, 질문 수는 실패·취소 포함) |
| FE → BE | `GET /api/members/me/conversations/{id}` (API-37) | 대화 전체, `messages`는 API-03-S1과 같은 형식 |
| FE → BE | `DELETE /api/members/me/conversations/{id}` (API-38) | 실행 중이면 취소 요청 뒤 삭제, 메시지는 CASCADE |
| BE → AI | `POST /internal/agent/runs` (INT-01) | `{conversationId, questionId}` → 202 접수만 하고 뒤에서 실행. 같은 대화가 실행 중이면 409 |
| BE → AI | `POST /internal/agent/runs/{conversationId}/cancel` (INT-02) | 실행을 멈추고 취소 행 저장 |
| BE → AI | `GET /internal/agent/runs/{conversationId}` (INT-03) | `{running, questionId}` 실행 상태 |

## 4. 상황별 동작

**첫 질문**: FE 질문(대화 ID 없음) → BE가 대화 행 + 질문 행을 한 트랜잭션으로 저장(대화 행의 실행 종료 일시·삭제 예정일은 기본값) → 커밋 뒤 INT-01 → 202 → FE는 `after=questionId`로 1초마다 조회 → AI는 단계마다 진행 행을 쓰고 커밋 → 완료 행(답변, artifacts) → FE는 끝 행에서 멈춤.

**이어서 질문**: FE가 대화 ID를 넣어 보냄(실행 중에는 보내기 버튼을 막음) → BE는 대화 행 `FOR UPDATE`, 소유자 확인, 끝 행 없는 질문이 있으면 409 → 나머지는 첫 질문과 같다. 이전 대화는 AI가 DB에서 직접 읽는다.

**새로고침·화면 이탈·네트워크 끊김**: 다시 들어오면 after=0으로 전체를 다시 그리고, 마지막 질문에 끝 행이 없으면 조회를 이어 간다. 조회가 한 번 실패해도 다음 조회가 마지막 id부터 이어 받는다. 401이면 로그인 화면.

**사용자 중단**: FE cancel → BE가 소유자 확인 후 INT-02 → AI가 멈추고 취소 행 저장 → FE는 취소 행에서 멈춤. AI가 정해진 시간 안에 응답하지 않으면 BE가 취소 행을 쓴다. 취소와 완료가 겹치면 먼저 저장된 끝 행만 남는다(완료가 먼저면 화면에 답변이 보인다).

**실패·시간 초과·AI 불량**

| 상황 | 처리 |
|---|---|
| AI 내부 오류 | AI가 실패 행 저장. FE는 실패 안내 |
| 실행 시간 초과 | AI가 제한 시간에 멈추고 실패 행 저장 |
| AI가 응답 없음 | 새 행이 정해진 시간 동안 없으면 BE가 조회를 처리할 때 INT-03으로 상태 확인 |
| AI 불량 | 실행 중이 아니고 끝 행이 없으면 BE가 같은 questionId로 INT-01을 한 번만 다시 요청 |
| 그래도 끝나지 않음 | 질문 시각 + AI 실행 제한 + 여유 시간이 지나면 BE가 실패 행. 그 뒤 AI의 늦은 행은 DB가 거부 |

**기록과 삭제**: 마이페이지 목록은 `v_conversation_summary`(첫 질문, 질문 수, 실행 종료 일시, 보관 기간 지난 대화 제외). 대화를 열면 지난 진행 단계·실패·취소까지 그대로 보인다. 보관은 실행 종료일(서울) + 3개월, 매일 한 번 만료 대화 삭제, 탈퇴 시 모두 삭제.

## 5. 아직 정할 것 (김민준, 11/3까지)

- 시간 값 4개: AI 실행 제한, BE 여유 시간, '응답 없음'으로 보는 시간, 취소 응답 대기 → BE 설정 `eumi.ai.*`
- artifacts 형식 (FE와 함께)
