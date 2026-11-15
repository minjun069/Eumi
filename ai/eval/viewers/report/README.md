# 실행 모니터의 평가 표시

[공용 실행 모니터](../../../report_viewer/README.md)의 평가 탭에 사용하는 파일이다. 모델·도구를 실행하거나 채점하지 않고 저장된 평가 지표·판정·근거를 표시한다.

| 파일 | 책임 |
| --- | --- |
| [evaluation-catalog.js](evaluation-catalog.js) | 평가 단위별 표시 지표와 적용 대상 |
| [evaluation.js](evaluation.js) | 평가 파일 검사, 실행 범위와 검사·지표 연결 |
| [evaluation-view.js](evaluation-view.js) | 지표·사례 선택과 판정 근거 표시 |
| [evaluation-sample.json](evaluation-sample.json), [evaluation-user-request-sample.json](evaluation-user-request-sample.json) | 과거 실행 증거를 사용한 화면 예시. 실제 품질 채점과 구분 |

[report_viewer.html](../../../report_viewer.html)은 이 스크립트를 직접 읽으며, [report_html.py](../../../report_html.py)는 공용 화면 코드와 함께 HTML 한 파일에 포함한다. 입력 형식·표시 기준·샘플 생성 방법은 [실행 모니터 안내](../../../report_viewer/README.md)를 따른다.
