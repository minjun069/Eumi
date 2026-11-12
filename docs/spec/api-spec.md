# 이음이 API 명세

- 판: 2.6.0 (2026-11-11, 11/6 초안 · 11/9 INT-06 · API-18 삭제 · 11/9 AI-a 반영 · 11/10 AI-b 반영: API-11 · 12 새 형식, INT-05 dongCodes, INT-08 · 11/10 A3 · M3 구현: API-09 · 33 · 34 · 11/10 C4: API-20 updatedAt, API-23 CaseUpdateInput · 11/11 A2 구현: API-04~07 · 11/11 보고서 일부 저장: API-12 찬 칸만, INT-05 · 08 · 11/12 문서 정리: API-03 · 03-S1 · 03-S2 운영 http, API-11 · 12 배포 상태, Tableau 워크북 하나)
- 원본: 이 파일이 기준이다. 엑셀(`이음이_API_명세표.xlsx`)은 `python docs/spec/build_xlsx.py`로 이 파일에서 만든다. 엑셀만 따로 고치지 않는다.
- API 형식의 기준은 `docs/api/openapi.json`, 내부 연동은 `docs/api/ai-agent-panel.md` · `docs/api/insight-report.md`다. 계약이 바뀌면 같은 MR에서 이 문서도 고친다.
- 형식: [docs/spec/README.md](README.md)의 'md 형식'

[[_TOC_]]

## API 목록

- 제목: 이음이 API 명세표
- 요약: API 2.6.0  45개 작업 (구현 45 · 예정 0)  * 필수 입력  기본 경로 /api
- 출처: eumi/docs/api/openapi.json 2.6.0 · eumi DB 및 인증 결정 · AI 패널(API-03·03-S1·03-S2·36~38)은 2026-11-02 A 방식 결정 · 질문 마스킹 범위는 2026-11-03 (ai-agent-panel.md 6절) · 인사이트 보고서 연동(INT-04 · 05)과 API-11·12 변경은 2026-11-06 초안 (A 방식, 문서 '이음이 API 명세 — 구현 현황과 AI 연동') · 보고서 저장 INT-06은 2026-11-09 삭제 (AI가 DB에 직접 저장) · AI 대화 패널 연결(API-03 화면 문맥, INT-01 messageId, INT-07, INT-03 삭제)은 2026-11-09 openapi 2.3.4 · ai-agent-panel.md · 인사이트 보고서 연결(API-11 · 12 새 형식, INT-05 dongCodes · 202 본문 없음, INT-08)은 2026-11-10 openapi 2.4.0 · insight-report.md 확정 · 보고서 일부 저장(API-12 찬 칸만 0~3개, null 가능)은 2026-11-11 openapi 2.6.0 · V20261111_01

### API-01 로그인 상태와 메뉴 프로필 조회
- 페이지 범위: /login·공통
- 요청 경로: GET /api/auth/me
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json memberApi_getMenuProfile_Success<br>memberId*:integer(int64); name*:string; orgName*:string; title*:string 또는 null; jurisdictionSidoCode*:string; jurisdictionSigunguCode*:string; mustChangePassword*:boolean
- 구현 (11/6): 구현

### API-02 로그아웃
- 페이지 범위: /login·공통
- 요청 경로: POST /api/auth/logout
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 없음
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-03 AI 질문 등록<br>신규 설계
- 페이지 범위: 공통 Agent 패널
- 요청 경로: POST /api/agent/questions
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json AgentQuestionRequest<br>conversationId*:string(uuid) 또는 null; question*:string(1~4000자); context:ScreenContext{dongCode:string(숫자 10자리); month:string(YYYY-MM)} (선택, 위험 탐색 · 읍면동 화면에서 보고 있는 동 · 월, {}와 생략 허용, 저장 안 함, ai-agent-panel.md 3-1)<br>저장 전 이름·생년월일 표지 값과 이메일·휴대전화(하이픈형)만 가림 · 그 밖의 식별정보는 남을 수 있음(완전한 비식별화 아님) · 질문 본문은 로그에 남기지 않음 · 범위는 ai-agent-panel.md 6절
- 응답 형식: 202 application/json AgentQuestionCreated_Success<br>conversationId*:string(uuid); questionId*:integer(int64)<br>첫 질문이면 대화 생성 · 질문 행 저장, 커밋 뒤 AI 실행 요청(INT-01)<br>400 INVALID_JSON: context의 모르는 필드 · 문자열이 아닌 값 · 400 VALIDATION_ERROR: context 형식 오류<br>409 RUN_ALREADY_ACTIVE: 끝 행이 없는 질문이 있음
- 구현 (11/6): 구현 (11/11부터 운영 http 모드, GMS gpt-6-luna · 화면 문맥 context는 BE 11/9 · FE 11/11)

