# 이음이 AI 서버

LangChain·LangGraph 기반 AI 서버를 책임별 모듈 구조로 개발한다.
현재는 디렉토리와 빈 파일만 생성한 상태다. 이 README를 제외한 소스·설정·문서 파일의 내용은 아직 작성하지 않았다.

## 구조

```text
ai/
├── README.md
├── AGENTS.md
├── REFERENCES.md
├── pyproject.toml
├── .env.example
├── langgraph.json
├── Dockerfile
├── src/eumi_ai/
│   ├── api/            # FastAPI 앱과 실행·조회·재개 API
│   ├── contracts/      # 외부 입력과 산출물·근거·확인 사항
│   ├── agents/         # 분석·추천·수집·시각화·기획·사용자 요청 처리
│   ├── workflows/      # 상담 구조화·메일 초안의 고정 처리 순서
│   ├── tools/          # 조회·검색·가공·저장 도구
│   ├── policies/       # 이용 조건·근거·승인 관련 검사
│   ├── integrations/   # 업무 API·PostgreSQL 연결
│   ├── rag/            # 문서 색인과 검색
│   ├── prompts/        # 프롬프트와 업무 지침 배치 예정
│   ├── runtime.py      # 프레임워크 조립과 공통 실행 설정
│   └── settings.py     # 환경 설정
├── tests/
│   ├── unit/           # 도구·업무 규칙 단위 검증
│   ├── integration/    # API·저장소·재개 연동 검증
│   └── fixtures/       # 합성·비식별 검증 자료
└── evals/
    ├── promptfooconfig.yaml
    ├── provider.py     # 실제 Agent 실행 경로를 평가 도구에 연결
    └── cases/          # 모델 출력·업무 행동 평가 사례
```

Python 패키지 디렉토리에는 빈 `__init__.py`를 두었다. 파일이 없는 디렉토리는 `.gitkeep`으로 유지한다.

## 초기화 범위

- 모든 Python 파일은 비어 있다. 함수·클래스·프롬프트·테스트 구현은 없다.
- `pyproject.toml`, `langgraph.json`, `Dockerfile`, `.env.example`, 평가 설정은 빈 자리표시자다. 유효한 실행 설정으로 사용할 수 없으며, 실행 전에 내용을 작성해야 한다.
- `AGENTS.md`와 `REFERENCES.md`는 후속 작성 위치만 마련했다.
- 의존성 설치, Python·라이브러리 버전 선택, 실행 환경 구성은 아직 수행하지 않았다.
- `uv.lock`은 의존성을 정의한 뒤 패키지 도구로 생성한다.

## 저장소 내 위치

| 대상 | 관리 위치 |
| --- | --- |
| AI 소스·테스트·평가 | `ai/` |
| 공동 AI 설계·API 계약 | `docs/ai/` |
| DB 마이그레이션 | `db/migration/` |
| 서비스 실행·배포 환경 | `infra/` |
| 지표 산출·데이터 분석 파이프라인 | `data/` |

상위 저장소의 `CONTRIBUTING.md`와 `.gitignore`를 따른다.
