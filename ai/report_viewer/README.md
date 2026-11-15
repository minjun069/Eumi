# 실행 모니터 수정 안내

저장된 `report.json`을 다섯 영역으로 읽는 로컬 뷰어다. 모델 호출·State·실행기에는 값을 쓰지 않는다.

## 수정할 파일

| 바꾸려는 부분 | 파일과 위치 |
| --- | --- |
| 화면 순서, 영역 제목, 기본 구조 | [report_viewer.html](../report_viewer.html)의 `sections`와 다섯 `section` |
| 색상, 글꼴, 여백, 카드, 반응형 배치 | [styles.css](styles.css). 기본값은 맨 위 `:root`, 세부 스타일은 번호별 주석 아래 |
| 노드명, 상태명, 메시지 역할 | [data.js](data.js)의 `nodeNames`, `statuses`, `roles` |
| trace 연결, 토큰 집계, 이전 대화 구분 | [data.js](data.js)의 `inspect`, `sumTokens`, `conversation` |
| 각 영역의 표시 내용·클릭 동작 | [app.js](app.js)의 `renderOverview`, `renderFlow`, `renderNodeDetail`, `renderSettings`, `renderConversation` |
| 접기·펼치기, 원문 복사, Markdown, 표, 산출물 | [components.js](components.js) |
| 한 파일로 내보내는 처리 | [report_html.py](../report_html.py) |

HTML과 JavaScript는 요소의 `id`로 연결된다. `id`를 바꿀 때는 `app.js`의 같은 이름도 함께 바꾼다. CSS는 한 선택자의 속성을 한 줄씩 배치했다. 별도 프레임워크나 npm 설치는 필요 없다.

## 열기·다시 생성하기

`report_viewer.html`을 브라우저에서 직접 열고 **실행 기록 불러오기**로 JSON을 선택하면 분리된 소스의 변경을 확인할 수 있다. CSS·JS를 수정한 뒤에는 새로고침한다.

공유용 리포트는 `Eumi/ai`에서 생성한다.

```powershell
uv run python report_html.py outputs/scenarios --output outputs/scenarios/report.html
```

생성된 HTML에는 CSS·스크립트·데이터가 모두 포함된다. 이 파일 하나로 오프라인에서 열 수 있다. 기존에 생성한 HTML은 원본 소스 변경만으로 갱신되지 않으므로 위 명령으로 다시 생성하거나, 새 뷰어에 기존 JSON을 불러온다.

## 표시 기준

- 전체 입출력: 초기 State의 마지막 사용자 메시지를 이번 실행의 최초 입력으로 표시한다. 분석 이벤트 실행은 사용자 질문 없이 시작된 것으로 표시한다. `request.goal`은 별도의 작업 요청으로 열람한다.
- 실행 흐름: 부모 호출별로 노드를 묶어 호출 시작 순서를 표시한다. 상위 노드 시간에 하위 호출 시간이 포함될 수 있으므로 행별 시간을 합산하지 않는다.
- 토큰: 가장 가까운 부모 노드에 모델 호출을 한 번만 집계한다. 실패한 호출도 포함한다. 실제 0과 미기록을 구분하고 일부 호출만 기록된 경우 기록 비율을 표시한다.
- 노드 상세: 노드 진입 State, 모델 호출별 프롬프트·반환 결과, State 변경을 표시한다. 모델 호출 중간의 State를 새로 추정하지 않는다. HTTP 원문과 SDK 스냅샷도 접힌 원본에서 확인할 수 있다.
- State 변화: 실행 전 필드와 `applied_update`를 비교한다. `messages`는 병합용 변경값일 수 있어 완성된 실행 후 State라고 표시하지 않는다. 노드가 반환한 `node_update`는 별도로 보존한다.
- 실행 설정: trace에 저장된 `settings`, HTTP 생성 옵션, State의 실행 예산만 표시한다. PC의 현재 `.env`를 읽거나 누락된 설정을 추정하지 않는다.
- 이전 대화: 초기 State에서 이번 질문 전까지의 사용자·Agent 메시지를 표시한다. 시작 기록이 없으면 범위를 확정하지 않고 저장된 메시지 전체를 표시한다.
- 과거 파일: trace가 없으면 연속된 결과를 노드별로 묶어 읽는다. 실제 노드 수·시간·프롬프트는 미기록으로 표시한다.

## 검증

```powershell
node --test tests/test_report_viewer_data.cjs
uv run pytest tests/test_report_html.py -q
```

데이터 검증은 중첩 토큰 집계, 실패 호출, 원본 보존, 대화 경계, HTTP 형식 차이를 확인한다. HTML 검증은 분리 소스의 포함과 데이터의 script 태그 이스케이프를 확인한다. 화면 수정 후에는 전체 입출력, 노드 이동, 호출 전환, 검색·오류 필터, 좁은 화면도 브라우저에서 확인한다.

## 글꼴과 화면 크기

본문은 16px, 보조 설명과 JSON은 14px 이상으로 표시한다. 폭 680px 이하에서는 실행 목록을 접고, 실행 선택 후 본문으로 이동한다. 긴 원문은 줄바꿈해 표시하되 복사할 때 원문을 보존한다.

공유용 HTML에는 Pretendard 글꼴과 SIL 라이선스를 포함하여 오프라인에서 같은 글꼴로 표시한다. 자산은 `assets/`에서 관리한다.
