# 실행 연결 사례

수정일: 2026-11-12.

[basic.json](basic.json)은 사용자 요청 한 번 또는 한 동·월의 보고서 작성 한 번이 노드·역할을 연결하고 결과를 반환하는지 확인하는 합성 입력이다. 실제 업무 그래프와 준비한 자료를 사용하며, `assessment`의 기대 조건은 업무 State·모델 입력에 전달하지 않는다. [생성 코드](generate.py)가 입력 형식을 검사한 뒤 이 파일을 작성한다.

## 사례 구성

| 사례 ID | 실행 상황과 입력 | 확인 범위 |
| --- | --- | --- |
| `request-context` | 행정동의 월별 집계로 개인 상태를 판정할 수 있는지 묻는 요청. 별도 조회 자료원 없음 | 목적 파악·진행 판단·최종 반환, EX-1~5 |
| `request-exhausted` | 같은 요청에서 일반 단계 한도와 종료 모델 호출 예산이 이미 소진된 상태 | 새 호출 없이 한도 종료, 기존 한도·오류 보존, EX-1~5 |
| `report-start` | 대치2동의 2025년 12월 보고서 요청과 합성 점수 한 행 | 선정→설명→인사이트 역할 연결과 승인 결과·보고서 구성, EX-1~5·EX-R1~5 |
| `report-reentry` | 선정 뷰 한 개의 승인·선정 역할 완료·설명 오류 이력과 기존 누적 예산 | 선정 결과를 보존하고 설명→인사이트부터 이어 실행, EX-1~5·EX-R1~5 |

재진입 입력의 승인·오류 이력은 연결 시험을 위해 직접 준비한 자료다. 앞 사례의 실행 결과를 자동으로 가져오지 않으며 실제 모델의 선정·검토 품질을 검증한 결과도 아니다. `initial.execution`의 기존 사용량과 이력을 각 반복에 같은 조건으로 제공하고 새 실행 ID를 사용한다. 세 개 뷰를 강제로 채우거나 완성 보고서를 정답으로 주입하지 않는다. 부분 보고서의 올바른 구성과 완성률은 별도로 판정한다.

모든 사례는 필수이며 실행 전체의 적용 검사와 기대 반환 조건을 선언한다. 운영 목표와 모델·도구 단가는 지정하지 않았다. 따라서 운영 지표를 수집해도 이 입력만으로 운영 합격을 판정하지 않는다. 형식과 지표 계약은 [실행 전체 채점](../../docs/runner.md#8-실행-전체-채점), 검사 기준은 [에이전트 실행 평가](../../docs/execution/README.md)를 따른다.

## 실행

`Eumi/ai`에서 실행한다. `validate`와 입력 파일 생성은 모델을 호출하지 않는다. `run`은 `.env` 또는 `--env-file`로 지정한 설정의 실제 업무 모델을 사용하므로 모델 연결 설정이 필요하다. `dependencies=stub`도 도구·하위 호출의 응답만 교체하며 최상위 업무 모델을 대체하지 않는다.

```powershell
uv run python -m eval.scenarios.execution.generate
uv run python -m eval validate eval/scenarios/execution/basic.json
uv run python -m eval run eval/scenarios/execution/basic.json --repeat 3
uv run python -m eval score-executions <실행묶음경로>
```

`<묶음-ID>`는 `run`이 출력한 실제 경로로 바꾼다. 특정 사례만 실행하려면 `run --case <사례-ID>`를 사용한다. 실행 뒤의 `score-executions --case`·`--check`는 이미 저장된 계획 안에서 채점 범위를 좁힌다. 채점은 모델·DB를 다시 호출하지 않으며 새 평가 파일을 저장한다.

## 검증 범위

[실행기 회귀](../../tests/test_evaluation_runner.py)는 준비한 모델 응답으로 질문·취소·하위 오류 처리와 초기 State를 제공한 보고서 재진입을 확인한다. [실행 채점 연결](../../tests/test_execution_scoring.py), [규칙 검사](../../tests/test_execution_rules.py), [운영 지표](../../tests/test_execution_metrics.py), [중단 기록 복구](../../tests/test_execution_evidence.py)는 정상 증거와 의도적으로 누락·변경한 증거의 판정·집계를 확인한다.

이 자료는 연결 검사에 사용할 수 있는 시작 사례다. 입력 파일과 구현 회귀의 통과는 실제 모델 실행·응답 품질·대표 환경의 성능 검증 완료를 뜻하지 않는다. 실제 결과는 실행별 증거와 별도 채점 JSON으로 확인한다.
