# frontend

이음이 웹 화면 (React 19 · React Router 7 · TanStack Query 5 · Vite 8 · TypeScript 5.9 · Tailwind 4, Node 24).

빌드·배포 설정, 레이아웃 틀, 공통 부품, API 공통 계층 위에 페이지를 하나씩 붙이는 중이다.
아직 붙이지 않은 화면은 '준비 중'으로 보인다 (목록은 `src/screens/placeholder/placeholders.ts`).
업무 화면은 페이지 작업 차례마다 프로토타입 원본(초기화 직전 develop 커밋 `c96cf85`의 `frontend/`)에서 옮겨 실제 API로 연결한다.
프로토타입 화면은 별도 링크(`eumi-prototype.vercel.app`)에서 확인하며 더 고치지 않는다.
그래서 운영 화면에 보이는 페이지는 실제로 동작하는 페이지뿐이다.

## 실행

```bash
npm ci
npm run dev        # http://localhost:5173, /api → http://localhost:8080 (backend) 프록시
npm run typecheck
npm run build
```

로그인 상태 복원(`GET /api/auth/me`)이 backend를 부르므로, 화면을 확인하려면 API 서버가 하나 떠 있어야 한다.

- **실제 API**: backend(8080)와 `infra/` 로컬 DB를 띄운 뒤 `npm run dev`.
- **가짜 API**: 저장소 밖 `mock-api.mjs`를 8081에 띄우고(`node mock-api.mjs`), `/api` 프록시 대상을 `VITE_API_TARGET`으로 바꾼다. 로그인은 `http://localhost:5173/api/__dev-login`. 데이터 파트의 Airflow 웹(`docker compose --profile data`)도 8081을 쓰므로 둘을 함께 켜지 않는다.

```bash
VITE_API_TARGET=http://localhost:8081 npm run dev
```

```powershell
$env:VITE_API_TARGET="http://localhost:8081"; npm run dev
```

## 구조

| 위치 | 내용 |
|---|---|
| `src/api/http.ts` | 공통 HTTP 클라이언트. 같은 출처 `/api`, 성공 `data`만 반환, 204 본문 안 읽음, 실패는 `ApiError` |
| `src/api/csrf.ts` | `GET /api/auth/csrf`로 `XSRF-TOKEN` 쿠키 준비, 변경 요청에 `X-XSRF-TOKEN` 헤더 |
| `src/api/errors.ts` | `ApiError`, 통신 오류·프록시 HTML·429·413 처리 문구 |
| `src/api/queryClient.ts` | TanStack Query 기본값 (4xx 재시도 안 함, 변경 요청 재시도 안 함) |
| `src/api/schema.d.ts` | `docs/api/openapi.json`에서 자동 생성한 타입(`npm run gen:api`). 직접 고치지 않는다 |
| `src/api/types.ts` | 화면에서 쓰는 응답 타입 별칭 |
| `src/api/*Api.ts` | API 묶음 (`authApi`: 로그인·로그인 상태 조회·로그아웃, `agentApi`: AI 패널 질문·조회·중단과 AI 대화 기록, `analysisApi`: 적재 월·읍면동 요약·보고서, `regionApi`: 시도·시군구·행정동 목록, `caseApi`: 사례자·상담, `resourceApi`: 복지자원, `memberApi`: 같은 기관 회원(담당자 선택), `myApi`: 마이페이지 내 정보·담당 자원) |
| `src/session/` | 로그인 상태(`sessionStore`), 복원·로그아웃·401 처리(`sessionActions`) |
| `src/components/` | 레이아웃(헤더·메뉴), 로그인 필요 화면 보호, 확인 창·알림·빈 상태·입력·정렬 버튼·페이지 번호 부품 |
| `src/screens/` | 화면 (`auth/` 로그인, `risk/` 고립 위험 탐색, `case/` 사례자 목록·상세·등록·수정·상담 창, `resource/` 복지자원 목록·상세·등록·수정, `my/` 마이페이지 탭·내 정보·담당 자원·AI 대화 기록·비밀번호 변경), `placeholder/` '준비 중' 화면과 화면별 예정 내용 |
| `src/tableau/` | Tableau Public 대시보드 띄우기(Embedding API v3)와 게시본 설정. 워크북 하나에서 자리마다 임베드용 대시보드를 띄운다. 새 뷰가 게시되면 `tableauConfig.ts`에 대시보드·워크시트 이름과 크기를 채운다. AI 패널 완료 행의 Tableau 카드(`TableauArtifactCard`)는 AI가 준 게시 뷰 주소·매개변수·필터로 띄운다 (정화한 표·SVG는 `components/agent/AgentArtifacts`) |
| `src/routes/paths.ts` | 화면 주소 |

## 규칙

- 로그인은 서버 세션(`SESSION` 쿠키, HttpOnly)으로만 유지한다. 회원 ID·토큰을 브라우저 저장소에 넣지 않는다.
- API는 `api.get/post/put/patch/delete`로만 부른다. 화면에서 `fetch`를 직접 쓰지 않는다.
- 응답 타입은 `src/api/types.ts`에서 `Schemas`·`SuccessData`로 꺼내 쓴다.
- 401을 받으면 로그인 화면으로, 403 `PASSWORD_CHANGE_REQUIRED`를 받으면 비밀번호 변경 화면으로 간다 (`sessionActions`).
- 로그아웃·사용자 전환 때 Query 캐시를 비운다 (`sessionStore.signOut`).
- 페이지를 옮길 때: 화면 컴포넌트와 그 CSS를 함께 옮기고, mock 호출을 `src/api/*Api.ts` + `useQuery`/`useMutation`으로 바꾼 뒤 `App.tsx`의 해당 줄과 `placeholders.ts` 항목을 바꾼다.
- 화면 CSS는 `index.css`가 아니라 그 화면 파일에서 `import "@/styles/○○.css"`로 불러온다. 여러 페이지 브랜치가 같은 파일을 동시에 고쳐 충돌하지 않게 하기 위해서다. `main.tsx`가 `index.css`를 가장 먼저 불러오므로 화면 CSS가 공통 규칙(`.input` 등) 뒤에 붙는다. 목록·상세·입력 화면 공통 스타일은 `list.css`·`detail.css`·`form.css`(사례자·복지자원이 함께 쓴다).

## API 타입 다시 만들기

`npm run gen:api`는 저장소의 `docs/api/openapi.json`을 읽는다. 명세가 바뀌면 그 파일을 갱신하고 다시 실행한다.
