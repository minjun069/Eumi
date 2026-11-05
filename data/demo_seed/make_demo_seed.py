"""시연용 복지자원 · 사례자 seed 를 만든다.

  python data/demo_seed/make_demo_seed.py

결과 (직접 고치지 말고 이 스크립트를 다시 돌린다):
  db/seed/R__04_welfare_resource.sql  실제 복지서비스(source/welfare_services.csv + welfare_picks.py) + 동 단위 가상 자원(resources_local.py)
  db/seed/R__05_demo_case.sql         대표 사례자(scenario_hero.py) + 생성 사례자(scenario_cases.py) · 담당자 · 상담 기록

- 고정 난수라 몇 번을 돌려도 같은 파일이 나온다 (내용이 바뀌면 Flyway 가 R 파일을 다시 실행한다).
- 기관은 R__02 시연 기관, 담당자는 R__03 시연 회원(demo1 · demo2)으로 찾는다. 둘 다 없는 DB 에서는 아무것도 넣지 않는다.
- 다시 실행돼도 중복이 생기지 않는다: 자원은 (자원명, 운영 기관, 시군구, 행정동), 사례자는 (기관, 관리번호),
  상담은 (사례자, 상담일, 목적)이 같으면 넣지 않는다. 사용자가 고친 행은 그대로 둔다.
"""
from __future__ import annotations

import csv
import datetime as dt
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import scenario_cases as sc  # noqa: E402
from resources_local import CHUNCHEON_ORG, GANGNAM_ORG, LOCAL_RESOURCES  # noqa: E402
from scenario_hero import HERO_CASES  # noqa: E402
from welfare_picks import PICKS, SIGUNGU_BY_SIDO  # noqa: E402

ORGS = {
    "gangnam": dict(domain="demo-gangnam.eumi.test", name=GANGNAM_ORG, sigungu="11680"),
    "chuncheon": dict(domain="demo-chuncheon.eumi.test", name=CHUNCHEON_ORG, sigungu="51110"),
}
SIGUNGU_ORG = {o["sigungu"]: k for k, o in ORGS.items()}
YEAR_START, YEAR_END = dt.date(2026, 1, 1), dt.date(2026, 12, 31)   # 실제 서비스의 운영 기간은 올해로 둔다
TODAY = dt.date.fromisoformat(sc.TODAY)
LIMITS = dict(resource_name=50, operating_org_name=50, target=100, support_content=1000, apply_method=200,
              purpose=200, content=20000, category_etc=20, name=100)


def email(org: str, who: str) -> str:
    return f"{who}@{ORGS[org]['domain']}"


def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "ARRAY[" + ", ".join(q(x) for x in v) + "]::text[]"
    return "'" + str(v).replace("'", "''") + "'"


def check_len(field: str, value: str | None) -> None:
    if value is not None and len(value) > LIMITS[field]:
        raise SystemExit(f"[FAIL] {field} 길이 {len(value)} > {LIMITS[field]}: {value[:40]}…")


