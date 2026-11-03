"""2차 5.3 — 국토교통부 아파트 실거래가 API 공통 (매매 상세 · 전월세).

- 요청: serviceKey + LAWD_CD(법정동 시군구 5자리) + DEAL_YMD(YYYYMM) + pageNo/numOfRows, 응답 XML.
- 키: infra/.env 의 DATA_GO_KR_SERVICE_KEY (공공데이터포털 '일반 인증키 (Decoding)' 값).
- 대상 시군구: 강남구 11680, 춘천시 51110 (2023-06 강원특별자치도 개편 코드).
"""
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import io

import pandas as pd
import s3fs

from . import minio_connect, months_arg  # noqa: F401  (재노출)

BASE = "https://apis.data.go.kr/1613000/"
KINDS = {  # 종류 → (API 경로, 원본 보관 폴더)
    "trade": ("RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev", "raw/apt_trade"),
    "rent": ("RTMSDataSvcAptRent/getRTMSDataSvcAptRent", "raw/apt_rent"),
}
LAWD = {  # 법정동 시군구 코드 → (시도명, 시군구명) : 지오코딩 주소와 검증에 쓴다
    "11680": ("서울", "강남구"),
    "51110": ("강원특별자치도", "춘천시"),
}
PAGE_SIZE = 1000
RETRY = 4
RESULT_NO_DATA = "03"


class ApiError(RuntimeError):
    pass


def service_key() -> str:
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY 가 없습니다. infra/.env 를 확인하세요")
    return key


def fetch_page(kind: str, lawd: str, ym: str, page: int, size: int = PAGE_SIZE) -> bytes:
    """한 페이지를 받아 응답 본문(XML bytes)을 그대로 돌려준다. 실패는 지수 대기 후 재시도."""
    path, _ = KINDS[kind]
    query = urllib.parse.urlencode({
        "serviceKey": service_key(), "LAWD_CD": lawd, "DEAL_YMD": ym, "pageNo": page, "numOfRows": size,
    })
    url = BASE + path + "?" + query
    last = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read()
            code, msg = result_code(body)
            if code in ("000", RESULT_NO_DATA):
                return body
            last = ApiError(f"resultCode {code} {msg}")
            if code in ("20", "22", "30", "31", "32"):  # 키 · 승인 · 한도 문제는 재시도해도 같다
                raise last
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
            last = e
        time.sleep(2 ** attempt)
    raise ApiError(f"{kind} {lawd} {ym} p{page}: {last}")


def result_code(body: bytes) -> tuple[str, str]:
    root = ET.fromstring(body)
    hdr = root.find("header")
    if hdr is None:  # 포털 게이트웨이 오류 응답 (<OpenAPI_ServiceResponse>)
        return (root.findtext(".//returnReasonCode") or "?"), (root.findtext(".//returnAuthMsg") or "")
    return (hdr.findtext("resultCode") or "?"), (hdr.findtext("resultMsg") or "")


def parse_items(body: bytes) -> tuple[int, list[dict]]:
    """(totalCount, item 목록). 값은 공백을 제거한 문자열, 빈 값은 ''."""
    root = ET.fromstring(body)
    total = int(root.findtext("body/totalCount") or 0)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall("body/items/item")]
    return total, items


minio = minio_connect  # 호환용 이름


def raw_prefix(bucket: str, kind: str, ym: str) -> str:
    return f"{bucket}/{KINDS[kind][1]}/{ym}"


def read_raw_items(fs: s3fs.S3FileSystem, bucket: str, kind: str, ym: str, lawd: str) -> list[dict]:
    """MinIO 에 보관한 원본 XML 페이지를 읽어 item 목록으로 합친다. 각 item 에 lawd · kind · ym 을 붙인다."""
    items: list[dict] = []
    for key in sorted(fs.glob(f"{raw_prefix(bucket, kind, ym)}/{lawd}_p*.xml")):
        with fs.open(key, "rb") as f:
            _, page_items = parse_items(f.read())
        items.extend(page_items)
    for it in items:
        it["_kind"], it["_lawd"], it["_ym"] = kind, lawd, ym
    return items


# ---- 단지 좌표 캐시 (geocode_apt.py 가 만들고 batch_re_apt_trade.py 가 읽는다)
GEOCODE_CACHE_KEY = "raw/apt_geocode/apt_geocode.csv"
GEOCODE_MANUAL_KEY = "raw/apt_geocode/manual.csv"
GEOCODE_GOOD = ("ok", "nearest", "manual")  # 좌표 · 행정동을 쓸 수 있는 상태


def read_csv(fs: s3fs.S3FileSystem, key: str) -> pd.DataFrame | None:
    """MinIO 의 csv 를 문자열 그대로 읽는다. 없으면 None."""
    if not fs.exists(key):
        return None
    with fs.open(key, "rb") as f:
        return pd.read_csv(io.BytesIO(f.read()), dtype=str, keep_default_na=False)
