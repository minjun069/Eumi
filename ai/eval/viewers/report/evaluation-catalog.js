/* eval/의 평가 단위별 표시 기준. 런타임 State나 평가기 실행에는 관여하지 않는다. */
globalThis.EvaluationCatalog = {
  "tools": {
    "label": "도구",
    "description": "도구별 호출의 입력 처리, 실제 결과와 반환 내용, 운영값을 확인한다.",
    "metrics": [
      {
        "name": "입력 처리 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "T-I.1·.2",
        "unit": "입력 항목",
        "numerator": "통과한 입력 항목 수",
        "denominator": "판정한 입력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "도구 출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "T-O 전체, T03-O.1",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "target_ids": ["T04"],
        "checks": "T04-B.1",
        "unit": "저장 작업",
        "numerator": "적용 행동을 모두 통과한 저장 작업 수",
        "denominator": "평가한 저장 작업 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 저장 작업 식별자별로 집계한다. 저장 도구를 채택하지 않았다면 비적용이다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "호출 응답시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.1",
        "unit": "도구 호출",
        "criterion": "사전 필수 지정 도구의 p95가 최대 허용값 이하",
        "note": "호출 시작부터 반환까지 측정해 성공·오류별 중앙값과 p95를 계산한다. 시간·비용은 사전 필수 지정 시에만 합격에 반영한다. 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "호출 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "도구 호출",
        "criterion": "사전 필수 지정 도구의 호출별 비용이 최대 허용값 이하",
        "note": "호출에서 사용한 모델·외부 서비스 사용량에 시험 당시 단가를 곱한다. 내부 재시도 비용을 포함한다. 시간·비용은 사전 필수 지정 시에만 합격에 반영한다."
      },
      {
        "name": "기술적 실행 실패율",
        "group": "operational",
        "kind": "ratio",
        "checks": "O02.1",
        "unit": "도구 호출",
        "numerator": "기술 장애로 실패 종료한 호출 수",
        "denominator": "종료한 호출 수",
        "criterion": "사전 필수 지정 도구의 최대 허용 비율 이하",
        "note": "정상 거부·취소는 실패 분자에서 제외한다. 결함 주입 시험은 일반 운영 실패율과 분리한다. 사전 필수 지정 대상만 합격에 반영한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 필수 기능 검사를 통과한 사례 수",
        "denominator": "반복에 배정한 핵심 사례 수",
        "criterion": "사전 필수 지정 도구의 핵심 사례 100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 사전 필수 지정 대상만 합격에 반영한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  },
  "nodes": {
    "label": "노드",
    "description": "실행 단계별 판단·출력·상태 기록과 행동을 확인한다. 진행 판단 진단값은 따로 표시한다.",
    "metrics": [
      {
        "name": "노드 출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "N의 O 검사",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "실행 상태 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "N-S.1~.3",
        "unit": "필드·기록 항목",
        "numerator": "통과한 필드 또는 기록 항목 수",
        "denominator": "판정한 필드 또는 기록 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "checks": "N의 B 검사",
        "unit": "노드 실행",
        "numerator": "적용 행동을 모두 통과한 노드 실행 수",
        "denominator": "평가한 노드 실행 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "분기 정확도",
        "group": "functional",
        "kind": "ratio",
        "target_ids": ["N03"],
        "checks": "N03-O.3",
        "unit": "진행 판단 실행",
        "numerator": "기대 방향과 일치한 판단 수",
        "denominator": "판정 가능한 진행 판단 실행 수",
        "criterion": "진단용; 출력 정확도에 중복 합산하지 않음",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 진단용 지표이며 출력 정확도에 다시 합산하지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "진행 장애 탐지율",
        "group": "functional",
        "kind": "ratio",
        "target_ids": ["N03"],
        "checks": "N03-O.4",
        "unit": "삽입 장애",
        "numerator": "위치까지 정확하게 식별한 장애 수",
        "denominator": "삽입한 장애 수",
        "criterion": "진단용; 출력 정확도에 중복 합산하지 않음",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 진단용 지표이며 출력 정확도에 다시 합산하지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "정상 통과율",
        "group": "functional",
        "kind": "ratio",
        "target_ids": ["N03"],
        "checks": "N03-O.3",
        "unit": "작성 가능 사례",
        "numerator": "작성 가능으로 판단한 실행 수",
        "denominator": "사전 지정한 작성 가능 사례 수",
        "criterion": "진단용; 출력 정확도에 중복 합산하지 않음",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 진단용 지표이며 출력 정확도에 다시 합산하지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "호출 응답시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.1",
        "unit": "노드 호출",
        "criterion": "사전 필수 지정 노드의 p95가 최대 허용값 이하",
        "note": "진입부터 반환까지의 중앙값과 p95를 성공·오류별로 계산한다. 하위 호출 시간을 다시 더하지 않는다. 시간·비용은 사전 필수 지정 시에만 합격에 반영한다. 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "호출 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "노드 호출",
        "criterion": "사전 필수 지정 노드의 호출별 비용이 최대 허용값 이하",
        "note": "모델·외부 서비스 사용량에 시험 당시 단가를 곱한다. 하위·수정·재시도 비용을 각각 한 번 포함한다. 시간·비용은 사전 필수 지정 시에만 합격에 반영한다."
      },
      {
        "name": "기술적 실행 실패율",
        "group": "operational",
        "kind": "ratio",
        "checks": "O02.1",
        "unit": "노드 실행",
        "numerator": "기술 장애로 실패 종료한 호출 수",
        "denominator": "종료한 호출 수",
        "criterion": "사전 필수 지정 노드의 최대 허용 비율 이하",
        "note": "정상 거부·취소는 실패 분자에서 제외한다. 결함 주입 시험은 일반 운영 실패율과 분리한다. 사전 필수 지정 대상만 합격에 반영한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 필수 기능 검사를 통과한 사례 수",
        "denominator": "반복에 배정한 핵심 사례 수",
        "criterion": "사전 필수 지정 노드의 핵심 사례 100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 사전 필수 지정 대상만 합격에 반영한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  },
  "interpretation": {
    "label": "데이터 분석 결과 해석",
    "description": "상위에서 맡긴 해석 작업의 주요 신호, 비교 근거와 해석 범위를 확인한다.",
    "metrics": [
      {
        "name": "해석 완료율",
        "group": "functional",
        "kind": "ratio",
        "checks": "필수 결과의 출력 검사",
        "unit": "해석 작업",
        "numerator": "필수 내용을 모두 제공하고 해당 산출물의 필수 검사를 통과한 작업 수",
        "denominator": "접수한 해석 작업 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 올바른 부분·불가·거부·되묻기는 행동 검사에 통과할 수 있지만 완료·해결로 세지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "입력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-I.1",
        "unit": "입력 항목",
        "numerator": "통과한 입력 항목 수",
        "denominator": "판정한 입력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "출력 평가의 O 검사",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "상태 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-S.1",
        "unit": "상태 항목",
        "numerator": "통과한 상태 항목 수",
        "denominator": "판정한 상태 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "checks": "행동 평가의 B 검사",
        "unit": "해석 작업",
        "numerator": "적용 행동을 모두 통과한 작업 수",
        "denominator": "평가한 작업 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 일치율",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.4~.7",
        "unit": "주장",
        "numerator": "적용 기준을 모두 충족한 주장 수",
        "denominator": "판정한 주장 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "주장별 적용 검사 중 하나라도 실패하면 실패다. 실패 없이 미판정·미실행이 남으면 분모에서 제외한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 연결률",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.8~.10",
        "unit": "출처 필요 항목",
        "numerator": "출처 기준을 모두 충족한 항목 수",
        "denominator": "출처가 필요한 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "해석 응답시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.1",
        "unit": "작업 1건",
        "criterion": "사전 필수 지정 시 p95가 최대값 이하",
        "note": "호출 접수부터 상위 반환까지의 시간을 성공·오류별 중앙값·p95로 집계 시간·비용은 사전 필수 지정 시에만 합격에 반영한다. 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "해석 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "작업 1건",
        "criterion": "사전 필수 지정 시 작업별 최대값 이하",
        "note": "모델·도구 사용량에 시험 단가 적용. 보완·재시도 포함 시간·비용은 사전 필수 지정 시에만 합격에 반영한다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 필수 기능 검사를 통과한 핵심 사례 수",
        "denominator": "반복 대상 핵심 사례 수",
        "criterion": "100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  },
  "visualization": {
    "label": "데이터 시각화",
    "description": "시각화 작업의 뷰·표시 조건과 반환 설정을 확인하고 실제 화면 연동은 별도로 판정한다.",
    "metrics": [
      {
        "name": "시각화 설정 완료율",
        "group": "functional",
        "kind": "ratio",
        "checks": "필수 결과의 출력 검사, A02 검사",
        "unit": "시각화 작업",
        "numerator": "요청 조건에 맞는 유효 산출물·안내를 제공하고 필수 검사를 통과한 작업 수",
        "denominator": "접수한 시각화 작업 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 올바른 부분·불가·거부·되묻기는 행동 검사에 통과할 수 있지만 완료·해결로 세지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "입력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-I.1",
        "unit": "입력 항목",
        "numerator": "통과한 입력 항목 수",
        "denominator": "판정한 입력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "출력 평가의 O 검사",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "상태 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-S.1",
        "unit": "상태 항목",
        "numerator": "통과한 상태 항목 수",
        "denominator": "판정한 상태 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "checks": "행동 평가의 B 검사",
        "unit": "시각화 작업",
        "numerator": "적용 행동을 모두 통과한 작업 수",
        "denominator": "평가한 작업 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 일치율",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.4~.7",
        "unit": "주장",
        "numerator": "적용 기준을 모두 충족한 주장 수",
        "denominator": "판정한 주장 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "주장별 적용 검사 중 하나라도 실패하면 실패다. 실패 없이 미판정·미실행이 남으면 분모에서 제외한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 연결률",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.8~.10",
        "unit": "출처 필요 항목",
        "numerator": "출처 기준을 모두 충족한 항목 수",
        "denominator": "출처가 필요한 항목 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "설정 응답시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.1",
        "unit": "작업 1건",
        "criterion": "사전 필수 지정 시 p95가 최대값 이하",
        "note": "호출 접수부터 산출물·안내 반환까지의 시간을 성공·오류별 중앙값·p95로 집계 시간·비용은 사전 필수 지정 시에만 합격에 반영한다. 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "설정 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "작업 1건",
        "criterion": "사전 필수 지정 시 작업별 최대값 이하",
        "note": "모델·도구 사용량에 시험 단가 적용. 보완·재시도 포함 시간·비용은 사전 필수 지정 시에만 합격에 반영한다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 필수 기능 검사를 통과한 핵심 사례 수",
        "denominator": "반복 대상 핵심 사례 수",
        "criterion": "100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "화면 연동 준수율",
        "group": "integration",
        "kind": "ratio",
        "checks": "§3의 적용 검사",
        "unit": "표시 실행",
        "numerator": "적용 화면 검사를 모두 통과한 표시 실행 수",
        "denominator": "평가한 표시 실행 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  },
  "user-request": {
    "label": "사용자 요청 처리",
    "description": "질문별 답변·작업·상태·서비스 연동을 확인한다. 대화 시나리오는 질문과 별도로 집계한다.",
    "metrics": [
      {
        "name": "요청 해결률",
        "group": "functional",
        "kind": "ratio",
        "checks": "필수 결과의 출력 검사",
        "unit": "질문",
        "numerator": "필수 답변·산출물과 내용 검사를 모두 충족한 질문 수",
        "denominator": "접수한 평가 대상 질문 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 올바른 부분·불가·거부·되묻기는 행동 검사에 통과할 수 있지만 완료·해결로 세지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "대화 해결률",
        "group": "functional",
        "kind": "ratio",
        "checks": "대화별 완료 기준, 질문별 출력 검사",
        "unit": "대화 시나리오",
        "numerator": "사전에 정한 대화 전체 목적을 해결한 시나리오 수",
        "denominator": "배정한 대화 시나리오 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 질문별 요청 해결률과 합산하지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "입력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-I.1",
        "unit": "입력 항목",
        "numerator": "통과한 입력 항목 수",
        "denominator": "판정한 입력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "§2.2의 O 검사",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "상태 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "§2.3의 S 검사",
        "unit": "상태 항목",
        "numerator": "통과한 상태 항목 수",
        "denominator": "판정한 상태 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "checks": "§2.4의 B 검사",
        "unit": "질문 실행",
        "numerator": "적용 행동을 모두 통과한 질문 실행 수",
        "denominator": "평가한 질문 실행 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 일치율",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.4~.7, A03-O.1",
        "unit": "주장",
        "numerator": "적용 검사를 모두 통과한 주장 수",
        "denominator": "판정한 주장 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "주장별 적용 검사 중 하나라도 실패하면 실패다. 실패 없이 미판정·미실행이 남으면 분모에서 제외한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "첫 유효 응답시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.2",
        "unit": "질문",
        "criterion": "질문 유형별 p95가 사전 최대값 이하",
        "note": "요청 수신부터 첫 중간 결과·최종 답변·되묻기 제공까지 측정. 접수·진행 문구 제외 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "종료시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.3",
        "unit": "질문",
        "criterion": "실행 마감과 사전 종료시간 목표 충족",
        "note": "요청 수신부터 끝 행 커밋까지 측정. 접수 준비와 진행 저장·알림 포함 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "질문 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "질문",
        "criterion": "질문 유형별 사전 최대값 이하",
        "note": "모델·외부 서비스 사용량에 시험 당시 단가 적용. 하위·수정·재시도 포함"
      },
      {
        "name": "기술 실패율",
        "group": "operational",
        "kind": "ratio",
        "checks": "O02.1",
        "unit": "질문",
        "numerator": "기술 장애로 실패 종료한 질문 수",
        "denominator": "종료한 질문 수",
        "criterion": "사전 최대 비율 이하",
        "note": "정상 거부·취소는 실패 분자에서 제외한다. 결함 주입 시험은 일반 운영 실패율과 분리한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 기능 검사를 통과한 핵심 사례 수",
        "denominator": "반복에 배정한 핵심 사례 수",
        "criterion": "100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 연결률",
        "group": "integration",
        "kind": "ratio",
        "checks": "A-O.8·.10, S08-O.5",
        "unit": "출처 필요 항목",
        "numerator": "출처 제공·일치·접근을 모두 통과한 항목 수",
        "denominator": "출처가 필요한 항목 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "연동 준수율",
        "group": "integration",
        "kind": "ratio",
        "checks": "서비스 연동 검사",
        "unit": "질문 실행",
        "numerator": "적용 검사를 모두 통과한 질문 실행 수",
        "denominator": "평가한 질문 실행 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  },
  "report": {
    "label": "세부 대시보드 보고서",
    "description": "선정·설명·인사이트 에이전트의 판단·산출물을 각각 확인하고, 순차 실행·전달·공유 예산·부분 처리와 생성 요청의 저장·알림·화면 연동을 별도로 확인한다. 역할별 검사 배정은 eval/docs/report.md를 따른다.",
    "metrics": [
      {
        "name": "보고서 완성률",
        "group": "functional",
        "kind": "ratio",
        "checks": "R01~R05, A-O",
        "unit": "동별 보고서",
        "numerator": "뷰 3개·설명·인사이트와 필수 검사를 충족한 보고서 수",
        "denominator": "접수한 평가 대상 동별 보고서 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 적절한 부분 반환은 기능 검사에 통과할 수 있지만 완성률 분자에 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "입력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "R01-I.1, F01-I.1",
        "unit": "입력 항목",
        "numerator": "통과한 입력 항목 수",
        "denominator": "판정한 입력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "출력 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "R·A의 O 검사",
        "unit": "출력 항목",
        "numerator": "통과한 출력 항목 수",
        "denominator": "판정한 출력 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "상태 정확도",
        "group": "functional",
        "kind": "ratio",
        "checks": "F01-S.1, R02-S.1, R03-S.1, R05-S.1·.2",
        "unit": "상태 항목",
        "numerator": "통과한 상태 항목 수",
        "denominator": "판정한 상태 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행을 분모에서 제외하고 건수를 별도 기록한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "행동 준수율",
        "group": "functional",
        "kind": "ratio",
        "checks": "§2.4의 B 검사",
        "unit": "동별 실행",
        "numerator": "적용 행동을 모두 통과한 동별 실행 수",
        "denominator": "평가한 동별 실행 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 일치율",
        "group": "functional",
        "kind": "ratio",
        "checks": "A-O.4~.7, R03-O.3",
        "unit": "주장",
        "numerator": "적용 검사를 모두 통과한 주장 수",
        "denominator": "판정한 주장 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "주장별 적용 검사 중 하나라도 실패하면 실패다. 실패 없이 미판정·미실행이 남으면 분모에서 제외한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "검토 결함 탐지율",
        "group": "functional",
        "kind": "ratio",
        "checks": "R04-O.1·.2",
        "unit": "삽입 결함",
        "numerator": "정확히 식별한 결함 수",
        "denominator": "사전에 삽입한 결함 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "정상 초안 승인율",
        "group": "functional",
        "kind": "ratio",
        "checks": "R04-O.1",
        "unit": "정상 초안",
        "numerator": "올바르게 승인한 정상 초안 수",
        "denominator": "사전에 지정한 정상 초안 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "수정 성공률",
        "group": "functional",
        "kind": "ratio",
        "checks": "R04-O.3, 수정본의 출력 검사",
        "unit": "수정 평가 항목",
        "numerator": "지적 결함을 해소하고 내용·형식을 충족한 항목 수",
        "denominator": "수정 평가에 배정한 항목 수",
        "criterion": "필수 사례의 해당 검사 모두 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "동별 처리시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.4",
        "unit": "동별 보고서",
        "criterion": "활성 한도 준수 및 사전 시간 목표 충족",
        "note": "실행 자리 대기·최초 분석 확인·노드 활성·최종 저장 시간을 각각 측정하고 중앙값·p95 산출 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "전체 처리시간",
        "group": "operational",
        "kind": "measurement",
        "checks": "O01.5",
        "unit": "생성 요청",
        "criterion": "동 수·동시성별 사전 최대값 이하",
        "note": "요청 수신부터 모든 동 처리·저장 재시도 후 완료 알림 결과 확정까지 측정 미종료 대상은 시간 통계에서 제외하고 건수·경과 시간을 별도 기록한다."
      },
      {
        "name": "동별 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.1",
        "unit": "동별 보고서",
        "criterion": "사전 동별 최대값 이하",
        "note": "모델·외부 서비스 사용량에 시험 당시 단가 적용. 수정·재처리 포함"
      },
      {
        "name": "전체 비용",
        "group": "operational",
        "kind": "measurement",
        "checks": "O03.2",
        "unit": "생성 요청",
        "criterion": "요청 규모별 사전 최대값 이하",
        "note": "동별 비용과 공통 외부 비용을 중복 없이 합산"
      },
      {
        "name": "기술 실패율",
        "group": "operational",
        "kind": "ratio",
        "checks": "O02.1",
        "unit": "동별 업무",
        "numerator": "기술 장애로 실패 종료한 동별 업무 수",
        "denominator": "종료한 동별 업무 수",
        "criterion": "사전 최대 비율 이하",
        "note": "정상 거부·취소는 실패 분자에서 제외한다. 결함 주입 시험은 일반 운영 실패율과 분리한다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "반복 충족률",
        "group": "operational",
        "kind": "ratio",
        "checks": "O04.1",
        "unit": "핵심 사례",
        "numerator": "모든 반복에서 기능 검사를 통과한 핵심 사례 수",
        "denominator": "반복에 배정한 핵심 사례 수",
        "criterion": "100%",
        "note": "모든 반복에서 필수 검사를 통과한 사례만 분자에 넣는다. 반복 미실행·미판정 사례는 분모에 남긴다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "저장 성공률",
        "group": "integration",
        "kind": "ratio",
        "checks": "S04-O.2·.3, S07-O.2",
        "unit": "동별 보고서",
        "numerator": "실제 커밋과 저장값을 확인한 보고서 수",
        "denominator": "접수한 평가 대상 동별 보고서 수",
        "criterion": "합격 판정과 별도 보고",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 완성·부분 저장을 구분한다. 완성 2개와 부분 1개를 모두 저장하면 저장률은 3/3이다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "근거 연결률",
        "group": "integration",
        "kind": "ratio",
        "checks": "A-O.8·.10, S08-O.5",
        "unit": "출처 필요 항목",
        "numerator": "출처 제공·일치·접근을 모두 통과한 항목 수",
        "denominator": "출처가 필요한 항목 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      },
      {
        "name": "연동 준수율",
        "group": "integration",
        "kind": "ratio",
        "checks": "서비스 연동 검사",
        "unit": "생성 요청",
        "numerator": "적용 검사를 모두 통과한 생성 요청 수",
        "denominator": "평가한 생성 요청 수",
        "criterion": "합격 판정의 해당 출처·연동 검사 통과",
        "note": "미판정·미실행 대상은 분모에 남기고 분자에는 넣지 않는다. 비적용은 사유와 함께 제외하며 분모 0은 산출 불가다."
      }
    ]
  }
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = globalThis.EvaluationCatalog;
}
