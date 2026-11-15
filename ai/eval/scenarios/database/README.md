# DB 조회 평가 자료

수정일: 2026-11-11.

[service-query.json](service-query.json)은 별도 평가 DB `eumi_eval`에 적재할 합성 원시 행과 서비스 조회 공급자 4종의 필수 사례 8개를 함께 담는다. 설정·실행 조건은 [평가 실행기](../../docs/runner.md)를 따른다.

두 합성동·두 기준월, 세 격자를 사용한다. 행정동과 격자 기준, 동별 분석 결과, 지표 기여도, 격자 이상 점수, 유동 상세를 6개 테이블에 적재한다. 모든 행에 열과 수정 시각을 명시한다. 조건 조회·정렬·반환 열·정상 0건·두 페이지와 격자 결합·동별 활동량 합산을 확인한다.

[생성 코드](generate_service_query.py)는 DB나 서비스 함수를 호출하지 않고 고정 원시 행과 별도 계산표로 기대값을 만든다. 예를 들어 10월 평가동 A의 08시 활동량은 `300/30 + 620/31 = 30`, 11월은 `60/30 + 90/30 = 5`다. 11월 월요일은 한 격자의 분모가 0이므로 전체 그룹을 `null`로 기대한다. 다음 페이지의 버전은 정렬된 독립 정답 행을 직렬화한 SHA-256이다.

`Eumi/ai`에서 실행한다. `eval/.env.evaluation-seed`는 평가 자료 준비 계정, `eval/.env.evaluation`은 평가 조회 계정의 DB 연결 설정이다.

```powershell
uv run python -m eval validate eval/scenarios/database/service-query.json
uv run python -m eval prepare-db eval/scenarios/database/service-query.json --env-file eval/.env.evaluation-seed
uv run python -m eval run eval/scenarios/database/service-query.json --env-file eval/.env.evaluation --repeat 3 --output eval/outputs/database-evaluations
uv run python -m eval score eval/outputs/database-evaluations/<묶음-ID>
```

생성 코드의 원시 행이나 기대값을 수정한 뒤에는 `uv run python eval/scenarios/database/generate_service_query.py`로 JSON을 다시 생성한다.