def cut(text: str, limit: int) -> str:
    """limit 안에서 문장(또는 항목) 경계로 자른다."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    for sep in (". ", "다.", "※", " - ", "- ", " "):
        i = head.rfind(sep)
        if i > limit * 0.5:
            return head[:i + len(sep)].rstrip() + "…"
    return head + "…"


def ymd(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y%m%d").date()


def at(day: dt.date, hour: int, minute: int) -> str:
    return f"{day.isoformat()} {hour:02d}:{minute:02d}"


# ---------------------------------------------------------------- 복지자원
def real_resources(rng: random.Random) -> list[dict]:
    with (HERE / "source" / "welfare_services.csv").open(encoding="utf-8", newline="") as f:
        src = {r["서비스ID"]: r for r in csv.DictReader(f)}
    rows = []
    for sid, pick in PICKS.items():
        r = src[sid]
        sigungu = SIGUNGU_BY_SIDO[r["시도명"]]
        start = max(ymd(r["시행시작일자"]), YEAR_START)
        end = min(ymd(r["시행종료일자"]), YEAR_END)
        apply = r["신청방법 내용"] or (f"{r['신청방법명']} 신청" if r["신청방법명"] else "주소지 동주민센터 문의")
        created = min(start, dt.date(2026, 1, 2)) + dt.timedelta(days=rng.randint(0, 20))
        rows.append(dict(
            name=r["서비스명"].strip(), org_name=r["사업담당부서명"], target=pick["target"], ages=pick["ages"],
            gender=pick["gender"], sigungu=sigungu, dong=None, start=start, end=end, fee=0, status="진행 중",
            manager=email(SIGUNGU_ORG[sigungu], pick["manager"]), capacity=pick["capacity"], participants=pick["participants"],
            content=cut(r["급여서비스 내용"] or r["서비스 요약"], LIMITS["support_content"]),
            apply=cut(apply, LIMITS["apply_method"]), created=at(created, rng.randint(9, 17), rng.randint(0, 59)),
            source=sid,
        ))
    return rows


def local_resources(rng: random.Random) -> list[dict]:
    rows = []
    for x in LOCAL_RESOURCES:
        org = ORGS[x["org"]]
        start, end = (dt.date.fromisoformat(d) for d in x["period"])
        created = min(start - dt.timedelta(days=rng.randint(7, 20)), TODAY)
        rows.append(dict(
            name=x["name"], org_name=org["name"], target=x["target"], ages=x["ages"], gender=x["gender"],
            sigungu=org["sigungu"], dong=x["dong"], start=start, end=end, fee=x["fee"], status=x["status"],
            manager=email(x["org"], x["manager"]), capacity=x["capacity"], participants=x["participants"],
            content=x["content"], apply=x["apply"], created=at(created, rng.randint(9, 17), rng.randint(0, 59)), source="가상",
        ))
    return rows


def validate_resource(r: dict) -> None:
    for f, v in (("resource_name", r["name"]), ("operating_org_name", r["org_name"]), ("target", r["target"]),
                 ("support_content", r["content"]), ("apply_method", r["apply"])):
        check_len(f, v)
    ages = r["ages"]
    assert ages and set(ages) <= {"청소년", "청년", "중장년", "노년", "무관"} and ("무관" not in ages or len(ages) == 1), r["name"]
    assert r["gender"] in ("남", "여", "무관") and r["end"] >= r["start"] and r["capacity"] >= 1, r["name"]
    assert r["participants"] is None or 0 <= r["participants"] <= r["capacity"], r["name"]
    assert r["dong"] is None or r["dong"][:5] == r["sigungu"], r["name"]


def resource_sql(rows: list[dict]) -> str:
    for r in rows:
        validate_resource(r)
    n_real = sum(r["source"] != "가상" for r in rows)
    values = ",\n".join(
        "    (" + ", ".join([q(r["name"]), q(r["org_name"]), q(r["target"]), q(r["ages"]), q(r["gender"]), q(r["sigungu"]),
                             q(r["dong"]), q(r["start"].isoformat()), q(r["end"].isoformat()), q(r["fee"]), q(r["status"]),
                             q(r["manager"]), q(r["capacity"]), q(r["participants"]), q(r["content"]), q(r["apply"]),
                             q(r["created"])]) + ")"
        for r in rows)
    return f"""-- 시연용 복지자원 {len(rows)}건. data/demo_seed/make_demo_seed.py 로 생성 (직접 고치지 말 것)
