# 작업 선택 및 실행

상태: 검토용 명세. 수정일: 2026-11-12.

[노드 평가 개요·지표·합격 판정](README.md) · [공통 평가 기준](common.md)

## 평가 범위

작업 선택 및 실행 노드(N02)가 최근 진행 판단에 따라 반환한 작업·호출 대상·입력 인자·선택 이유를 평가한다.

## 출력 형식

출력 형식은 [정형 평가 정의](act.json)의 관련 원칙을 따른다.

### 반환 구조

반환 구조는 [정형 평가 정의](act.json)의 `output-action` 원칙을 따른다.

### 호출 인자

호출 인자는 [정형 평가 정의](act.json)의 `arguments-common`과 호출 대상별 `arguments-query`, `arguments-process`, `arguments-visualization`, `arguments-agent` 원칙을 따른다.

#### 조건·정렬 객체

조건·정렬 객체는 [정형 평가 정의](act.json)의 `argument-conditions` 원칙을 따른다.

#### 가공 연산 객체

가공 연산 객체는 [정형 평가 정의](act.json)의 `arguments-process` 원칙을 따른다.

#### 시각화 입력 프로필

시각화 입력 프로필은 [정형 평가 정의](act.json)의 `arguments-visualization` 원칙을 따른다.

## 전용 검사

검사 정의의 단일 원본은 [정형 평가 정의](act.json)다. 이관 내용은 [원본 Markdown 보관본](originals/act.md)과 대조한다.

입력·설정 검사 도구의 판정 정확성은 [도구 평가](../tools.md)에서 확인한다. 선택한 출력대로 검사·호출하고 결과를 기록하는 동작은 이 노드의 책임이며, 현재 모델 출력 검사와 내부 실행 검사의 정비 범위는 [노드 평가 대상](README.md#대상)을 따른다.