### API-03-S1 AI 대화 메시지 조회<br>신규 설계
- 페이지 범위: 공통 Agent 패널
- 요청 경로: GET /api/agent/conversations/{conversationId}/messages
- 요청 형식: 인증 SESSION 쿠키<br>path conversationId*:string(uuid); query after:integer(int64)<br>본문 없음
- 응답 형식: 200 application/json AgentMessages_Success<br>messages*:AgentMessage[]<br>AgentMessage: messageId*:integer(int64); questionId*:integer(int64) 또는 null; role*:string(Member·AI); status*:string(질문·진행·완료·실패·취소); content*:string 또는 null(질문 행은 등록 당시 마스킹 처리 결과); details*:string 또는 null; artifacts*:JSON 또는 null(Tableau · 표 · 그래프, 형식과 FE 표시 규칙은 ai-agent-panel.md 2-1); createdAt*:string(date-time)<br>after보다 큰 messageId만 오름차순 · 실행 중 1초마다, 대화를 열 때 after=0<br>새 행이 응답 없음 기준 동안 없으면 BE가 같은 messageId로 INT-01을 질문당 1번 다시 보냄 · 질문 시각 + 실행 제한 + 여유가 지나면 BE가 실패 행
- 구현 (11/6): 구현 (11/11부터 운영 http 모드)

### API-03-S2 AI 실행 중단<br>신규 설계
- 페이지 범위: 공통 Agent 패널
- 요청 경로: POST /api/agent/conversations/{conversationId}/cancel
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path conversationId*:string(uuid)<br>본문 없음
- 응답 형식: 204 본문 없음<br>취소 행은 API-03-S1로 받음 · 이미 끝났으면 아무것도 하지 않음<br>AI가 정해진 시간 안에 응답하지 않으면 BE가 취소 행을 대신 저장
- 구현 (11/6): 구현 (11/11부터 운영 http 모드)

### API-04 소속기관 검색
- 페이지 범위: /signup
- 요청 경로: GET /api/organizations
- 요청 형식: 인증 공개<br>query keyword:string<br>본문 없음
- 응답 형식: 200 application/json signupApi_searchOrganizations_Success
- 구현 (11/6): 구현 (11/11)

### API-05 인증 메일 발송
- 페이지 범위: /signup
- 요청 경로: POST /api/signup/email-verifications
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 application/json SendVerificationRequest<br>orgId*:integer(int64); email*:string(email)
- 응답 형식: 201 application/json signupApi_sendVerificationEmail_Success<br>expiresAt*:string(date-time)
- 구현 (11/6): 구현 (11/11)

### API-06 인증 코드 확인
- 페이지 범위: /signup
- 요청 경로: POST /api/signup/email-verifications/verify
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 application/json VerifyCodeRequest<br>email*:string(email); code*:string
- 응답 형식: 200 application/json signupApi_verifyCode_Success<br>verificationToken*:string
- 구현 (11/6): 구현 (11/11)

### API-07 회원가입
- 페이지 범위: /signup
- 요청 경로: POST /api/members
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 application/json SignupRequest<br>verificationToken*:string; orgId*:integer(int64); email*:string(email); name*:string; password*:string(password); title:string 또는 null; phone:string 또는 null
- 응답 형식: 201 application/json signupApi_signup_Success<br>memberId*:integer(int64)
- 구현 (11/6): 구현 (11/11)

### API-08 로그인
- 페이지 범위: /login·공통
- 요청 경로: POST /api/auth/login
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 application/json LoginRequest<br>email*:string(email); password*:string(password)
- 응답 형식: 200 application/json authApi_login_Success<br>user*:LoginUser
- 구현 (11/6): 구현

### API-09 임시 비밀번호 발급
- 페이지 범위: /password/find·/my/password
- 요청 경로: POST /api/auth/temp-password
- 요청 형식: 인증 공개 · CSRF 필수<br><br>본문 application/json TempPasswordRequest<br>email*:string(email); name*:string
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현 (11/10)

### API-10 적재된 월 목록 조회
- 페이지 범위: /risk
- 요청 경로: GET /api/analysis/sigungus/{sigunguCode}/months
- 요청 형식: 인증 SESSION 쿠키<br>path sigunguCode*:string<br>본문 없음
- 응답 형식: 200 application/json analysisApi_getLoadedMonths_Success<br>months*:string[]
- 구현 (11/6): 구현