--   실제 복지서비스 {n_real}건: 한국사회보장정보원 복지서비스 상세 정보(공공데이터). 서비스명 · 담당 부서 · 지원 내용 · 신청 방법은 원본,
--     지원 대상 요약 · 연령 · 운영 기간(올해) · 정원 · 참여자 수 · 담당자는 시연용 가정값 (data/demo_seed/welfare_picks.py)
--   동 단위 가상 자원 {len(rows) - n_real}건: 시연 기관이 고위험 동에서 운영한다고 가정한 프로그램 (실제 사업 아님)
-- 담당자는 R__03 시연 회원 이메일로 찾는다. 같은 (자원명, 운영 기관, 시군구, 행정동) 행이 있으면(삭제된 행 포함) 넣지 않는다.
INSERT INTO welfare_resource (
    resource_name, operating_org_name, target, support_age_groups, support_gender, sigungu_code, dong_code,
    period_start, period_end, fee, manual_status, manager_member_id, capacity, actual_participants,
    support_content, apply_method, created_at, updated_at)
SELECT s.resource_name, s.operating_org_name, s.target, s.support_age_groups, s.support_gender, s.sigungu_code, s.dong_code,
       s.period_start::date, s.period_end::date, s.fee, s.manual_status, m.member_id, s.capacity, s.actual_participants,
       s.support_content, s.apply_method,
       s.created_at::timestamp AT TIME ZONE 'Asia/Seoul', s.created_at::timestamp AT TIME ZONE 'Asia/Seoul'
FROM (VALUES
{values}
) AS s(resource_name, operating_org_name, target, support_age_groups, support_gender, sigungu_code, dong_code,
       period_start, period_end, fee, manual_status, manager_email, capacity, actual_participants,
       support_content, apply_method, created_at)
JOIN member m ON m.email_normalized = s.manager_email AND m.withdrawn_at IS NULL
WHERE (s.dong_code IS NULL OR EXISTS (SELECT 1 FROM dim_region r WHERE r.adm_cd10 = s.dong_code))
  AND NOT EXISTS (
    SELECT 1 FROM welfare_resource w
    WHERE w.resource_name = s.resource_name AND w.operating_org_name = s.operating_org_name
      AND w.sigungu_code = s.sigungu_code AND w.dong_code IS NOT DISTINCT FROM s.dong_code);
