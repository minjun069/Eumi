# 평가 결과 조회

결과 뷰어는 저장된 실행·채점 결과를 읽어 표시하며 원본 결과와 업무 실행 상태를 변경하지 않는다. 평가 실행과 채점은 [평가 실행 안내](../README.md)를 따른다.

Codex 브라우저의 주석 선택 기능을 위해 세 로컬 평가 뷰어의 CSP는 `style-src 'self' 'unsafe-inline'`을 유지하고, `script-src 'self'` 제한은 그대로 둔다.

| 위치 | 책임 |
| --- | --- |
| [results](results/README.md) | 실행 결과와 도구 채점 조회 |
| [nodes](nodes/README.md) | 노드·역할별 채점과 모델 호출 근거 조회 |
| [execution](execution/README.md) | 에이전트·보고서 실행 전체의 기능·운영 평가 조회 |
| [report](report/README.md) | 공용 실행 모니터의 평가 탭과 화면 예시 |
| `shared/` | 세 평가 뷰어가 함께 사용하는 파일 조회·이름 표시와 검증 준비 코드 |
| [catalog.py](catalog.py) | 저장 결과의 경로·크기와 묶음·채점 JSON의 식별 정보 목록 생성 |

`Eumi/ai`에서 `python -m http.server 8872 --bind 127.0.0.1`을 실행한 뒤 원하는 뷰어의 사용 안내에 적힌 주소를 연다. 목록은 `eval/outputs/evaluation-viewer/catalog.json`, 원본 결과는 `eval/outputs/evaluations/`와 `eval/outputs/database-evaluations/`를 사용한다. 수동으로 추가한 결과의 목록은 `python -m eval.viewers.catalog`로 갱신한다.

목록의 묶음별 `node_targets`는 노드 이름 표시에 쓰는 선택 메타데이터다. `batch.json`의 등록 실행 중 `unit`이 `node`인 항목의 문자열 `target`만 중복 없이 정렬해 기록한다. 해당 실행이 없으면 빈 목록이며, 이전에 생성한 목록에는 이 항목이 없을 수 있다.

공용 실행 기록 화면은 [report_viewer.html](../../report_viewer.html), HTML 생성기는 [report_html.py](../../report_html.py)를 사용한다. 평가 전용 표시 코드는 `report/`에 두고 기존 실행·평가 파일 표시 순서와 입력 형식을 유지한다.
