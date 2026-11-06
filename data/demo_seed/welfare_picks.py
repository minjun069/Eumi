"""실제 복지서비스에서 시연에 쓸 것만 고른 목록과, 원본에 없는 운영 항목.

원본: 한국사회보장정보원 복지서비스 상세 정보 (서비스ID 기준). 서비스명 · 담당 부서 · 시행 기간 · 지원 내용 · 신청 방법은
원본 그대로 쓰고(extract_welfare.py 가 정리), 아래 값만 사람이 정한다.
  target   지원 대상 요약 (화면 칸이 100자라 원본 '지원대상 내용'을 줄여 씀)
  ages     지원 연령 (원본 생애주기 기준, 청소년~노년 네 개 모두면 무관)
  gender   지원 성별
  capacity · participants  정원 · 실제 참여자 수 (원본에 없음, 시연용 가정값. participants None 이면 비워 둠)
  manager  등록 담당자 (시연 기관 demo1 / demo2)
고르는 기준: 사례 시나리오(고립 어르신, 1인 중장년, 은둔 · 저소득 청년, 장애인 가구, 한부모 · 조손)에 맞는 것.
영유아 · 임신 · 출산 전용, 신청이 끝난 시범사업, 개인이 아닌 상점 · 시설 대상 사업은 뺐다.
"""

ALL = ["무관"]

PICKS = {
    # ---------- 강남구 사업 ----------
    "WLF00002224": dict(target="강남구 기초생활수급자 · 차상위계층 · 한부모가족 (가구당 세대주 1인)",
                        ages=ALL, gender="무관", capacity=300, participants=262, manager="demo1"),
    "WLF00002227": dict(target="강남구 거주 등록장애인 중 휠체어 사용자",
                        ages=ALL, gender="무관", capacity=60, participants=41, manager="demo2"),
    "WLF00006109": dict(target="강남구 거주 만 19~39세 미취업 청년",
                        ages=["청년"], gender="무관", capacity=200, participants=137, manager="demo1"),
    "WLF00005414": dict(target="강남구 거주 신혼부부 · 청년 전세자금 대출자 (소득 · 면적 기준 충족)",
                        ages=["청년", "중장년"], gender="무관", capacity=150, participants=None, manager="demo2"),
    "WLF00002205": dict(target="건강보험료가 하한액 이하인 만 65세 이상 강남구 노인가구",
                        ages=["노년"], gender="무관", capacity=150, participants=128, manager="demo1"),
    "WLF00005706": dict(target="주거 공간이 좁은 강남구 기초생활수급자 · 차상위계층",
                        ages=ALL, gender="무관", capacity=40, participants=33, manager="demo1"),
    "WLF00006563": dict(target="강남구 기초생활수급자 · 차상위계층 (호흡기 중증질환자 · 장애인 · 고령자 우선)",
                        ages=ALL, gender="무관", capacity=80, participants=52, manager="demo2"),
    "WLF00006014": dict(target="강남구 거주 어르신(65세 이상) · 청년(19~24세) · 청소년(13~18세) · 어린이",
                        ages=["청소년", "청년", "노년"], gender="무관", capacity=500, participants=None, manager="demo1"),
    # ---------- 서울시 사업 (강남구 주민도 대상) ----------
    "WLF00002234": dict(target="국민기초생활보장 기준을 넘어 보호받지 못하는 비수급 빈곤층",
                        ages=ALL, gender="무관", capacity=100, participants=71, manager="demo1"),
    "WLF00002235": dict(target="실업 · 폐업 · 중한 질병 등 갑작스러운 위기로 생계가 어려운 가구 (중위소득 100% 이하)",
                        ages=ALL, gender="무관", capacity=80, participants=58, manager="demo1"),
    "WLF00006703": dict(target="서울시 거주 미취업 만 30~49세 여성 (중위소득 150% 이하)",
                        ages=["청년", "중장년"], gender="여", capacity=60, participants=44, manager="demo2"),
    "WLF00006708": dict(target="서울 거주 만 19~39세 청년",
                        ages=["청년"], gender="무관", capacity=200, participants=None, manager="demo2"),
    "WLF00002255": dict(target="민간 월세에 사는 기초생활수급자가 아닌 저소득 가구",
                        ages=ALL, gender="무관", capacity=120, participants=96, manager="demo1"),
    "WLF00006781": dict(target="만 10세 이상 서울시민 · 서울 소재 직장인 · 대학(원)생",
                        ages=ALL, gender="무관", capacity=500, participants=None, manager="demo2"),
    "WLF00006795": dict(target="서울시 거주 만 18세 이상 장애 정도가 심한 장애인",
                        ages=["청년", "중장년", "노년"], gender="무관", capacity=30, participants=24, manager="demo2"),
    "WLF00000843": dict(target="9~24세 저소득 여성청소년 (수급자 · 차상위 · 한부모가족)",
                        ages=["청소년", "청년"], gender="여", capacity=100, participants=67, manager="demo2"),
    "WLF00006262": dict(target="만 45세 이상 서울시민 (포인트는 만 60세 이상)",
                        ages=["중장년", "노년"], gender="무관", capacity=300, participants=None, manager="demo1"),
    "WLF00005003": dict(target="병원 이용에 동행이 필요한 서울시민 (중위소득 100% 이하 연 48회 무료)",
                        ages=ALL, gender="무관", capacity=100, participants=74, manager="demo1"),
    "WLF00001299": dict(target="기준중위소득 60% 이하 자가 · 임차 가구 (반지하 가구 우선)",
                        ages=ALL, gender="무관", capacity=20, participants=18, manager="demo2"),
    "WLF00005247": dict(target="서울시 거주 만 18~34세 근로 청년",
                        ages=["청년"], gender="무관", capacity=100, participants=None, manager="demo2"),
    "WLF00002637": dict(target="만 19~39세 무주택 세대주 (연소득 5천만 원 이하)",
                        ages=["청년"], gender="무관", capacity=150, participants=None, manager="demo2"),
    "WLF00005407": dict(target="돌봄 가족이 일시 부재한 서울시 거주 6~64세 등록 장애인",
                        ages=["청소년", "청년", "중장년"], gender="무관", capacity=30, participants=12, manager="demo2"),
    "WLF00005410": dict(target="서울시 거주 만 6~24세 저소득 · 한부모 · 학교 밖 청소년 등",
                        ages=["청소년", "청년"], gender="무관", capacity=200, participants=None, manager="demo2"),
    "WLF00006578": dict(target="입원 · 건강검진으로 일을 쉰 서울시 취약노동자",
                        ages=ALL, gender="무관", capacity=100, participants=39, manager="demo1"),
    "WLF00006579": dict(target="외롭거나 고립감을 느끼는 서울시민 누구나",
                        ages=ALL, gender="무관", capacity=300, participants=184, manager="demo1"),
    "WLF00004854": dict(target="기준중위소득 50% 이하 전동보장구 이용 장애인",
                        ages=ALL, gender="무관", capacity=60, participants=27, manager="demo2"),
}

# 서비스가 적용되는 시연 기관 (시군구). 원본의 시군구명이 비어 있으면 시 전체 사업 → 그 시의 시연 기관 시군구로 넣는다.
SIGUNGU_BY_SIDO = {"서울특별시": "11680"}
