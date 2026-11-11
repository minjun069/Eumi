# A2 회원가입 인계

현재 구현·검사·FE 인계는 [2026-11-11 회원가입 기록](2026-11-11_signup.md)을 따른다. 기준은 develop `aa79e3e`, 브랜치는 `feat/be-signup`, 계약은 OpenAPI 2.5.0이다.

최신 후속 작업은 A2 커밋 `205fb05`의 리뷰 F1·O1·O3을 반영한다. 기존 행이 있는 동시 재발송의 삭제 범위를 제한하고, 전화번호를 trim하며, 두 오류 문구를 현재 OpenAPI 예시와 맞췄다. O2는 유지하고 O4는 문제가 생길 때 보강하는 후속 인계다. 수정 전 재현과 수정 후 검사 결과는 위 기록 6절에서 구분한다.

| Jira | API | 성공 |
|---|---|---|
| S15P31B201-167 | API-04 GET /api/organizations | 200 기관 배열 |
| S15P31B201-167 | API-05 POST /api/signup/email-verifications | 201 expiresAt |
| S15P31B201-168 | API-06 POST /api/signup/email-verifications/verify | 200 verificationToken |
| S15P31B201-169 | API-07 POST /api/members | 201 memberId |

네 경로는 비로그인으로 사용하며 POST는 기존 CSRF 쿠키·헤더가 필요하다. 코드와 증명은 HMAC-SHA256, 비밀번호는 기존 PBKDF2로 저장한다. 인증 실패 횟수는 동일 트랜잭션 커밋 후 오류를 반환하고, 가입 증명 사전 확인을 통과한 요청만 트랜잭션 밖에서 PBKDF2를 수행한다.

DB·Mailpit은 사용자가 eumi-infra에서 준비한다. SecurityConfig·DB 마이그레이션·루트 docs·FE·Nginx는 수정하지 않았다. 구현 상태 문서 반영과 FE 연결은 병합 뒤 별도 작업이다.
