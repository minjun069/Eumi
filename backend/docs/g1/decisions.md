# G1 공통 기반 구현 결정

기준일: 2026-10-31. 정책은 전달받은 최종 계약을 적용하며 아래 구현 방식은 승인된 B0~B4 안에서 선택했다.

| ID | 결정 | 이유와 후속 영향 |
|---|---|---|
| DEC-001 | 최종 API 기준 info.version 2.2.0, 물리 DB·권한은 develop SQL | SQL 사본 8개 동일 확인. 정책·SQL 충돌을 임의로 수정하지 않음 |
| DEC-002 | 서버가 UUID를 생성하고 헤더·본문·MDC에 같은 requestId 사용 | 클라이언트가 준 ID를 인증·추적 근거로 신뢰하지 않음. MDC는 요청 후 정리 |
| DEC-003 | 응답 factory와 공통 오류 모델 사용 | Health·204·SSE·파일을 자동 포장하지 않음. 새 JSON 업무 컨트롤러는 ApiResponse 사용 |
| DEC-004 | MVC advice·Security 오류 작성기·Servlet error controller를 분리 | 필터 오류와 기본 HTML 오류도 계약 JSON으로 전달. 예외·입력 원문은 노출하지 않음 |
| DEC-005 | Boot Session JDBC 스타터와 기존 Flyway 테이블 사용 | initialize-schema=never. principal은 member_id 문자열. 별도 스키마·Flyway 의존성 없음 |
| DEC-006 | SessionAuthenticationSupport에서 전략 실행 후 명시적 Context 저장 | 실제 A1은 자격 확인 후 호출. ID 교체·CSRF 정리 연결을 fixture로 검증 |
| DEC-007 | Spring Security 7.1 내장 csrf.spa() 사용 | 별도 SPA 처리기를 복제하지 않음. 쿠키 저장소의 Path=/·Lax·Secure는 명시 설정 |
| DEC-008 | 공개 경로를 메서드와 정확한 경로로 열고 나머지는 인증 | /auth/me·하위 기관 회원 조회까지 공개되는 실수를 방지. Basic·폼·기본 logout·요청 캐시는 비활성 |
| DEC-009 | 제한 principal의 업무 접근을 별도 필터에서 차단 | 실제 제한 여부·회원 활성 상태는 A1/A3에서 최신 DB로 확인. CSRF 실패는 CSRF 코드 유지 |
| DEC-010 | Boot 기본 사용자 자동 생성 제외 | 사용하지 않는 메모리 계정과 무작위 암호 로그를 만들지 않음. 실제 자격 검증은 A1 |
| DEC-011 | SMTP·해시 키 변수 이름을 승인안으로 통일 | 운영 주입은 별도 인프라 담당 작업. 실제 비밀값 기록 금지 |
| DEC-012 | SMTP 연결·읽기·쓰기 각 5초, 실패는 안전한 500 코드로 변환 | 수신자·본문·SMTP 예외 원문은 로그에 남기지 않음. DB rollback·최종 배달은 A2/A3 후속 검증 |
| DEC-013 | test와 integrationTest를 분리 | fixture 검사와 실제 PostgreSQL·HTTP·Mailpit 검사를 혼동하지 않음 |
| DEC-014 | CSRF fixture도 실제 cookie와 raw header 사용 | 테스트 보조기가 토큰 저장소를 바꾸는 순서 의존성을 제거. MockMvc 요청 출력은 꺼서 쿠키 기록 방지 |
| DEC-015 | 유효 CSRF 쿠키의 준비 재호출은 기존 토큰을 유지 | 매번 회전하면 병행 요청을 깨뜨릴 수 있다. 신규 발급과 재호출을 구분해 검사하며 로그인 등 인증 전환에서는 별도 정리·재준비 |
| OPEN-04 | 암호 인코더·BCrypt seed 정합성은 미결정 | 8~128자 계약을 축소하거나 조용히 자르지 않음. A1/A3 전에 결정 |

## 공식 근거

- [Boot Session JDBC](https://docs.spring.io/spring-boot/reference/web/spring-session.html)
- [Spring Session JDBC](https://docs.spring.io/spring-session/reference/configuration/jdbc.html)
- [Security SPA CSRF](https://docs.spring.io/spring-security/reference/servlet/exploits/csrf.html)
- [Security 인증 저장](https://docs.spring.io/spring-security/reference/servlet/authentication/session-management.html)
- [Boot 메일과 타임아웃](https://docs.spring.io/spring-boot/reference/io/email.html)

문서 조회 당시 Boot 4.1.2·Security 7.1.2·Session 4.1.1을 확인했다. 최종 의존성은 Wrapper 실행 결과와 함께 확인한다.