"""


# ---------------------------------------------------------------- 사례자
def pick_weighted(rng: random.Random, items: list, weights: list):
    return rng.choices(items, weights=weights, k=1)[0]


def birth_for(rng: random.Random, age: int, ref: dt.date = TODAY) -> dt.date:
    # ref 기준 만 age 세가 되도록 (생일이 ref 이전인 날짜)
    year = ref.year - age
    while True:
        d = dt.date(year, rng.randint(1, 12), rng.randint(1, 28))
        if d <= ref.replace(year=year):
            return d


def random_date(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=rng.randint(0, (end - start).days))


def weekday_after(day: dt.date) -> dt.date:
    while day.weekday() >= 5:   # 상담일은 평일로
        day += dt.timedelta(days=1)
    return day


def plan_stages(rng: random.Random, profile: dict) -> list[str]:
    n = rng.choice([2, 3, 3, 4, 4, 5])
    stages = ["init"]
    used = {"regular": 0, "mid": 0, "urgent": 0, "etc": 0}
    for i in range(1, n):
        last = i == n - 1
        if last and n >= 3 and rng.random() < 0.3:
            stages.append("close")
            break
        options, weights = [], []
        for st, w in (("regular", 6), ("mid", 2), ("urgent", 2), ("etc", 1)):
            cap = len(profile[st]) if st != "etc" else 1
            if used[st] >= cap or (st == "mid" and used["regular"] == 0):
                continue
            options.append(st)
            weights.append(w)
        if not options:
            break
        st = pick_weighted(rng, options, weights)
        used[st] += 1
        stages.append(st)
    return stages


def consult_days(rng: random.Random, registered: dt.date, stages: list[str]) -> list[dt.date]:
    """첫 상담은 등록일. 진행 중 사례는 마지막 상담이 최근 2~10주 안, 종결 사례는 등록 4~10개월 뒤에 끝난다."""
    k = len(stages) - 1
    if stages[-1] == "close":
        end = registered + dt.timedelta(days=rng.randint(120, 320))
    else:
        end = TODAY - dt.timedelta(days=rng.randint(3, 75))
    end = min(max(end, registered + dt.timedelta(days=14 * k)), TODAY - dt.timedelta(days=2))
    span = (end - registered).days
    middle = sorted(rng.sample(range(14, span), k - 1)) if k > 1 else []
    days, last = [registered], registered
    for off in middle + ([span] if k else []):
        day = weekday_after(registered + dt.timedelta(days=off))
        if day <= last:
            day = weekday_after(last + dt.timedelta(days=1))
        days.append(min(day, TODAY))
        last = day
    return days


def generated_cases(rng: random.Random, taken_names: set[str]) -> list[dict]:
    cases = []
    start, end = (dt.date.fromisoformat(d) for d in (sc.REGISTER_FROM, sc.REGISTER_TO))
    for org, count in sc.GENERATED_COUNT.items():
        dongs = sc.DONGS[org]
        must = sc.GUARANTEED[org]
        for i in range(count):
            if i < len(must):   # 목록 필터(연령대 등)가 비지 않도록 꼭 넣을 유형부터
                key = must[i]
                ok = [d for d in dongs if sc.PROFILES[key]["weight"][sc.area_of(d[1])] > 0]
                code, dong_name, grade = pick_weighted(rng, ok, [sc.GRADE_WEIGHT[g] for _, _, g in ok])
                area = sc.area_of(dong_name)
            else:
                code, dong_name, grade = pick_weighted(rng, dongs, [sc.GRADE_WEIGHT[g] for _, _, g in dongs])
                area = sc.area_of(dong_name)
                keys = [k for k, p in sc.PROFILES.items() if p["weight"][area] > 0]
                key = pick_weighted(rng, keys, [sc.PROFILES[k]["weight"][area] for k in keys])
            p = sc.PROFILES[key]
            age = rng.randint(*p["ages"])
            gender = "여" if rng.random() < p["female"] else "남"
            while True:
                name = rng.choice(sc.SURNAMES) + rng.choice(sc.GIVEN[(gender, sc.generation(age))])
                if name not in taken_names:
                    taken_names.add(name)
                    break
            registered = weekday_after(random_date(rng, start, end))
            r = rng.random()
            managers = ["demo1"] if r < 0.6 else ["demo2"] if r < 0.75 else ["demo1", "demo2"]
            words = sc.AREA_WORDS[area]
            fill = dict(home=rng.choice(words["home"]), hub=words["hub"], neighbor=words["neighbor"])
            consultations = []
            pools = {st: list(p[st]) for st in ("init", "regular", "mid", "urgent", "close")}
            stages = plan_stages(rng, p)
            for st, day in zip(stages, consult_days(rng, registered, stages)):
                recorder = rng.choice(managers)
                if st == "etc":
                    etc, purpose, content = rng.choice(sc.ETC)
                    consultations.append((day.isoformat(), "기타", etc, purpose, content, recorder))
                    continue
                purpose, content = pools[st].pop(rng.randrange(len(pools[st])))
                category = {"init": "초기상담", "regular": "정기상담", "mid": "중기상담", "urgent": "긴급상담", "close": "종료상담"}[st]
                consultations.append((day.isoformat(), category, None, purpose, content.format(**fill), recorder))
            cases.append(dict(org=org, dong=code, dong_name=dong_name, name=name, birth=birth_for(rng, age).isoformat(),
                              gender=gender, registered=registered.isoformat(), managers=managers,
                              consultations=consultations, profile=key))
    return cases


def all_cases(rng: random.Random) -> list[dict]:
    hero = [dict(c, profile="hero") for c in HERO_CASES]
    cases = hero + generated_cases(rng, {c["name"] for c in hero} | sc.RESERVED_NAMES)
    # 관리번호: 기관 · 최초 등록일 연도별 순번 (등록일 순). next_management_no 가 이어서 발급한다.
    seq: dict[tuple[str, str], int] = {}
    for c in sorted(cases, key=lambda c: (c["org"], c["registered"], c["name"])):
        k = (c["org"], c["registered"][:4])
        seq[k] = seq.get(k, 0) + 1
        c["management_no"] = f"{k[1]}-{seq[k]:04d}"
    return sorted(cases, key=lambda c: (c["org"], c["management_no"]))


def validate_case(c: dict) -> None:
    check_len("name", c["name"])
    assert c["gender"] in ("남", "여") and c["managers"], c["name"]
    assert c["birth"] < c["registered"] <= sc.TODAY, c["name"]
    days = [x[0] for x in c["consultations"]]
    assert days and days == sorted(days) and days[0] >= c["registered"] and days[-1] <= sc.TODAY, c["name"]
    assert len(set((d, p) for d, _, _, p, _, _ in c["consultations"])) == len(days), f"상담 중복 {c['name']}"
    for d, cat, etc, purpose, content, recorder in c["consultations"]:
        assert cat in ("초기상담", "중기상담", "종료상담", "정기상담", "긴급상담", "기타") and (cat == "기타") == (etc is not None)
        assert recorder in c["managers"], f"기록자가 담당자가 아님 {c['name']} {d}"
        assert c["name"] not in content, f"상담 내용에 이름 {c['name']}"
        check_len("purpose", purpose)
        check_len("content", content)
        if etc:
            check_len("category_etc", etc)


def case_sql(cases: list[dict], rng: random.Random) -> str:
    for c in cases:
        validate_case(c)
    key = lambda c: [q(c["org"]), q(c["management_no"]), q(c["name"]), q(c["birth"])]  # noqa: E731
    case_rows = ",\n".join(
        "    (" + ", ".join(key(c) + [q(c["gender"]), q(c["dong"]), q(c["registered"]),
                                    q(at(dt.date.fromisoformat(c["registered"]), rng.randint(9, 11), rng.randint(0, 59)))]) + ")"
        for c in cases)
    manager_rows = ",\n".join(
        "    (" + ", ".join(key(c) + [q(email(c["org"], m))]) + ")" for c in cases for m in c["managers"])
    consult_rows = ",\n".join(
        "    (" + ", ".join(key(c) + [q(d), q(cat), q(etc), q(purpose), q(content), q(email(c["org"], rec)),
                                    q(at(dt.date.fromisoformat(d), rng.randint(13, 18), rng.randint(0, 59)))]) + ")"
        for c in cases for d, cat, etc, purpose, content, rec in c["consultations"])
    n_consult = sum(len(c["consultations"]) for c in cases)
    orgs = ",\n".join(f"    ({q(k)}, {q(o['domain'])}, {q(o['name'])}, {q(o['sigungu'])})" for k, o in ORGS.items())
    return f"""-- 시연용 사례자 {len(cases)}명 · 상담 기록 {n_consult}건 (모두 가상 인물). data/demo_seed/make_demo_seed.py 로 생성 (직접 고치지 말 것)
