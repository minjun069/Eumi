# 전체 노드 시나리오 검토용 사본

현행 21개 시나리오에 지역 해석과 확인 대상의 구체성을 반영한 사본입니다. 사용자 요청 계열 12개와 도곡1동·대치4동·효자1동의 보고서 역할별 9개를 포함합니다. 원본과 이전 검토 사본은 보존하며, 도곡1동의 승인된 보고서 설명·퀵 인사이트와 사용자 요청 예시는 유지합니다.

[전체 시나리오 색인](scenarios.json)에서 각 경로의 시작 입력, 분석·선정 과정, 작성·검토 응답, 최종 반환을 확인할 수 있습니다. `scenarios/`의 각 파일은 하나의 역할이 진입해 반환하는 전체 경로입니다. 과거 예외·부분 사례 보관본은 이번 현행 21개에 포함하지 않습니다.

## 구성

| 구분 | 범위 | 수 |
| --- | --- | ---: |
| 사용자 요청 처리 | 이전 대화 없음·새 주제·기존 응답 수정·보완 답변 완료 | 4 |
| 데이터 분석 결과 해석 | 같은 대화 조건 4가지 | 4 |
| 데이터 시각화 | 같은 대화 조건 4가지 | 4 |
| 보고서 | 세 지역의 시각화 선정·설명·퀵 인사이트 | 9 |

| 지역 | 시각화 선정 | 시각화 설명 | 퀵 인사이트 |
| --- | --- | --- | --- |
| 도곡1동 | [열기](scenarios/candidate-report-selection-1168065500.json) | [열기](scenarios/candidate-report-description-1168065500.json) | [열기](scenarios/candidate-report-insight-1168065500.json) |
| 대치4동 | [열기](scenarios/candidate-report-selection-1168063000.json) | [열기](scenarios/candidate-report-description-1168063000.json) | [열기](scenarios/candidate-report-insight-1168063000.json) |
| 효자1동 | [열기](scenarios/candidate-report-selection-5111062000.json) | [열기](scenarios/candidate-report-description-5111062000.json) | [열기](scenarios/candidate-report-insight-5111062000.json) |

## 평가 입력과 근거

독립 노드 입력과 기대조건은 [목적 파악](interpret.json), [진행 판단](decide.json), [도구·에이전트 호출](act.json), [응답 작성](compose.json), [추가 질문](ask.json)에 있습니다. 추가 질문 파일에는 정상 완료 조건상 사례가 없습니다. 보고서 내부 작성·검토 30회는 [별도 호출 묶음](report-calls.json)으로 제공합니다. 이 중 각 역할의 최초 작성 9회는 노드 묶음과 중복하므로 사례 수에 합산하지 않습니다.

해석 평가는 수치의 정확성에 더해 관측 사이의 관계, 시간·집단·공간 비교가 바꾸는 상황 해석, 필요한 확인 대상과 조건을 봅니다. 숫자와 주의문만 나열한 답변을 충분한 해석으로 인정하지 않습니다. 지도 표시와 표현 수정 요청에는 요청하지 않은 분석을 강제하지 않습니다. [보고서 품질 기준](report-quality-criteria.json)과 각 사례의 `assessment`는 모델 입력과 분리합니다.

[자료 스냅샷](snapshots/data.json)은 원본 측정 자료를 유지하고 세 지역의 2025년 7~12월 실제 활동 집계·원지표 18행과 지표 정의를 보완합니다. [조회 증거](snapshots/activity-evidence.json)에 읽기 전용 SQL, 정확한 소수 값, 수집 시각과 해시를 보존합니다. 성별·시간대·요일별 상세 활동 자료는 없으며, 성별 절대 감소나 격자의 주거지 여부·현장 변화는 확인된 사실로 작성하지 않습니다.

## 재생성과 검증

`Eumi/ai/`에서 실행합니다. 재생성은 저장한 자료를 사용하며 DB나 외부 모델에 접속하지 않습니다.

```powershell
.venv/Scripts/python.exe eval/scenarios/nodes-insight-all/build_dataset.py
```

[검증 결과](validation.json)는 원본·승인 문안 보존, 21개 경로의 구성, 실제 노드·조회·가공 실행, 수치와 문장 수를 기록합니다. [입력 검증](input-validation.json)은 이력의 조회·가공 재현과 평가 메타데이터의 모델 입력 유입 여부를 확인합니다. [호출별 검증](report-call-coverage.json)은 보고서의 내부 작성·검토 입력을 따로 확인합니다. 외부 업무 모델·평가 모델의 자율 실행 품질 평가는 미실행입니다.

기존 선정→설명→인사이트 역할과 State 전달 계약, 공통 검사 ID를 유지합니다. 적용 기준은 [업무 범위](../../../docs/agent/scope.md), [보고서 명세](../../../docs/agent/report.md), [노드 평가](../../docs/nodes/README.md)입니다.
