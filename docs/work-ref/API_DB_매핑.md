# API DB 매핑

최신 물리 객체와 화면 작업 ID를 연결한다. 인증 회원·기관·기록자·관리번호는 서버가 결정한다. 응답 DTO는 DB 컬럼을 그대로 공개하는 구조가 아니며 연령·상태·최근 기록일·편집 가능 여부는 계산값이다.

| API | 요청 | 작업 | DB 객체 |
| --- | --- | --- | --- |
| API-01 | GET /api/auth/me | A1 | public.member, public.organization, public.v_sido, public.v_sigungu, public.spring_session |
| API-02 | POST /api/auth/logout | A1 | public.spring_session, public.spring_session_attributes |
| API-03 | POST /api/agent/runs | AI1 | Spring 메모리 실행 저장소, public.ai_conversation, public.ai_conversation_turn |
| API-03-S1 | GET /api/agent/runs/{runId}/events | AI1 | Spring 메모리 실행 저장소 |
| API-03-S2 | GET /api/agent/runs/{runId} | AI1 | Spring 메모리 실행 저장소, public.ai_conversation_turn |
| API-04 | GET /api/organizations | A2 | public.organization, public.v_sido, public.v_sigungu |
| API-05 | POST /api/signup/email-verifications | A2 | public.organization, public.member, public.email_verification |
| API-06 | POST /api/signup/email-verifications/verify | A2 | public.email_verification |
| API-07 | POST /api/members | A2 | public.member, public.email_verification |
| API-08 | POST /api/auth/login | A1 | public.member, public.organization, public.spring_session |
| API-09 | POST /api/auth/temp-password | A3 | public.member, public.spring_session |
| API-10 | GET /api/analysis/sigungus/{sigunguCode}/months | D1 | public.region_result |
| API-11 | GET /api/analysis/dongs/{dongCode}/insight | D2 | public.v_region_insight, public.region_result, public.region_insight_report |
| API-12 | GET /api/analysis/dongs/{dongCode}/report | D2 | public.region_result, public.region_insight_report |
| API-13 | GET /api/resources | W1 | public.v_resource_summary |
| API-14 | GET /api/resources/{resourceId} | W2 | public.v_resource_summary |
| API-15 | PUT /api/resources/{resourceId} | W3 | public.welfare_resource, public.member, public.dim_region |
| API-16 | DELETE /api/resources/{resourceId} | W2 | public.welfare_resource |
| API-17 | POST /api/resources | W3 | public.welfare_resource, public.member, public.dim_region |
| API-18 | POST /api/resources/document-extractions | P1 | 일시 업로드 파일, FastAPI 추출 모듈 |
| API-19 | GET /api/cases | C1 | public.v_case_summary, public.case_manager |
| API-20 | GET /api/cases/{caseId} | C2 | public.v_case_summary, public.case_manager, public.member |
| API-21 | POST /api/cases/duplicate-check | C3 | public.case_record, public.case_manager |
| API-22 | POST /api/cases | C3 | public.organization, public.case_record, public.case_manager, public.next_management_no |
| API-23 | PUT /api/cases/{caseId} | C3 | public.case_record, public.case_manager, public.member |
| API-24 | DELETE /api/cases/{caseId} | C2 | public.case_record, public.case_manager, public.consultation |
| API-25 | GET /api/cases/{caseId}/consultations | C4 | public.consultation, public.case_record, public.case_manager, public.member |
| API-26 | GET /api/cases/{caseId}/consultations/{consultationId} | C4 | public.consultation, public.case_record, public.case_manager, public.member |
| API-27 | POST /api/cases/{caseId}/consultations | C4 | public.consultation, public.case_record, public.case_manager |
| API-28 | PUT /api/cases/{caseId}/consultations/{consultationId} | C4 | public.consultation, public.case_record, public.case_manager |
| API-29 | DELETE /api/cases/{caseId}/consultations/{consultationId} | C4 | public.consultation, public.case_record, public.case_manager |
| API-30 | GET /api/members/me | M1 | public.member, public.organization, public.v_sido, public.v_sigungu |
| API-31 | PATCH /api/members/me | M1 | public.member |
| API-32 | PUT /api/members/me/password | A3 | public.member, public.spring_session |
| API-33 | GET /api/members/me/withdrawal | M3 | public.member, public.case_manager, public.v_case_summary, public.v_resource_summary, public.ai_conversation |
| API-34 | POST /api/members/me/withdrawal | M3 | public.organization, public.member, public.case_record, public.case_manager, public.welfare_resource, public.v_resource_summary, public.ai_conversation, public.ai_message, public.spring_session |
| API-35 | GET /api/members/me/resources | M2 | public.v_resource_summary |
| API-36 | GET /api/members/me/conversations | AI2 | public.v_conversation_summary |
| API-37 | GET /api/members/me/conversations/{conversationId} | AI2 | public.ai_conversation, public.ai_conversation_turn |
| API-38 | DELETE /api/members/me/conversations/{conversationId} | AI2 | public.ai_conversation, public.ai_conversation_turn |
| API-39 | GET /api/regions/sidos | G1 | public.v_sido |
| API-40 | GET /api/regions/sidos/{sidoCode}/sigungus | G1 | public.v_sigungu |
| API-41 | GET /api/regions/sigungus/{sigunguCode}/dongs | G1 | public.dim_region |
| API-42 | GET /api/organizations/me/members | G1 | public.member |
| SYS-01 | GET /api/auth/csrf | G1 | Spring Security CSRF 토큰 저장소 |
| SYS-02 | GET /api/health | G1 | 없음 |

## 주요 필드 매핑

| DTO 필드 | 최신 DB 또는 계산 | 주의 |
| --- | --- | --- |
| dongCode | dim_region.adm_cd10 | adm_cd8과 혼용 금지 |
| background.score/stage | region_result.bg_score/bg_grade | 분석 등급 1~5 |
| behavior.score/stage | region_result.bh_score/bh_grade | 분석 등급 1~5 |
| riskGrade | region_result.risk_grade | 종합 단계 |
| insight.summary/generatedAt | region_insight_report.summary_lines/generated_at | 없으면 insight=null |
| report | region_insight_report.report + generated_at | 조회 시 생성 안 함 |
| manualStatus | welfare_resource.manual_status | 폼 편집용 저장값 |
| status/autoEnded | v_resource_summary 계산 | 종료일은 한국 날짜 기준 |
| age/ageGroup/lastRecordedAt | v_case_summary 계산 | 새 연령 경계 적용 |
| progressSteps/blocks/completedAt | ai_conversation_turn.progress_steps/answer_blocks/completed_at | 완료 turn만 저장 |
| mustChangePassword | member.temp_password_expires_at 및 제한 세션 | JWT 주장 없음 |
| resourceTransfers | 진행 중 담당 자원 집합과 후임자 검증 | 추가 DB 테이블 없음 |
