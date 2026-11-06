# G1 B0부터 B4까지의 범위와 인계

2026-11-02 갱신: `feat/be-login`(시작 HEAD 4de5c62)에서 A1·PBKDF2·시연 seed와 prod 필수 설정 검증을 추가했다. 최신 계약은 현재 저장소의 OpenAPI 2.3.0이다. 최신 결과와 다음 작업은 [A1 인계](../a1/README.md)를 먼저 읽는다. 아래의 브랜치·2.2.0·미완료 안내는 10월 31일 기록이다.

기준일: 2026-10-31. 사용자 승인 후 `feat/be-common-foundation`에서 진행한다. 기준 develop은 `99e63564788f97fadc1327a4fe237ddf2e229125`이며 사용자가 직접 pull 후 Already up to date를 확인했다. 이후 원격 갱신·commit·push·merge는 Agent가 수행하지 않았다.

## 범위

| 블록 | 구현 대상 |
|---|---|
| B0 | 최종 계약·실행 환경·DB 권한·seed 상태 확인 |
| B1 | 공통 응답·MVC와 보안 오류·UUID 요청 추적 |
| B2 | JDBC 세션·쿠키·보호 경로·인증 저장 연결 기반 |
| B3 | CSRF 204 준비 API·SPA raw 헤더 처리 |
| B4 | Mailpit·운영 SMTP 주입·타임아웃·해시 키 설정 |

이번 작업은 G1 전체 완료가 아니다. API-39~42 지역·기관 회원 조회와 FE 공통 기반이 남는다. A1 로그인·복원·로그아웃, A2 가입·이메일 인증, A3 임시 암호·암호 변경, AI·PDF·배포는 후속 작업이다.

B0~B4의 99e6356 기반 구현·검증을 완료했다. fixture 15개, 실제 로컬 통합 4개, fixture 없는 jar HTTP 5개와 bootJar 빌드가 통과했다. 상세 범위·명령·제한은 검증 문서에서 확인한다.

후속 사용자 fetch로 origin/develop이 2ea2a28로 갱신됐으나 아직 작업 브랜치에 병합하지 않았다. 운영 환경변수 전달 보완이 필요한 상태다. 오늘은 현재 구현과 문서를 사용자가 작업 브랜치에 commit·push해 보관하고, 병합·운영 설정 보완·재검증은 내일 이어가기로 했다. 작성 당시 commit·push는 미실행이며 실제 결과는 재개 시 확인한다. [11월 1일 재개 안내](2026-11-01_이어가기.md)를 먼저 읽는다.

## 문서와 코드 위치

- [실행과 환경변수](../../README.md)
- [구현 결정](decisions.md)
- [검증 결과](verification.md)
- [작업 내용 코드 해설](작업_내용_코드_해설.md)
- [11월 1일 재개 안내](2026-11-01_이어가기.md)
- `src/main/java/com/eumi/backend/common`: 응답·오류·필터·보안 오류·메일
- `src/main/java/com/eumi/backend/auth`: CSRF·세션 principal·인증 저장·제한 세션 경계
- `src/main/java/com/eumi/backend/config`: Security와 메일·인증 키 설정
- `src/test/java/com/eumi/backend/support`: 테스트 전용 인증 fixture

로컬의 상세 착수·선행 조건·과정 기록은 저장소 상위 `산출물/개발_참조/G1_BE_공통기반/README.md`에서 시작한다. 저장소 밖 최종 계약은 같은 `개발_참조` 폴더의 openapi.json·공통_응답_및_세션_규칙.md·구현_트랜잭션_가이드.md·API_DB_매핑.md다. 이 저장소 문서는 실행·구현 인계를, 외부 작업 로그는 착수 이후의 과정을 기록한다.

## DB와 데이터 확인

실제 PostgreSQL 17.11에서 Flyway 13.11.1의 V1~V6와 afterMigrate가 종료 코드 0으로 적용됐다. eumi_app의 세션 두 테이블 DML 권한, analysis 접근 불가, Flyway 이력 접근 불가, Asia/Seoul 시간대를 읽기 전용으로 확인했다.

확인 당시 dim_region·organization·member는 각각 0건이었다. seed 폴더에는 .gitkeep만 있고 seed 경로는 비활성이다. DB·마이그레이션·infra 추적 파일과 frontend는 수정하지 않았다. 로컬의 무시되는 infra/.env는 없을 때 예제에서 생성했다.

## 다음 작업

최신 develop 반영과 운영 설정 연결 검토를 아래 후속 기능보다 먼저 진행한다. Git·추가 승인·재검증 순서는 재개 안내를 따른다.

1. 검증 문서의 실제 결과와 미검증을 확인한다.
2. API-39~42와 가짜 기관·회원 seed는 별도 승인 범위를 확인한 뒤 준비한다.
3. OPEN-04 암호 인코더·seed를 확정하고 A1의 실제 자격 검증·로그인 응답·복원·로그아웃을 구현한다.
4. A2/A3에서 인증 발급·메일 실패 롤백·세션 폐기·경합을 검증한다.
5. FE F1~F3에서 HTTP·Query·캐시·새로고침 복원과 연결하고 실제 브라우저·운영 쿠키·Nginx를 검증한다.

Jira 키·O/M/P·WBS 레이블·진행 상태는 이 작업에서 외부 시스템으로 확인하거나 변경하지 않았다. Jira 완료와 MR 병합을 수행한 것으로 기록하지 않는다.