### API-11 읍면동 인사이트 조회
- 페이지 범위: /risk?dong=…
- 요청 경로: GET /api/analysis/dongs/{dongCode}/insight
- 요청 형식: 인증 SESSION 쿠키<br>path dongCode*:string; query month*:string<br>본문 없음
- 응답 형식: 200 application/json analysisApi_getDongInsight_Success<br>dongCode*:string; dongName*:string; sigunguCode*:string; sigunguName*:string; month*:string; background*:RiskValue; behavior*:RiskValue; insight*:object 또는 null; riskGrade*:integer<br>insight = {summary*:string[] (최신 보고서의 quick_insight 한 개, 줄바꿈으로 나누지 않음); generatedAt*:string(date-time)} 또는 null · 최신 보고서(result_updated_at = 결과 updated_at)만 · quick_insight가 없으면 insight null · 결과 없음 404
- 구현 (11/6): 구현 · 새 칸(quick_insight) 읽기는 11/10 (응답 모양 유지)

### API-12 인사이트 보고서 조회
- 페이지 범위: /risk?dong=…
- 요청 경로: GET /api/analysis/dongs/{dongCode}/report
- 요청 형식: 인증 SESSION 쿠키<br>path dongCode*:string; query month*:string<br>본문 없음
- 응답 형식: 200 application/json analysisApi_getInsightReport_Success<br>report*:object 또는 null<br>report = {quickInsight*:string(1~500자) 또는 null; graphs*:[{sheet*:string(EmbedDetailV01~V08); description*:string(1~1000자) 또는 null}] 0~3개(graph_n이 있는 칸만 graph_1~3 순서, 빈 칸은 건너뜀); generatedAt*:string(date-time)} 또는 null · AI는 검토를 통과한 칸만 저장(2.6.0) · 허용 밖 시트는 그 그래프만 빼고 경고 로그 · 퀵 인사이트와 그래프가 모두 없거나 옛 보고서(결과 시각 불일치)면 null · 결과 없음 404 · 조회가 생성을 실행하지 않음
- 구현 (11/6): 구현 (11/12 2.6.0 일부 표시, V20261111_01과 함께 배포)

### API-13 복지자원 목록 조회
- 페이지 범위: /resources
- 요청 경로: GET /api/resources
- 요청 형식: 인증 SESSION 쿠키<br>query sidoCode:string; query sigunguCode:string; query dongCode:string; query ageGroup:string; query gender:string; query capacityMin:integer; query capacityMax:integer; query resourceName:string; query managerName:string; query sort:string; query direction:string; query page:integer; query size:integer<br>본문 없음
- 응답 형식: 200 application/json resourceApi_searchResources_Success<br>totalCount*:integer; page*:integer; size*:integer; totalPages*:integer; items*:ResourceListItem[]
- 구현 (11/6): 구현

### API-14 복지자원 상세 조회
- 페이지 범위: /resources/:id
- 요청 경로: GET /api/resources/{resourceId}
- 요청 형식: 인증 SESSION 쿠키<br>path resourceId*:integer(int64)<br>본문 없음
- 응답 형식: 200 application/json resourceApi_getResource_Success<br>resourceId*:integer(int64); resourceName*:string; operatingOrgName*:string; target*:string; capacity*:integer; sigunguName*:string; dongName*:string 또는 null; periodStart*:string(date); periodEnd*:string(date); fee*:integer; status*:string; supportAgeGroups*:string[]; supportGender*:string; sidoCode*:string; sidoName*:string; sigunguCode*:string; dongCode*:string 또는 null; autoEnded*:boolean; actualParticipants*:integer 또는 null; supportContent*:string 또는 null; applyMethod*:string 또는 null; manager*:object; editable*:boolean; manualStatus*:string<br>manager.withdrawn*:boolean · 종료+탈퇴만 name=퇴사자
- 구현 (11/6): 구현

