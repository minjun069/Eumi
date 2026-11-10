# C4 사례자 수정 경합 409 인계

- 작업: C4, API-20·23. Jira: S15P31B201-271.
- 브랜치: `feat/be-case-conflict`, 기준 develop `b5e9084cd303de93d8b2db3e12d196c0a51ad499`.
- 초기 구현은 `d50a2b6`으로 커밋·리뷰됐다. 아래 초기 검사 기록과 마지막 절의 C4 리뷰 S1 후속 검사 기록을 구분한다.
- 사용자 지시로 이번 BE MR에 `docs/api/openapi.json`과 지정된 `docs/spec` 문서·엑셀을 함께 변경한다. AGENTS.md의 평소 docs/api 담당 제한보다 이번 명시적 지시를 우선했다.

## 바꾼 파일

- `backend/src/main/java/com/eumi/backend/cases/CaseController.java`
- `backend/src/main/java/com/eumi/backend/cases/CaseDtos.java`
- `backend/src/main/java/com/eumi/backend/cases/CaseRepository.java`
- `backend/src/main/java/com/eumi/backend/cases/CaseService.java`
- `backend/src/main/java/com/eumi/backend/mypage/WithdrawalRepository.java`
- `backend/src/test/java/com/eumi/backend/CaseIntegrationTests.java`
- `backend/src/test/java/com/eumi/backend/CaseValidationTests.java`
- `backend/src/test/java/com/eumi/backend/WithdrawalIntegrationTests.java`
- `backend/docs/cases/README.md`
- `backend/docs/cases/2026-11-10_case-conflict.md`
- `docs/api/openapi.json`
- `docs/spec/api-spec.md`
- `docs/spec/README.md`
- `docs/spec/이음이_API_명세표.xlsx`

## 계약·DTO·오류

OpenAPI를 2.4.1에서 2.5.0으로 올렸다. 확정 지시와 달라진 점은 없다.

- API-20 `CaseDetail.updatedAt`은 필수 문자열이다. DB TIMESTAMPTZ를 Instant로 읽은 뒤 `uuuu-MM-dd'T'HH:mm:ss.SSSSSSxxx`와 Asia/Seoul 시간대로 포맷한다. 문자열이므로 Jackson이 끝의 0을 없애지 않는다. 같은 순간을 유지하고 소수 6자리와 오프셋을 고정한다.
- API-23은 별도 `CaseDtos.UpdateInput`을 받는다. 기존 6개 입력과 `updatedAt`을 받으며, API-22의 `CaseDtos.Input`은 유지한다.
- `updatedAt` 누락·null·빈 문자열·잘못된 날짜·오프셋 없는 값은 `VALIDATION_ERROR` 400과 `fieldErrors.updatedAt`으로 응답한다. 서비스 입력 검사에서 OffsetDateTime으로 파싱하고 안정적인 필드 오류만 반환한다. 최초 통합 검사에서 공통 Bean Validation 경로가 누락·null의 fieldErrors를 비우는 것을 발견해, 이 필드의 검사를 서비스의 동일한 파싱 경로로 모았다. 공통 오류 처리기는 바꾸지 않았다.
- 잠근 사례자 행과 요청의 Instant를 각각 MICROS로 잘라 비교한다. 오프셋이 달라도 같은 순간이면 통과한다. 나노초 끝 3자리는 비교하지 않는다.
- 불일치는 기존 `STATE_CONFLICT` 409다. 성공은 204이며 새 오류 코드는 없다.
- OpenAPI의 변경 경로는 `info.version/description`, `CaseDetail.updatedAt/required`, 새 `CaseUpdateInput`, `/cases/{caseId}` GET 예시와 PUT 설명·요청 스키마·예시뿐이다. API-22와 나머지 API·스키마는 보존했다. `json.dumps(ensure_ascii=False, indent=2)` 형식과 파일 끝 줄바꿈 없음도 검사했다.

## 권한·잠금·M3 인계

잠금 순서는 기존대로 접근 확인 → 입력 검사 → 기관 → 회원 ID 순 → 사례자 FOR UPDATE다. 잠근 행에서 시각을 읽고 권한을 재확인한 직후 비교하며, 409이면 사례자와 담당자 연결을 바꾸지 않는다. 같은 기관 비담당자는 403, 다른 기관·없는 사례자는 404이며 이 판단이 시각 비교보다 먼저다. 부적합 담당자는 기존대로 400이므로 탈퇴자가 요청 담당자에 남은 경우 409보다 먼저 400이 날 수 있다.

