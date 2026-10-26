# GitLab 저장소 초기 설정

저장소 관리자(Maintainer 이상 권한) 1명이 진행합니다.
GitLab 버전에 따라 메뉴 이름·위치가 조금 다를 수 있습니다.

## 1. 첫 커밋 올리기

```bash
git clone <저장소 주소>
cd <저장소 폴더>

# 압축 파일의 내용을 이 폴더 안에 바로 풉니다.
# .gitignore, .gitattributes, .editorconfig, .gitlab/ 같은 숨김 파일도 함께 들어가야 합니다.
git status            # .gitignore, .gitlab/ 등이 목록에 보이는지 확인

git add .
git commit -m "chore: [init] 초기 디렉터리 구조와 협업 템플릿 추가"
git branch -M master
git push -u origin master

# 개발 통합 브랜치
git switch -c develop
git push -u origin develop
```

## 2. 기본 브랜치와 보호 브랜치

**Settings > Repository**

- Branch defaults(기본 브랜치): `develop`
- Protected branches

| 브랜치 | Allowed to merge | Allowed to push and merge |
|---|---|---|
| `master` | Maintainers | No one |
| `develop` | Developers + Maintainers | No one |

## 3. Merge Request 설정

**Settings > Merge requests**

- Squash commits when merging: Encourage (권장)
- Enable "Delete source branch" option by default: 체크
- 승인 필수 규칙(Approval rules)은 GitLab 요금제에 따라 사용할 수 없을 수 있습니다. 이 경우 "리뷰어 1명 승인 후 병합"을 팀 규칙으로 운영합니다.

## 4. 라벨

**Manage > Labels** (버전에 따라 Project information > Labels)

| 구분 | 라벨 |
|---|---|
| 파트 | `FE`, `BE`, `AI`, `DATA`, `DB`, `INFRA`, `DOCS` |
| 우선순위 | `P0`, `P1`, `P2`, `P99` (기능명세서 우선순위와 같음) |
| 유형 | `bug` |

## 5. 마일스톤

**Plan > Milestones** (버전에 따라 Issues > Milestones)

| 이름 | 시작일 | 마감일 |
|---|---|---|
| 1차 | 2026-10-26 | 2026-10-31 |
| 2차 | 2026-11-02 | 2026-11-08 |

## 6. 팀원 권한

**Manage > Members**

- 저장소 관리자 1~2명: Maintainer
- 나머지 팀원: Developer

## 7. 다음 단계 (각 파트 담당)

각자 `develop`에서 `chore/{폴더}-init` 브랜치(예: `chore/backend-init`)를 만들고, 담당 폴더에 프로젝트를 생성해 `develop`으로 MR을 올립니다.

| 폴더 | 생성 방법 | 주의 |
|---|---|---|
| `frontend/` | Vite React 템플릿 | 폴더 안에서 `npm create vite@latest .` 실행 후 "Ignore files and continue" 선택 (`.gitkeep` 때문) |
| `backend/` | Spring Initializr (Gradle) | 내려받은 압축 파일의 내용을 `backend/` 안에 풉니다 |
| `ai/` | FastAPI | Python 버전과 의존성 파일(`requirements.txt` 등)을 함께 커밋 |
| `data/` | Python 환경 파일 | 원본 데이터는 `data/raw/`에 두며 커밋되지 않음 |
| `db/` | 확정된 스키마 SQL | `db/migration/V1__init.sql`부터 번호 순서대로 |

- 프로젝트 생성 도구가 하위 폴더에 `.git`을 만들었다면 반드시 지웁니다. (저장소 안에 저장소가 생기는 것 방지)
- 각 폴더의 `.gitkeep`은 프로젝트 파일이 들어간 뒤 지워도 됩니다.
- 파트별 실행 방법은 해당 폴더의 README에 적습니다.
