# 작업 참고 (docs/work-ref)

**작업 계획에 딸린 참고 문서**를 둔다. 확정 계약은 [docs/api](../api/README.md), 기준 문서는 [docs/spec](../spec/README.md), 결정 이유는 [docs/decisions](../decisions/)에 있다. 여기 문서와 이 셋이 다르면 이 셋을 따른다.

## 규칙

1. **넣을 때:** 아래 표에 한 줄을 추가한다. 원본, 원본 날짜, 쓰는 계획, 끝나는 조건을 적는다. 저장소 밖 문서의 사본은 내용을 고치지 않는다.
2. **진행:** 계획대로 진행한다. 진행 중에 결정이 바뀌면 이 폴더가 아니라 docs/api · docs/spec · docs/decisions를 고친다.
3. **계획이 모두 끝나면:** 마지막 MR에서 아래 두 가지를 함께 한다.
   - 작업으로 바뀐 계약을 docs/api에 작업한 내용대로 고친다. 기능이 바뀌었으면 docs/spec도 고친다.
   - 이 폴더의 해당 문서와 표의 줄을 지운다.
4. **넣지 않는 것:** 비밀값(비밀번호 · 키 · 토큰)과 실제 개인정보.

## 지금 있는 문서

| 파일 | 원본 | 원본 날짜 · 판 | 쓰는 계획 | 끝나는 조건 |
|---|---|---|---|---|
| [구현_트랜잭션_가이드.md](구현_트랜잭션_가이드.md) | `이음이_개발산출물_최종_v1.0/산출물/개발_참조/` | 10/30 | BE 남은 API(회원가입 · 임시 비밀번호 · 탈퇴)의 잠금 · 트랜잭션 구현 | 남은 BE API 구현 MR이 모두 끝날 때 |
| [API_DB_매핑.md](API_DB_매핑.md) | 같은 곳 | 10/30 | 위와 같은 BE 구현에서 API와 테이블 대응 확인 | 위와 같다 |
| [FE_연동과_완료_조건.md](FE_연동과_완료_조건.md) | `공통_응답_및_세션_규칙.md` 2.2.0의 'FE 연동과 완료 조건' 절 | 10/30 | 화면을 실제 API로 연결하는 작업 | 모든 화면이 실제 API로 연결될 때 |
| [프로토타입_기능_상세_계약.md](프로토타입_기능_상세_계약.md) | `INFRA/fe-ref/` | 11/3 | 화면별 세부 동작(API 없는 로컬 동작 포함) | 화면 작업이 모두 끝날 때 (바뀐 동작은 docs/spec 기능명세에 반영) |
| [대시보드_구현_확정안.md](대시보드_구현_확정안.md) | `INFRA/fe-ref/` | 11/5 | 고립 위험 탐색 · 읍면동 상세 화면의 Tableau 임베딩 | 대시보드 · 읍면동 상세 · 보고서 화면이 끝날 때 |
| [대시보드_파일_계약.md](대시보드_파일_계약.md) | `INFRA/fe-ref/` | 11/2 | Tableau 게시 데이터 형식 (데이터 파트와 맞춤) | 위와 같다 |
| [tableau_views.json](tableau_views.json) | `INFRA/fe-ref/` | 3.2.0 (11/5) | Tableau 뷰 목록 (`frontend/src/tableau/tableauConfig.ts`의 기준) | 위와 같다 |

## 적용하지 않는 부분

사본에는 지금 기준과 다른 옛 내용이 남아 있다. 아래 부분은 적용하지 않는다.

- **SSE · JWT 관련 내용:** 로그인은 [docs/decisions/login-sse.md](../decisions/login-sse.md)를 따른다.
- **옛 AI 실행 방식** (runId, `/agent/runs`, `ai_conversation_turn`, 메모리 실행 저장소, 410): AI 대화는 [docs/api/ai-agent-panel.md](../api/ai-agent-panel.md)를 따른다. `API_DB_매핑.md`의 API-03 · 37 · 38 행과 `프로토타입_기능_상세_계약.md`의 'Agent · 추천 · 저장' 절이 여기에 해당한다.
- **옛 보고서 형식** (`summary_lines` · `report` JSON · 5종 그래프): 보고서는 [docs/api/insight-report.md](../api/insight-report.md)를 따른다.
- **대시보드 ④:** 11/5 결정으로 메인 화면에서 뺐다.
- 사본 안에서 이름만 나오는 `최종_기능_ERD_점검.md`는 저장소에 없다.