`CaseRepository.update`의 `updated_at=now()`와 담당자 교체 순서는 유지했다. 담당자만 바꿔도 시각이 갱신된다.

M3에서 C4로 넘긴 S1도 반영했다. `WithdrawalRepository.deleteCaseLinks`는 이미 잠근 본인 담당 사례자의 `updated_at=now()`를 같은 탈퇴 트랜잭션에서 갱신한 뒤 담당자 연결을 삭제한다. 공동 담당자를 포함한 담당 변경을 이전 수정 화면에서 감지한다. API-34 형식·오류 순서·잠금 순서는 바꾸지 않았다. 기존 M3 경합 검사의 API-23 요청에는 필수 updatedAt만 추가했다.

DB 스키마·마이그레이션·FE·infra·운영 설정·의존성 변경은 없다. API-22·삭제·상담 형식도 유지했다. git 쓰기와 docker compose, 실제 AI 호출은 실행하지 않았다.

## 초기 구현 검사 기록 (d50a2b6)

실제 공용 PostgreSQL에 합성 기관·회원·사례자·상담을 만들고 실제 PBKDF2 로그인·세션·CSRF·HTTP를 사용한다. 생성한 기관·회원의 데이터와 세션만 정리한다. 날짜·담당·권한·동시성 검사는 실제 DB다. 기존 등록 롤백 검사는 Spy로 저장 실패를 주입한다. 동시 수정 검사는 두 요청이 모두 기관 잠금 직전까지 도착한 뒤 함께 풀어 204 한 개와 409 한 개를 확인한다. 실제 AI 대신 fake와 테스트 내부 HTTP stub만 사용한다.

| 실행 | 결과 |
|---|---|
| 첫 Case·Withdrawal 통합 | 69개 중 67개 통과. updatedAt 누락·null의 fieldErrors 2개 실패 후 수정 |
| 수정 후 Case·Withdrawal 통합 | Case 42 + Withdrawal 27 = 69개 통과 |
| Case 8080 실제 HTTP | 42개 통과 (`EUMI_CASE_TEST_PORT=8080`) |
| 최종 전체 단위·mock | 26개 클래스, 194개 통과 (2026-11-10 22:17~22:18 서울 시각) |
| 관련 실제 DB·로컬 HTTP·Mailpit | 14개 클래스, 214개 통과 (2026-11-10 22:15~22:17 서울 시각) |
| bootJar·공백 검사 | 통과 |
| 명세 생성·형식 검사 | 제공된 Python(openpyxl 3.1.5)으로 build_xlsx.py 및 --check 통과 |
| 엑셀 보존·화면 | API-20·23 변경 전후 렌더 확인. 셀 스타일·열 너비·틀 고정·병합 유지, 추가 문구에 따라 두 행 높이만 변경 |

CaseIntegrationTests는 기존 29개에 C4 13개를 더해 42개다. 추가 범위는 소수 6자리·오프셋, 정상 수정·시각 변경, 옛 값 409와 데이터 보존, 담당자만 변경, 누락·null·형식 오류, 같은 순간의 다른 오프셋·나노초 절삭, 동시 204/409, 403·404 우선, M3 인계 후 옛 값 409다. 등록은 updatedAt 없이 기존대로 201이다.

관련 14개 클래스의 개수: AgentHttpRecovery 4, Agent 7, AgentRecovery 9, AgentWriterConcurrency 6, Auth 8, AuthTransaction 1, Case 42, ConversationCleanup 10, ConversationHistory 16, My 12, PasswordChange 14, Resource 46, TempPassword 12, Withdrawal 27. 모두 실패·오류·미실행 0이다. 위 69개·42개는 별도 선별 실행이며 214개에 포함된다.