--   대표 사례자 {len(HERO_CASES)}명은 2025-12 위험 탐지 결과의 고위험 동 이야기(scenario_hero.py), 나머지는 위기 유형별 문장으로 생성(scenario_cases.py)
-- 기관은 R__02 시연 기관(도메인 · 이름 · 시군구), 담당자 · 기록자는 R__03 시연 회원 이메일로 찾는다.
-- 같은 기관에 같은 관리번호가 있으면 사례자를 넣지 않는다. 담당자 · 상담 기록은 관리번호 · 이름 · 생년월일이 모두 같은 사례자에만 붙인다.
CREATE TEMP TABLE seed_demo_org ON COMMIT DROP AS
SELECT DISTINCT ON (s.org_key) s.org_key, o.org_id
FROM (VALUES
{orgs}
) AS s(org_key, domain, org_name, sigungu_code)
JOIN organization o ON o.official_domain = s.domain AND o.org_name = s.org_name AND o.jurisdiction_sigungu_code = s.sigungu_code
ORDER BY s.org_key, o.org_id;

INSERT INTO case_record (org_id, management_no, name, birth_date, gender, dong_code, first_registered_at, created_at, updated_at)
SELECT o.org_id, s.management_no, s.name, s.birth_date::date, s.gender, s.dong_code, s.first_registered_at::date,
       s.created_at::timestamp AT TIME ZONE 'Asia/Seoul', s.created_at::timestamp AT TIME ZONE 'Asia/Seoul'
