# 사회적 고립 위험 분석 서비스

> 지역의 사회적 고립 위험 신호를 데이터로 분석하고, 해석·비교·시각화로 복지 담당자의 지역 탐색을 돕는 웹 서비스

- **개발 기간**: 2026.10.26 ~ 2026.11.08
- **SSAFY 15기 자율 프로젝트**
- **구현 범위**: ERD(테이블 24개)와 프로토타입 화면 기준 6개 영역 — 로그인 · 회원가입 · 비밀번호 찾기, 위험 탐지 대시보드, 사례자 관리, 복지자원 관리, 마이페이지, AI Agent 패널

## 목차

1. [프로젝트 소개](#프로젝트-소개)
2. [주요 기능](#주요-기능)
3. [서비스 화면](#서비스-화면)
4. [시스템 구성](#시스템-구성)
5. [기술 스택](#기술-스택)
6. [디렉터리 구조](#디렉터리-구조)
7. [시작하기](#시작하기)
8. [팀 소개](#팀-소개)
9. [문서](#문서)
10. [협업 규칙](#협업-규칙)

## 프로젝트 소개

이 서비스는 복지 담당자가 관할 지역의 사회적 고립 위험 신호를 파악하고, 지역·집단별 특성을 비교해 방문 지역과 우선순위를 검토하는 일을 돕습니다.

지역 데이터를 분석한 **배경 취약성 지수**와 **행동 이상 지수**로 지역별 위험 신호를 보여줍니다. AI Agent는 분석 근거와 비교 결과를 설명하고, 사용자가 선택한 지역·지표·차트를 참고해 추가 설명과 시각화를 제공합니다.

**대상 사용자**: 복지기관 담당자 (소속 기관의 관할 시군구 기준으로 이용)

## 주요 기능

### 위험 탐지 대시보드

- 지역·집단별 분석 결과를 지도·차트·표로 보여줍니다.
- 분석 완료 후 생성·검증한 기본 해석을 해당 분석 결과와 함께 표시합니다.
- 지역·기간별 비교 결과와 지표 정의·출처·해석 한계를 함께 제공합니다.

### AI Agent

- 모든 화면에서 열 수 있는 패널로, 사용자가 보고 있는 화면의 내용을 참고해 질문에 답합니다.
- 데이터 분석 결과 해석 Agent가 주요 신호·비교 결과·근거·해석 한계를 설명합니다.
- 데이터 시각화 Agent가 요청 목적에 맞는 차트·표·지도를 생성하고 검증합니다.
- 사용자 요청 처리 Agent가 자연어 요청에 필요한 Agent·도구를 선택하고 결과를 통합합니다.
- 대화 이력과 선택 대상·필터를 유지해 후속 요청에 반영합니다.

## 서비스 화면

> 구현 후 주요 화면 캡처를 추가합니다.

## 시스템 구성

| 구성 요소 | 기술 | 역할 |
|---|---|---|
| 웹 클라이언트 | React | 서비스 화면, Tableau 대시보드 임베딩, AI Agent 패널 |
| API 서버 | Spring Boot | 회원, 복지자원, 사례자, 상담 등 서비스 API |
| AI Agent 서버 | FastAPI | 화면 기반 질의응답, 복지자원 추천, 인사이트 보고서 생성, 문서 기반 자동 입력 |
| 데이터 파이프라인 | Python · Spark · Kafka | 배경 데이터 월별 배치, 유동인구 데이터 시간별 처리, 고립 위험 분석 결과 적재 |
| 데이터베이스 | PostgreSQL | API 서버·AI Agent 서버·데이터 파이프라인이 함께 사용 (스키마는 `db/`에서 관리) |
| 시각화 | Tableau | 위험도 지도 등 대시보드 시각화 |

> 아키텍처 다이어그램은 서버 간 연동 방식이 정해지면 추가합니다.

## 기술 스택

| 구분 | 기술 | 버전 |
|---|---|---|
| 프론트엔드 | React · Vite · TypeScript · Tailwind CSS | 19.3.1 · 8.3.5 · 5.9.3 · 4.3.3 (Node 24) |
| 백엔드 | Spring Boot · Java · Gradle | 4.1.2 · 21 · 9.8.2 |
| AI Agent 서버 | FastAPI · LangChain · LangGraph | AI 파트 초기 설정 때 확정 |
| 데이터 분석 | Python · Spark (PySpark) · Kafka · Airflow | 3.12 · 3.5.9 (Java 17) · 3.9.2 (KRaft) · 2.10.5 |
| 원본 저장소 | MinIO (S3 호환) | 2025.7.23 (`bitnamilegacy/minio`) |
| DB | PostgreSQL · Flyway | 17 · 13.11.1 |
| 시각화 | Tableau Public | - |
| 로컬 메일 확인 | Mailpit | v1.27 |
| 협업 | GitLab, Jira, Figma | - |

## 디렉터리 구조

```
.
├── frontend/          # React 웹 (Vite)
├── backend/           # Spring Boot API 서버
├── ai/                # FastAPI AI Agent 서버
├── data/              # 데이터 수집 · 적재 · 분석
│   ├── notebooks/     #   탐색 · 분석 노트북
│   └── pipeline/      #   적재 · 분석 파이프라인
├── db/                # PostgreSQL 스키마 (여러 서버가 같은 DB를 쓰므로 한 곳에서 관리)
│   ├── migration/     #   Flyway 마이그레이션 + 계정별 권한(afterMigrate.sql)
│   ├── roles/         #   DB 계정 생성 SQL
│   └── seed/          #   개발 · 시연용 초기 데이터
├── infra/             # 로컬 개발 DB(docker-compose), 배포 설정
├── docs/              # 결정 기록, 저장소 설정, 명세 문서
├── .gitlab/           # MR 템플릿
├── Jenkinsfile        # CI/CD
├── CONTRIBUTING.md    # 협업 규칙 (브랜치 · 커밋 · MR · 리뷰 · Jira · DB · 비밀값)
└── README.md
```

## 시작하기

### 준비물

| 파트 | 필요한 것 |
|---|---|
| 공통 | Git, Docker Desktop (설치 + 실행) |
| BE | JDK 21 |
| FE | Node 24 |
| AI · 데이터 | 각 파트가 정한 Python 환경 |

### 받기와 로컬 DB

```bash
git clone https://lab.ssafy.com/s15-final/S15P31B201.git
cd S15P31B201                    # 기본 브랜치 develop

cd infra
cp .env.example .env
docker compose up -d             # PostgreSQL 17 + 스키마 · 계정 · 권한 + 메일 확인용 Mailpit
```

DB 계정, 메일 확인, 문제 해결은 [infra/README.md](infra/README.md)를 봅니다.

### 파트별 실행

| 구분 | 실행 | 확인 |
|---|---|---|
| 백엔드 | `cd backend` → `./gradlew bootRun` (또는 IntelliJ) | http://localhost:8080/api/health |
| 프론트엔드 | `cd frontend` → `nvm use 24` → `npm ci` → `npm run dev` | http://localhost:5173 |
| AI Agent 서버 | [ai/](ai/) | 포트 8000, `GET /health` |
| 데이터 파이프라인 | [data/](data/README.md) | |

## 팀 소개

| 이름 | 역할 | 담당 |
|---|---|---|
| 김민준 | PM · AI | 일정 · Jira 관리, AI Agent 서버 |
| 김민재 | BE · FE · Infra | API 서버, 서비스 화면, DB, 배포 환경 |
| 강병민 | 데이터 엔지니어링(DE) | 데이터 수집 · 적재 파이프라인 (Spark · Kafka) |
| 이지석 | 데이터 분석(DA) | 지표 설계 · 분석 |
| 배유진 | - | - |
| 이지원 | - | - |

## 문서

| 문서 | 위치 |
|---|---|
| 협업 규칙 (브랜치 · 커밋 · MR · 리뷰 · Jira · DB · 비밀값) | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 로컬 개발 환경 (DB · 메일) | [infra/README.md](infra/README.md) |
| DB 스키마 · 마이그레이션 규칙 | [db/README.md](db/README.md) |
| API 계약 (OpenAPI 2.3.1) · AI 에이전트 패널 동작 · 인사이트 보고서 내부 연동 | [docs/api/openapi.json](docs/api/openapi.json), [docs/api/ai-agent-panel.md](docs/api/ai-agent-panel.md), [docs/api/insight-report.md](docs/api/insight-report.md) |
| 결정 기록: 로그인 방식 · 에이전트 흐름 전달 | [docs/decisions/login-sse.md](docs/decisions/login-sse.md) |
| GitLab 저장소 설정 | [docs/gitlab-setup.md](docs/gitlab-setup.md) |
| 문서 목록 (테이블 정의서 · ERD 위치 포함) | [docs/README.md](docs/README.md) |

## 협업 규칙

요약입니다. 전체 내용은 [CONTRIBUTING.md](CONTRIBUTING.md)를 봅니다.

- **브랜치**: `master`(배포) · `develop`(기본, 개발 통합)은 직접 push가 막혀 있습니다. `develop`에서 `태그/기능명` 브랜치를 만들어 `develop` 대상 MR로 병합합니다.
- **커밋**: 제목 `{태그}: [{기능명}] 한 일`, 한 줄 띄우고 `Jira: 이슈 키`
- **MR 리뷰**: DB 마이그레이션, 파트 간 API · 이벤트 형식, `infra/`는 리뷰어 승인 후 병합합니다. 그 밖에는 리뷰어만 지정하고 병합할 수 있습니다.
- **Jira**: 작업 전에 Task를 만들고, 키를 커밋 본문과 MR 설명에 적습니다.
- **DB**: 병합된 마이그레이션 파일은 고치지 않고 새 파일로 추가합니다. 테이블 변경은 'Eumi ERD 변경 기록'에 먼저 적습니다.
- **비밀값**: `.env` · 키 파일은 커밋하지 않고, 전달은 Mattermost 비공개 채널에서만 합니다. 로컬 DB에는 가짜 데이터만 넣습니다.