재실행은 저장소 루트에서 명세 검사, backend에서 Gradle 검사를 실행한다. Python에는 openpyxl이 필요하다. 이번 PC의 기본 Python에는 없어 제공된 런타임 Python을 사용했다. `CaseIntegrationTests`의 기본 포트는 0이며 `EUMI_CASE_TEST_PORT=8080`일 때만 8080을 사용한다. 다른 프로세스가 쓰는 포트에서는 실행하지 않는다. 명령에는 기존 로컬 DB 환경을 전달하고 `EUMI_AI_MODE=fake`를 지정하며 `EUMI_VERIFY_LIVE_AI`는 설정하지 않는다.

실행별 클래스 수·시각·소스 해시 등은 ignored 파일 `backend/build/case-conflict-verification.json`에 기록한다. 선별 실행마다 XML이 바뀌므로 실행 직후 집계한다.

## 남은 일·FE 인계

- 초기 구현 `d50a2b6`의 사용자 커밋·Claude Code 리뷰는 완료됐다. C4 리뷰 S1 후속 수정의 커밋·리뷰와 push·develop 대상 MR·병합은 남아 있다. 파트 간 API 형식 변경이므로 FE 확인이 필요한 MR이다.
- FE는 병합 뒤 OpenAPI 2.5.0으로 `gen:api`를 실행하고 상세 updatedAt을 수정 폼에 보관해 그대로 전송한다. 409이면 변경 안내 후 상세를 다시 불러온다. FE 타입 파일은 이 MR에서 고치지 않았다.
- API 계약 변경을 모르고 옛 요청을 보내는 FE는 400이 나므로 FE 연결과 배포 순서를 맞춰야 한다.
- 브라우저·운영 배포·실제 AI 검사는 미실행이다.
- 원래 `updated_at=now()`를 유지했다. 요청 시각 비교는 시각 기반 버전이며 별도 정수 버전 컬럼을 추가하지 않았다.

커밋 제목 제안: `feat: [BE] 사례자 수정 경합 409 (openapi 2.5.0)`

커밋 본문 끝: `Jira: S15P31B201-271`

## C4 리뷰 S1 후속 — 상세 조회 시점 일치

- 기준 커밋: `d50a2b66266a992d8c7c89d18473e15b3870b9aa`. Jira는 S15P31B201-271을 유지한다.
- 이번 후속 변경 파일은 `CaseService.java`, `CaseIntegrationTests.java`, 이 인계 문서 3개이며 모두 backend 안이다.
- 이 절의 S1은 상세의 담당자 목록과 updatedAt이 다른 시점에서 읽히는 C4 리뷰 지적이다. 앞 절의 M3에서 이관했던 담당자 변경 시각 갱신 S1과 구분한다.

### 문제와 수정

기존 READ COMMITTED 상세 조회는 담당자 SELECT 다음, 사례자 정보·updatedAt SELECT 전에 다른 수정이 커밋되면 옛 담당자와 새 수정 시각을 함께 반환했다. 이 응답으로 저장하면 204로 통과해 상대방의 이름·담당자 변경이 되돌아갔다.

`CaseService.detail`만 `@Transactional(readOnly=true, isolation=Isolation.REPEATABLE_READ)`로 묶었다. 회원·접근 확인, 담당자 목록, 사례자 정보·updatedAt을 같은 읽기 스냅샷에서 가져온다. 읽는 동안 다른 사용자의 수정은 커밋될 수 있으며, 옛 스냅샷으로 저장하면 기존 API-23 비교가 409로 거절한다.

API-23의 접근 확인·입력 검증·기관 → 회원 → 사례자 잠금과 마이크로초 비교는 바꾸지 않았다. 새로운 쓰기 잠금이나 새 오류 코드는 없다. OpenAPI 2.5.0·DTO·DB 스키마·FE·명세·엑셀은 이번 후속에서 변경하지 않는다.

### 재현·회귀 검사

새 매개변수 검사 `detailReadDuringManagerChangeKeepsOldVersionAndRejectsTheStaleSave`는 담당자 추가와 제거 두 경우를 실행한다. JdbcTemplate을 Spy로 감싸 실제 담당자 SELECT가 끝난 뒤 해당 테스트 사례자만 한 번 멈춘다. 별도 사용자의 실제 HTTP PUT이 204로 커밋된 뒤 상세 조회를 계속한다. SQL 결과는 모사하지 않고 실제 DB에서 읽으며, 데이터 변경·버전 비교·HTTP 응답도 실제 구현을 사용한다.

