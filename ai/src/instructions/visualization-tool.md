# 시각화 작업 선택 시 도구 사용

적용 대상: 사용자 요청 처리 Agent, 데이터 시각화 Agent의 작업 선택 및 실행. 지침 ID: `visualization-tool`, 버전: `7`, 시행일: 2026-11-12.

## 호출

`validate_visualization`은 선택한 Tableau 뷰와 조건을 등록 설정에 대조한다. 성공하면 같은 조건의 프론트용 산출물을 반환한다. 자동 재시도·외부 API 호출·화면 렌더링은 수행하지 않는다.

도구는 현재 State의 `execution.event`로 허용 뷰를 확인한다. `event`, `state`, `allowed_view_keys`는 모델이 전달하는 도구 인자가 아니다. 아래 예시는 해당 뷰가 이번 실행의 목록에 있을 때만 사용한다.

| 입력 | 내용 |
| --- | --- |
| `view_key` | `visualization_catalog.views`에 등록된 뷰 식별자 |
| `parameters` | 해당 뷰에 등록된 모든 매개변수의 이름→문자열 값. 누락 시 `missing_parameter` 반환 |
| `filters` | 해당 뷰의 필드명→문자열 목록. 생략한 필드는 전체 선택 |

```json
{
  "view_key": "Embed01VulnerabilityMap",
  "parameters": {
    "p_city": "51110",
    "p_start": "2025-07-01",
    "p_end": "2025-12-01"
  },
  "filters": {"읍면동": ["후평3동"]}
}
```

작업 선택의 `arguments_json`에는 위 객체를 JSON 문자열로 직렬화한다. `input_result_id`, 원자료, 임의 URL·HTML·JavaScript는 전달하지 않는다. 동명이거나 소속을 확인할 수 없는 지역을 추측하지 않는다. 빈 지역 목록은 허용하지 않으며, 전체 지역은 `filters`에서 해당 필드를 생략한다.

## 검사 결과 사용

호출 결과는 이력에 기록하고 작업 진행 판단으로 전달한다. 진행 판단이 정보의 충분성과
추가 작업·사용자 정보·응답 작성 중 다음 방향을 결정한다. 작업 선택은 추가 작업을
결정한 최근 판단에 따라 아래 결과를 읽고 수정할 뷰·입력 인자를 선택한다.

| 출력 | 다음 행동 |
| --- | --- |
| `valid=true`, `artifact` 있음 | 공개 후보로 보관하며, 사용자 목적·대상·비교 기준의 충족 여부는 작업 진행 판단에서 확인 |
| `valid=false`, `issues` 있음 | 추가 작업을 결정한 경우 각 문제의 `code`, `path`, `requested`, `allowed`, `message`를 읽고 수정 인자 선택 |
| `artifact=null` | 공개 가능한 시각화가 없음. 정상 산출물로 선택하지 않음 |
| `validation_scope=registered_configuration` | 등록된 설정만 검사함. 데이터 유무·최신성·표시 성공을 의미하지 않음 |

`view_not_allowed`는 이번 이벤트에서 사용할 수 없는 뷰다. 진행 판단이 대체 작업을 결정하면 오류의 `allowed`에서 사용자 목적에 맞는 뷰를 선택한다. 이벤트를 바꾸어 재시도하지 않는다. `unknown_parameter`, `unsupported_filter`는 선택한 뷰의 등록 이름으로 수정한다. `missing_parameter`는 필수 매개변수를 확인한다. `invalid_parameter_value`는 허용값을 검토한다. `invalid_period`는 해당 날짜 쌍을 확인한다. `invalid_filter_value`는 선택한 매개변수에 따른 필터 허용값을 확인한다. `invalid_input`, `duplicate_filter_value`는 자료형·중복을 수정한다.

도구는 누락된 지역을 조용히 제외하거나 잘못된 값을 자동 보정하지 않는다. 부적합 결과에는 산출물이 없다. 같은 입력으로 반복 호출하지 않는다. 허용값이 사용자 요구와 다르면 다른 기간·지역을 임의 선택하지 않는다. 지원할 수 없는 범위·미해결 사항과 실제 Tableau 등록 설정의 차이는 진행 판단을 거쳐 응답 작성에서 설명한다.

## 공개 응답

- 도구 반환값은 해당 호출의 `results[].output`에 보존된다. 응답 작성은 검증된 호출 ID를 `artifact_ids`로 선택한다. Agent가 `artifact` 내부를 다시 작성하지 않는다.
- `artifact.type`은 `tableau`다. `artifact.data`는 뷰 주소·대상 시트·확정 매개변수·필터·설정 버전·출처를 포함한다. 프론트가 이를 채팅 카드로 렌더링한다.
- 적용한 도시·기간·읍면동과 표시 목적을 설명한다. `catalog_revision`·등록 확인 시각은 자료 버전이나 자료 갱신 시각이 아니다. 원자료의 수치·단위·최신성은 별도로 확인한 경우에만 설명한다.
- 후속 설명과 최종 응답에서 유효한 기존 차트를 유지한다. 기존 산출물의 조건을 변경했다면 새로 검증한 산출물을 선택한다.

프론트의 적용 순서·자료형·실패 처리는 `docs/agent/tableau.md`의 전달 계약을 따른다. Agent는 프론트 동작을 대신 실행하거나 실제 표시 성공을 주장하지 않는다.