FROM (VALUES
{case_rows}
) AS s(org_key, management_no, name, birth_date, gender, dong_code, first_registered_at, created_at)
JOIN seed_demo_org o ON o.org_key = s.org_key
JOIN dim_region r ON r.adm_cd10 = s.dong_code
ON CONFLICT (org_id, management_no) DO NOTHING;

INSERT INTO case_manager (case_id, member_id)
SELECT c.case_id, m.member_id
FROM (VALUES
{manager_rows}
) AS s(org_key, management_no, name, birth_date, manager_email)
JOIN seed_demo_org o ON o.org_key = s.org_key
JOIN case_record c ON c.org_id = o.org_id AND c.management_no = s.management_no AND c.name = s.name AND c.birth_date = s.birth_date::date
JOIN member m ON m.email_normalized = s.manager_email AND m.org_id = o.org_id AND m.withdrawn_at IS NULL
ON CONFLICT DO NOTHING;

INSERT INTO consultation (case_id, consulted_at, category, category_etc, purpose, content, recorder_member_id, created_at, updated_at)
SELECT c.case_id, s.consulted_at::date, s.category, s.category_etc, s.purpose, s.content, m.member_id,
       s.created_at::timestamp AT TIME ZONE 'Asia/Seoul', s.created_at::timestamp AT TIME ZONE 'Asia/Seoul'
FROM (VALUES
{consult_rows}
) AS s(org_key, management_no, name, birth_date, consulted_at, category, category_etc, purpose, content, recorder_email, created_at)
JOIN seed_demo_org o ON o.org_key = s.org_key
JOIN case_record c ON c.org_id = o.org_id AND c.management_no = s.management_no AND c.name = s.name AND c.birth_date = s.birth_date::date
JOIN member m ON m.email_normalized = s.recorder_email AND m.org_id = o.org_id
WHERE NOT EXISTS (
    SELECT 1 FROM consultation x
    WHERE x.case_id = c.case_id AND x.consulted_at = s.consulted_at::date AND x.purpose = s.purpose);
"""


def main() -> None:
    rng = random.Random(sc.SEED)
    resources = real_resources(rng) + local_resources(rng)
    cases = all_cases(rng)
    out4 = ROOT / "db" / "seed" / "R__04_welfare_resource.sql"
    out5 = ROOT / "db" / "seed" / "R__05_demo_case.sql"
    out4.write_text(resource_sql(resources), encoding="utf-8", newline="\n")
    out5.write_text(case_sql(cases, rng), encoding="utf-8", newline="\n")
    by_org = {k: [c for c in cases if c["org"] == k] for k in ORGS}
    print(f"[OK] {out4.relative_to(ROOT)}: 복지자원 {len(resources)}건 "
          f"(실제 {sum(r['source'] != '가상' for r in resources)}, 가상 {sum(r['source'] == '가상' for r in resources)})")
    for k, cs in by_org.items():
        n = sum(len(c["consultations"]) for c in cs)
        print(f"[OK] {out5.relative_to(ROOT)}: {k} 사례자 {len(cs)}명 · 상담 {n}건")


if __name__ == "__main__":
    main()