### API-15 복지자원 수정
- 페이지 범위: /resources/new·/:id/edit
- 요청 경로: PUT /api/resources/{resourceId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path resourceId*:integer(int64)<br>본문 application/json ResourceInput<br>resourceName*:string; operatingOrgName*:string; target*:string; supportAgeGroups*:string[]; supportGender*:string; sigunguCode*:string; dongCode:string 또는 null; periodStart*:string(date); periodEnd*:string(date); fee*:integer; status*:string; managerMemberId*:integer(int64); capacity*:integer; actualParticipants:integer 또는 null; supportContent:string 또는 null; applyMethod:string 또는 null
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-16 복지자원 삭제
- 페이지 범위: /resources/:id
- 요청 경로: DELETE /api/resources/{resourceId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path resourceId*:integer(int64)<br>본문 없음
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-17 복지자원 등록
- 페이지 범위: /resources/new·/:id/edit
- 요청 경로: POST /api/resources
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json ResourceInput<br>resourceName*:string; operatingOrgName*:string; target*:string; supportAgeGroups*:string[]; supportGender*:string; sigunguCode*:string; dongCode:string 또는 null; periodStart*:string(date); periodEnd*:string(date); fee*:integer; status*:string; managerMemberId*:integer(int64); capacity*:integer; actualParticipants:integer 또는 null; supportContent:string 또는 null; applyMethod:string 또는 null
- 응답 형식: 201 application/json resourceApi_createResource_Success<br>resourceId*:integer(int64)
- 구현 (11/6): 구현

### API-19 사례자 목록 조회
- 페이지 범위: /cases
- 요청 경로: GET /api/cases
- 요청 형식: 인증 SESSION 쿠키<br>query sidoCode:string; query sigunguCode:string; query dongCode:string; query ageGroup:string; query gender:string; query registeredFrom:string(date); query registeredTo:string(date); query recordedFrom:string(date); query recordedTo:string(date); query keyword:string; query sort:string; query direction:string; query page:integer; query size:integer<br>본문 없음
- 응답 형식: 200 application/json caseApi_searchCases_Success<br>totalCount*:integer; page*:integer; size*:integer; totalPages*:integer; items*:CaseListItem[]
- 구현 (11/6): 구현

### API-20 사례자 정보 조회
- 페이지 범위: /cases/:id
- 요청 경로: GET /api/cases/{caseId}
- 요청 형식: 인증 SESSION 쿠키<br>path caseId*:integer(int64)<br>본문 없음
- 응답 형식: 200 application/json caseApi_getCase_Success<br>caseId*:integer(int64); managementNo*:string; name*:string; age*:integer; ageGroup*:string; gender*:string; sidoName*:string; sigunguName*:string; dongName*:string; firstRegisteredAt*:string(date); lastRecordedAt*:string(date) 또는 null; birthDate*:string(date); sidoCode*:string; sigunguCode*:string; dongCode*:string; managers*:MemberOption[]; updatedAt*:string(date-time)
- 구현 (11/6): 구현

### API-21 사례자 중복 확인
- 페이지 범위: /cases/new·/:id/edit
- 요청 경로: POST /api/cases/duplicate-check
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json DuplicateCheckRequest<br>name*:string; birthDate*:string(date); excludeCaseId:integer(int64) 또는 null
- 응답 형식: 200 application/json caseApi_checkDuplicate_Success<br>duplicates*:object[]
- 구현 (11/6): 구현

### API-22 사례자 정보 등록
- 페이지 범위: /cases/new·/:id/edit
- 요청 경로: POST /api/cases
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json CaseInput<br>name*:string; birthDate*:string(date); gender*:string; dongCode*:string; firstRegisteredAt*:string(date); managerMemberIds*:integer(int64)[]
- 응답 형식: 201 application/json caseApi_createCase_Success<br>caseId*:integer(int64); managementNo*:string
- 구현 (11/6): 구현

### API-23 사례자 정보 수정
- 페이지 범위: /cases/new·/:id/edit
- 요청 경로: PUT /api/cases/{caseId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path caseId*:integer(int64)<br>본문 application/json CaseUpdateInput<br>name*:string; birthDate*:string(date); gender*:string; dongCode*:string; firstRegisteredAt*:string(date); managerMemberIds*:integer(int64)[]; updatedAt*:string(date-time)
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-24 사례자 정보 삭제
- 페이지 범위: /cases/:id
- 요청 경로: DELETE /api/cases/{caseId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path caseId*:integer(int64)<br>본문 없음
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-25 상담 목록 조회
- 페이지 범위: 상담 모달
- 요청 경로: GET /api/cases/{caseId}/consultations
- 요청 형식: 인증 SESSION 쿠키<br>path caseId*:integer(int64)<br>본문 없음
- 응답 형식: 200 application/json consultationApi_getConsultations_Success
- 구현 (11/6): 구현

### API-26 상담 내용 조회
- 페이지 범위: 상담 모달
- 요청 경로: GET /api/cases/{caseId}/consultations/{consultationId}
- 요청 형식: 인증 SESSION 쿠키<br>path caseId*:integer(int64); path consultationId*:integer(int64)<br>본문 없음
- 응답 형식: 200 application/json consultationApi_getConsultation_Success<br>consultationId*:integer(int64); consultedAt*:string(date); purpose*:string; category*:string; categoryEtc*:string 또는 null; recorderName*:string; content*:string; recorderMemberId*:integer(int64)
- 구현 (11/6): 구현

### API-27 상담 등록
- 페이지 범위: 상담 모달
- 요청 경로: POST /api/cases/{caseId}/consultations
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path caseId*:integer(int64)<br>본문 application/json ConsultationInput<br>consultedAt*:string(date); purpose*:string; category*:string; categoryEtc:string 또는 null; content*:string
- 응답 형식: 201 application/json consultationApi_createConsultation_Success<br>consultationId*:integer(int64)
- 구현 (11/6): 구현

### API-28 상담 수정
- 페이지 범위: 상담 모달
- 요청 경로: PUT /api/cases/{caseId}/consultations/{consultationId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path caseId*:integer(int64); path consultationId*:integer(int64)<br>본문 application/json ConsultationInput<br>consultedAt*:string(date); purpose*:string; category*:string; categoryEtc:string 또는 null; content*:string
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-29 상담 삭제
- 페이지 범위: 상담 모달
- 요청 경로: DELETE /api/cases/{caseId}/consultations/{consultationId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path caseId*:integer(int64); path consultationId*:integer(int64)<br>본문 없음
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### API-30 내 정보 조회
- 페이지 범위: /my
- 요청 경로: GET /api/members/me
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json myApi_getMyInfo_Success<br>name*:string; email*:string(email); orgName*:string; jurisdictionName*:string; title*:string 또는 null; phone*:string 또는 null
- 구현 (11/6): 구현

### API-31 내 정보 수정
- 페이지 범위: /my
- 요청 경로: PATCH /api/members/me
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json MyInfoPatch<br>title:string 또는 null; phone:string 또는 null
- 응답 형식: 200 application/json myApi_updateMyInfo_Success<br>name*:string; email*:string(email); orgName*:string; jurisdictionName*:string; title*:string 또는 null; phone*:string 또는 null
- 구현 (11/6): 구현

### API-32 비밀번호 변경
- 페이지 범위: /password/find·/my/password
- 요청 경로: PUT /api/members/me/password
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json PasswordChangeRequest<br>currentPassword*:string(password); newPassword*:string(password)
- 응답 형식: 200 application/json myApi_changePassword_Success<br>user*:LoginUser
- 구현 (11/6): 구현

### API-33 탈퇴 안내 조회
- 페이지 범위: /my/withdraw·확인 모달
- 요청 경로: GET /api/members/me/withdrawal
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json myApi_getWithdrawalInfo_Success<br>soleCases*:SoleCaseItem[]; sharedCaseCount*:integer; successors*:MemberOption[]; resourceCount*:integer; conversationCount*:integer; ongoingResources*:OngoingResourceTransferItem[]; endedResourceCount*:integer
- 구현 (11/6): 구현 (11/10)

### API-34 회원 탈퇴
- 페이지 범위: /my/withdraw·확인 모달
- 요청 경로: POST /api/members/me/withdrawal
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br><br>본문 application/json WithdrawalRequest<br>password*:string(password); transfers*:object[]; resourceTransfers*:object[]
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현 (11/10)

### API-35 담당 복지자원 목록 조회
- 페이지 범위: /my/resources
- 요청 경로: GET /api/members/me/resources
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json myApi_getMyResources_Success<br>totalCount*:integer; items*:ResourceListItem[]
- 구현 (11/6): 구현

### API-36 내 대화 목록 조회
- 페이지 범위: /my/conversations
- 요청 경로: GET /api/members/me/conversations
- 요청 형식: 인증 SESSION 쿠키<br>query page:integer; query size:integer<br>본문 없음
- 응답 형식: 200 application/json agentApi_listConversations_Success<br>totalCount*:integer; page*:integer; size*:integer; totalPages*:integer; items*:ConversationListItem[]<br>firstQuestion: 등록 당시 마스킹 처리 결과(목록 제목) · questionCount: 실패·취소 포함 질문 수 · lastMessageAt: 실행 종료 일시
- 구현 (11/6): 구현

### API-37 내 대화 내용 조회
- 페이지 범위: /my/conversations
- 요청 경로: GET /api/members/me/conversations/{conversationId}
- 요청 형식: 인증 SESSION 쿠키<br>path conversationId*:string(uuid)<br>본문 없음
- 응답 형식: 200 application/json agentApi_getConversation_Success<br>conversationId*:string(uuid); firstQuestion*:string(등록 당시 마스킹 처리 결과); lastMessageAt*:string(date-time); deleteScheduledAt*:string(date); messages*:AgentMessage[]<br>messages는 API-03-S1과 같은 형식 · 진행 단계·실패·취소 행까지 처음부터 전체
- 구현 (11/6): 구현

### API-38 내 대화 한 건 삭제
- 페이지 범위: /my/conversations
- 요청 경로: DELETE /api/members/me/conversations/{conversationId}
- 요청 형식: 인증 SESSION 쿠키 · CSRF 필수<br>path conversationId*:string(uuid)<br>본문 없음
- 응답 형식: 204 본문 없음<br>실행 중이면 AI 취소 요청 뒤 삭제 · 메시지는 CASCADE로 함께 삭제
- 구현 (11/6): 구현

### API-39 시도 목록 조회
- 페이지 범위: 공통
- 요청 경로: GET /api/regions/sidos
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json regionApi_getSidos_Success
- 구현 (11/6): 구현

### API-40 시군구 목록 조회
- 페이지 범위: 공통
- 요청 경로: GET /api/regions/sidos/{sidoCode}/sigungus
- 요청 형식: 인증 SESSION 쿠키<br>path sidoCode*:string<br>본문 없음
- 응답 형식: 200 application/json regionApi_getSigungus_Success
- 구현 (11/6): 구현

### API-41 행정동 목록 조회
- 페이지 범위: 공통
- 요청 경로: GET /api/regions/sigungus/{sigunguCode}/dongs
- 요청 형식: 인증 SESSION 쿠키<br>path sigunguCode*:string<br>본문 없음
- 응답 형식: 200 application/json regionApi_getDongs_Success
- 구현 (11/6): 구현

### API-42 소속 기관 회원 목록 조회
- 페이지 범위: 공통
- 요청 경로: GET /api/organizations/me/members
- 요청 형식: 인증 SESSION 쿠키<br><br>본문 없음
- 응답 형식: 200 application/json memberApi_getOrgMembers_Success
- 구현 (11/6): 구현

### SYS-01 CSRF 쿠키 준비<br>신규 설계
- 페이지 범위: 공통
- 요청 경로: GET /api/auth/csrf
- 요청 형식: 인증 공개<br><br>본문 없음
- 응답 형식: 204 본문 없음
- 구현 (11/6): 구현

### SYS-02 서버 생존 확인<br>현재 구현
- 페이지 범위: 공통
- 요청 경로: GET /api/health
- 요청 형식: 인증 공개<br><br>본문 없음
- 응답 형식: 200 application/json HealthData<br>status*:string
- 구현 (11/6): 구현

## 내부 연동 API

- 제목: 내부 연동 API
- 요약: 6개 작업  BE ↔ AI · 파이프라인 → BE  AI 서버(/internal/)는 인증 없음 · BE 내부 경로(/api/internal/)는 호출자별 서비스 토큰(INT-07 · 08 AI 토큰, INT-04 파이프라인 토큰)  둘 다 Nginx에 열지 않음 (Nginx는 /api/internal/을 404로 막음) · BE 내부 경로는 세션 · CSRF 없는 별도 보안 체인 · 인사이트 보고서는 AI가 DB에 직접 저장
- 출처: AI 에이전트 패널 동작 흐름 (A 방식) 2026-11-02 · 응답 필드와 시간 값은 AI 담당자와 확정 · 인사이트 보고서 INT-04 · 05는 2026-11-06 초안 (A 방식: 생성 세대를 저장하지 않음, 결과 시각 resultUpdatedAt으로 옛 보고서 판단) · 보고서 저장 INT-06은 2026-11-09 삭제 (AI가 region_insight_report에 직접 저장, insight-report.md 4절) · INT-01 messageId · 화면 문맥, INT-07 추가, INT-03 삭제는 2026-11-09 (ai-agent-panel.md 3절, openapi 2.3.4 x-internal-api) · INT-05 dongCodes · 202 본문 없음(꼬리표는 AI가 직접 읽음), INT-08 추가는 2026-11-10 (insight-report.md 4절, openapi 2.4.0)

### INT-01 AI 실행 시작<br>신규 설계
- 구간: BE → AI
- 요청 경로: POST /internal/agent/runs
- 요청 형식: 인증 없음 (내부 네트워크)<br><br>본문 application/json<br>conversationId*:string(uuid); messageId*:integer(int64, 커밋된 질문 행 ID = API-03의 questionId); context:ScreenContext(선택, API-03에서 받은 그대로)
- 응답 형식: 202 본문 없음, 접수만 바로 돌려주고 뒤에서 실행<br>같은 messageId가 실행 중이어도 202 · 같은 대화의 다른 질문이 실행 중이면 409 · 400 본문 오류<br>AI는 대화 ID로 이전 대화를, messageId로 이번 질문을 ai_message에서 읽고 진행·완료·실패·취소 행을 직접 저장하고 행마다 INT-07<br>응답이 없으면 BE가 같은 messageId로 질문당 1번 다시 보냄 (INT-03 대신)<br>질문에 대상 정보가 부족하면 되묻는 내용을 완료 행으로 저장 (사용자의 답은 같은 대화의 다음 질문)

### INT-02 AI 실행 취소<br>신규 설계
- 구간: BE → AI
- 요청 경로: POST /internal/agent/runs/{conversationId}/cancel
- 요청 형식: 인증 없음 (내부 네트워크)<br>path conversationId*:string(uuid)<br>본문 없음
- 응답 형식: 202 실행을 멈추고 취소 행 저장<br>BE는 http-timeout과 취소 대기 중 짧은 시간까지 응답을 기다리고, 취소 대기 안에 끝 행이 없으면 취소 행을 대신 저장

### INT-04 파이프라인 완료 알림<br>신규 설계
- 구간: 파이프라인 → BE
- 요청 경로: POST /api/internal/analysis/pipeline-completions
- 요청 형식: Authorization: Bearer <파이프라인 토큰><br><br>본문 application/json<br>month*:string(YYYY-MM); pipelineRunId:string(1~200자, 로그용); reason:string(FULL · RESULT_RELOAD · ANALYSIS_RELOAD, 기본 FULL, 로그용)
- 응답 형식: 202 application/json<br>month*:string; targetCount*:integer<br>BE가 그 달 region_result의 동 코드를 모두 읽어 INT-05를 보내고, AI가 http-timeout(기본 3초) 안에 202로 접수하면 202 · targetCount는 보낸 동 수<br>400 VALIDATION_ERROR · 401 UNAUTHENTICATED · 403 FORBIDDEN · 404 NOT_FOUND(그 달 결과 없음) · 503 AI_UNAVAILABLE(AI 접수 실패 → 파이프라인이 재시도)<br>14단계(결과 검증) 성공 뒤 Airflow 마지막 작업이 보냄. 12·13단계만 다시 돌려도 보냄 · fake 모드는 INT-05 없이 202(targetCount는 그 달 동 수)

### INT-05 인사이트 보고서 생성 요청<br>신규 설계
- 구간: BE → AI
- 요청 경로: POST /internal/insight-reports/runs
- 요청 형식: 인증 없음 (내부 네트워크)<br><br>본문 application/json<br>requestId*:string(uuid, INT-04를 처리하며 BE가 만든 값 = INT-04 응답의 X-Request-Id · meta.requestId); month*:string(YYYY-MM); dongCodes*:string[](10자리, 그 달 결과가 있는 모든 동, 1개 이상, 중복 없음)
- 응답 형식: 202 본문 없음<br>400 본문 오류(모르는 필드 · 형식 · 중복 동)<br>접수만 바로 돌려주고 뒤에서 동별로 생성 · AI가 동마다 꼬리표(결과 행 updated_at)를 먼저 읽고 region_insight_report에 직접 저장(eumi_ai INSERT · UPDATE, 결과 행 updated_at = 꼬리표일 때만 반영, 같은 동 · 월 덮어씀, 0행이면 버림, 검토를 통과한 칸만 저장하고 나머지는 NULL, 저장할 칸이 없는 동은 실패)<br>생성 중 오류가 난 동은 요청 끝에 한 번 더 · 모든 동을 처리한 뒤 INT-08 한 번 · 같은 달 요청이 겹치면 진행 중 작업을 멈추고 새 요청으로 다시 시작 · BE는 다시 보내지 않음

### INT-07 AI 행 저장 알림<br>신규 설계
- 구간: AI → BE
- 요청 경로: POST /api/internal/agent/notifications
- 요청 형식: Authorization: Bearer <AI 토큰><br><br>본문 application/json<br>conversationId*:string(uuid); messageId*:integer(int64, 양수, 방금 커밋한 AI 행 ID)
- 응답 형식: 204 본문 없음<br>400 INVALID_JSON(모르는 필드 · 정수 아님) · 400 VALIDATION_ERROR · 401 UNAUTHENTICATED · 403 FORBIDDEN(AI 토큰 아님) · 404 NOT_FOUND(그 대화에 그 AI 행 없음)<br>AI 행 커밋 직후 보냄 · 최대 2번(5xx · 연결 오류 · 시간 초과일 때만 한 번 더, 4xx는 다시 안 보냄), 실패해도 실행 계속 · BE는 중복 · 순서에 기대지 않고, 끝 행이면 그 질문의 메모리 추적 상태를 정리 · 화면에는 밀지 않음(1초 조회 유지)

### INT-08 보고서 생성 완료 알림<br>신규 설계
- 구간: AI → BE
- 요청 경로: POST /api/internal/analysis/insight-report-completions
- 요청 형식: Authorization: Bearer <AI 토큰><br><br>본문 application/json<br>requestId*:string(INT-05에서 받은 값); month*:string(YYYY-MM); savedCount*:integer(0 이상, 저장된 동 수, 일부 칸만 저장한 보고서 포함); failedDongCodes*:string[](10자리, 저장하지 못한 동, 없으면 빈 배열)
- 응답 형식: 204 본문 없음<br>400 INVALID_JSON(모르는 필드 · 타입 오류) · 400 VALIDATION_ERROR · 401 UNAUTHENTICATED · 403 FORBIDDEN(AI 토큰 아님)<br>INT-05 요청 하나의 모든 동을 처리한 뒤 한 번 보냄 · 최대 2번(5xx · 연결 오류 · 시간 초과일 때만 한 번 더, 4xx는 다시 안 보냄) · BE는 requestId · 월 · 저장 수 · 실패한 동을 로그에만 남기고 저장하지 않음, 두 번 받아도 결과가 같음

## 별도 범위

- 제목: 외부 연동과 구현 경계
- 요약: Tableau·내부 AI·데이터 파이프라인은 외부 REST 목록과 구별
- 출처: 대시보드_구현_확정안.md · tableau_views.json 3.0.0 (11/3 새 워크북) · 3.2.0 (11/5 상세 워크북 v2_0_6 · 보고서 시트 EmbedDetailV01~V08) · eumi/db/README.md · 11/12 워크북 v2_0_6 하나로 통일 (frontend/src/tableau/tableauConfig.ts)

### Tableau
- 대상: 시군구 ①②③⑤ · 읍면동 ⑥ · 인사이트 보고서 그래프 EmbedDetailV01~V08
- 현재 근거: Embedding API v3 · 워크북 eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed 하나 (11/12 재게시, 모든 뷰. 메인 워크북 eumi_tableau_main_dashboard_v_master는 11/12부터 쓰지 않음) · 대시보드는 모두 고정 크기, 크기 · 배치가 바뀌면 FE tableauConfig.ts도 바꿈
- 경계: 서비스 REST로 세지 않음
- 선행 조건: ⑥ 게시(11/5) · ④는 11/5 결정으로 넣지 않음 · 데이터 파일 계약 확인(월 형식·산출불가·계산 값·공개 범위)
- 검증: 동 선택·매개변수(시군구·기간)·로딩·게시 오류

### FastAPI 내부
- 대상: AI 실행 · 취소(INT-01 · 02) · 행 저장 알림(INT-07) · 인사이트 보고서 생성 요청 INT-05 · 생성 완료 알림 INT-08 (내부 연동 API 시트). PDF 추출(API-18)은 2026-11-09 범위 제외
- 현재 근거: AI: 2026-11-02 A 방식 결정
- 경계: 브라우저는 Spring만 호출 · 대화 패널: AI가 ai_message에 직접 저장 · 인사이트 보고서: AI가 region_insight_report에 직접 저장 (BE는 생성 요청 · 조회만)
- 선행 조건: 운영 모델(GMS) 확정 · AI 작업 선택 수정 (운영 시간 값은 11/10 확정 330 · 5 · 40 · 3초, artifacts 형식은 11/9 ai-agent-panel.md 2-1, 이전 대화 범위는 11/2 '전체'로 결정, eumi_ai의 ai_message 읽기·추가 권한은 11/2 적용)
- 검증: 행 단위 커밋·끝 행 하나·늦은 행 거부·취소 경합·질문 마스킹·시간 초과·부족 정보 되묻기·응답 없음 재요청 1회·INT-07 토큰과 행 소속

### 파이프라인
- 대상: analysis 10테이블·public 결과
- 현재 근거: V5~V6·afterMigrate
- 경계: Spring은 analysis 접근 불가
- 선행 조건: 코드표·좌표계·지역 귀속·적재 일정 · 완료 알림 INT-04 (14단계 검증 뒤, Airflow 마지막 작업)
- 검증: 월/연도 부분 재적재·FK·보고서 재생성(result_updated_at 비교)

### 정적 검수
- 대상: OpenAPI·SQL·문서
- 현재 근거: 산출물_검증_결과.json
- 경계: 실제 HTTP 시험 아님
- 선행 조건: 기능 구현 후 실제 연동
- 검증: 쿠키·SMTP·Nginx·DB·Tableau·AI