- 수정 전 운영 코드는 그대로 둔 채 새 검사 2개를 먼저 실행했다. 두 경우 모두 담당자는 옛 값·시각은 새 값이었고, 옛 화면 저장이 204로 통과하며 상대방의 저장값을 덮어써 3개 단정이 각각 실패했다.
- REPEATABLE_READ 적용 뒤 같은 검사 2개가 통과했다. 옛 담당자와 옛 시각을 함께 반환하고, 그 값으로 저장하면 409 STATE_CONFLICT이며 새 이름·담당자 집합이 그대로다.
- 대기에는 상한을 두고 finally에서 조회 재개 latch를 푼다. 검사 종료 시 JdbcTemplate·Repository Spy 설정을 초기화한 뒤 자체 기관·회원·사례자·세션만 정리한다.
- 검사 코드의 제네릭 타입 표기 보완 중 컴파일 오류 1회는 import로 수정했다. 그 시도에서는 검사가 실행되지 않았으며 이후 8080 전체 검사가 통과했다.

| 후속 실행 | 결과 |
|---|---|
| 수정 전 S1 재현 | 2개 모두 예상 실패: 잘못된 스냅샷·204 저장·덮어쓰기 실제 확인 (11/10 22:55~22:56 서울 시각) |
| 수정 후 S1 선별 회귀 | 2개 통과 (11/10 22:56) |
| Case 8080 실제 DB·HTTP | 44개 통과 (기존 42 + S1 2, 11/10 22:57~22:58) |
| 관련 실제 DB·로컬 HTTP·Mailpit | 14개 클래스, 216개 통과 (11/10 22:58~23:00) |
| 최종 전체 단위·mock | 26개 클래스, 194개 통과 (11/10 23:01) |
| bootJar·공백 검사 | 통과 |

최종 관련 통합의 클래스별 개수는 초기 기록에서 Case만 42 → 44로 늘고 나머지는 같다. 최종 단위·통합은 실패·오류·미실행 모두 0이다. 수정 전의 예상 실패 2개와 검사 코드 컴파일 실패 시도는 최종 통과 결과에 포함하지 않는다.

기존 로컬 DB 환경과 JDK 21을 준비한 뒤 Git Bash에서 backend 폴더에서 재실행한다. 기본 포트는 0이고 8080은 비어 있을 때만 지정한다.

```bash
EUMI_AI_MODE=fake ./gradlew.bat integrationTest \
  --tests '*CaseIntegrationTests.detailReadDuringManagerChangeKeepsOldVersionAndRejectsTheStaleSave*' --console=plain
EUMI_AI_MODE=fake EUMI_CASE_TEST_PORT=8080 ./gradlew.bat integrationTest \
  --tests '*CaseIntegrationTests' --console=plain
./gradlew.bat test --console=plain
```

후속 실행별 클래스 수·시각·소스 해시는 ignored 파일 `backend/build/case-conflict-snapshot-verification.json`에 보존한다. 초기 `case-conflict-verification.json`과 구분한다.

### 수정하지 않은 후속 인계

- C4 리뷰 S2: M3 단독 담당 사례 인계의 수정 시각, 탈퇴 롤백 시 시각 복원, 부적합 담당자와 옛 버전이 함께 올 때의 400 우선순위 검사를 보강할 수 있다. 이번에는 추가하지 않았다.
- C4 리뷰 S3: 다른 입력 검증이 먼저 실패하면 updatedAt 오류까지 한 번에 모으지 않는다. 요청은 400으로 거절되며 검증 집계 방식은 유지한다.
- C4 리뷰 S4: 향후 v_case_summary에 updated_at이 추가될 때를 대비한 별칭 보강은 미뤘다. 현재 뷰에는 그 열이 없다.
- C4 리뷰 S5: updatedAt 설명은 사용자가 지정한 계약 문구 그대로다. 필요하면 계약 담당과 문구 개선을 논의한다.
- FE 연결·브라우저·운영 배포·실제 AI 검사는 미실행이다. git 쓰기와 docker compose, 실제 AI 호출은 하지 않았다.

후속 커밋 제목 제안: `fix: [BE] 사례자 상세 조회 스냅샷 일치`

후속 커밋 본문 끝: `Jira: S15P31B201-271`
