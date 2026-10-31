# GitLab 저장소 설정

현재 설정 기록입니다. 
GitLab 버전에 따라 메뉴 이름 · 위치가 조금 다를 수 있습니다.

- 마지막 확인: 2026-10-30

## 1. 브랜치

**Settings > Repository**

- 기본 브랜치(Branch defaults): `develop`
- 보호 브랜치(Protected branches)

| 브랜치 | Allowed to merge | Allowed to push and merge | Allowed to force push |
|---|---|---|---|
| `master` | Maintainers | No one | 끔 |
| `develop` | Developers + Maintainers | No one | 끔 |

## 2. Merge Request

**Settings > Merge requests**

| 항목 | 값 | 이유 |
|---|---|---|
| Merge method | Merge commit | |
| Squash commits when merging | Allow | MR마다 작성자가 선택 |
| Squash commit message template | %{title} / %{all_commits} / MR: %{reference} (줄마다 띄움) | 합친 커밋에도 각 커밋 메시지와 Jira 키를 남기기 위해 |
| Enable "Delete source branch" option by default | 켬 | 병합된 작업 브랜치 정리 |
| All threads must be resolved | 켬 | 리뷰 댓글을 해결해야 병합 ([CONTRIBUTING 3.2](../CONTRIBUTING.md#32-리뷰-진행-순서)) |

승인을 강제하는 설정(Approval rules)은 GitLab 요금제에 따라 쓸 수 없을 수 있습니다. 승인 필수 범위는 팀 규칙으로 지킵니다.

## 3. 멤버

**Manage > Members**

| 이름 | 역할 | 권한 |
|---|---|---|
| 김민재 | BE · FE · Infra | Maintainer |
| 김민준 | PM · AI | Maintainer |
| 강병민 | DE | Developer 이상 |
| 이지석 | DA | Developer 이상 |
| 이지원 | -  | Developer 이상 |
| 배유진 | -  | Developer 이상 |


## 4. 연동

| 대상 | 방식 | 상태 |
|---|---|---|
| Jenkins | 서버(EC2)에 설치된 Jenkins. GitLab 접근 토큰은 인프라 담당 계정으로 발급 | 토큰 교체 · webhook은 배포 설정 때 진행 |
| Jira | 커밋 본문과 MR 설명에 이슈 키를 적음 ([CONTRIBUTING 2장](../CONTRIBUTING.md#2-커밋-메시지)) | GitLab–Jira 연동(Settings > Integrations > Jira)이 켜져 있으면 Jira 이슈에 커밋이 자동으로 연결됨. 켜져 있는지 확인 필요 |

## 5. 쓰지 않는 기능

- GitLab 이슈 · 라벨 · 마일스톤: 일정과 이슈는 Jira로 관리합니다.

## 6. 설정 이력

| 날짜 | 내용 |
|---|---|
| 2026-10-26 | 초기 디렉터리 구조 · 협업 규칙 · 템플릿 (master, develop 생성) |
| 2026-10-27 | Jenkins 연결 테스트용 `Jenkinsfile` (master) |
| 2026-10-30 | backend · frontend 초기 프로젝트 병합, master의 `Jenkinsfile`을 develop에 반영, 기본 브랜치 develop, master · develop 보호 |
| 2026-10-30 | 공통 규칙(버전, 로그인 결정 기록), 로컬 개발 DB(Flyway V1~V6, 계정 · 권한) 병합 |
| 2026-10-30 | 개발 인원 4명 기준으로 협업 규칙 개편 (MR 리뷰, Jira, DB, 비밀값) |
