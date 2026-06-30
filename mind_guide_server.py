"""
마음길잡이 MCP — 정신건강·복지 안내 봇

설계 원칙
- '연결해주는 봇'. 감정 진단·치료 조언 금지.
- 위기 신호 감지 시 추천보다 위기 연락처를 먼저 안내.
- DATA_GO_KR_API_KEY 환경변수가 있으면 공공데이터 API 호출,
  없으면 더미 데이터로 동작(개발·테스트용).

실행:
  pip install -r requirements.txt
  cp .env.example .env  # API 키 입력 후
  python mind_guide_server.py
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus, urlencode

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("마음길잡이")

_API_KEY = os.getenv("DATA_GO_KR_API_KEY", "")
_HOST = os.getenv("HOST", "127.0.0.1")
_PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# 위기 연락처 (출처: 보건복지부, 2024-01-01~ 통합 운영)
# ---------------------------------------------------------------------------
CRISIS_CONTACTS = [
    ("자살예방상담전화",   "109",       "24시간 · 무료"),
    ("정신건강위기상담전화", "1577-0199", "24시간 · 무료"),
    ("보건복지상담센터",   "129",       "24시간 · 무료"),
    ("청소년전화",        "1388",      "24시간 · 무료"),
    ("응급",             "119",       "24시간"),
]

_CRISIS_SIGNALS = [
    "죽고 싶", "자해", "살기 싫", "사라지고 싶", "없어지고 싶",
    "끝내고 싶", "버티기 힘들", "더는 못", "극단적",
]


def _detect_crisis(text: str) -> bool:
    t = (text or "").replace(" ", "")
    return any(s.replace(" ", "") in t for s in _CRISIS_SIGNALS)


def _crisis_block() -> str:
    lines = [
        "⚠️ 지금 많이 힘드신 것 같아요. 혼자 견디지 않으셔도 됩니다.",
        "아래로 연락하면 바로 도움을 받을 수 있어요.", "",
    ]
    for name, num, hours in CRISIS_CONTACTS:
        lines.append(f"· {name}  {num}  ({hours})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 실제 데이터 로드 (전국건강증진센터표준데이터 — 정신보건 필터)
# ---------------------------------------------------------------------------
_DATA_PATH = Path(__file__).parent / "data" / "centers.json"


def _load_centers() -> list[dict]:
    """data/centers.json에서 정신보건 센터만 읽어 내부 형식으로 변환."""
    if not _DATA_PATH.exists():
        return []
    with _DATA_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    centers = []
    for r in raw.get("records", []):
        if r.get("건강증진센터구분") != "정신보건":
            continue
        addr = r.get("소재지도로명주소") or r.get("소재지지번주소", "")
        # 시도명 추출 (주소 첫 토큰: "경기도 화성시..." → "경기")
        region = addr.split()[0].rstrip("도특별시광역") if addr else ""
        start = r.get("운영시작시각", "09:00")
        end = r.get("운영종료시각", "18:00")
        holiday = r.get("휴무일정보", "")
        hours = f"{start}~{end}" + (f" ({holiday} 휴무)" if holiday else "")
        centers.append({
            "region": region,
            "name": r.get("건강증진센터명", ""),
            "phone": r.get("운영기관전화번호") or r.get("관리기관전화번호", ""),
            "hours": hours,
            "addr": addr,
            "업무": r.get("건강증진업무내용", ""),
        })
    return centers


_CENTERS = _load_centers()

_DUMMY_CENTERS = [  # _CENTERS 로드 실패 시 최후 폴백
    {"region": "서울", "name": "서울시 정신건강복지센터", "phone": "02-3444-9934",
     "hours": "평일 09:00~18:00", "addr": "서울 중구", "업무": ""},
]

_DUMMY_WELFARE = [
    {"name": "청년 마음건강 바우처",
     "keywords": ["청년", "스트레스", "직장", "취업", "불안"],
     "desc": "만 19~34세 대상 전문 심리상담 비용 지원(본인부담 일부).",
     "how": "복지로 또는 주민센터 신청"},
    {"name": "산모·신생아 건강관리 및 산후 정서지원",
     "keywords": ["산후", "출산", "육아", "산모"],
     "desc": "출산 가정 대상 건강관리·정서지원 서비스.",
     "how": "보건소·복지로 신청"},
    {"name": "노인 맞춤돌봄 및 정서지원",
     "keywords": ["노인", "어르신", "외로움", "고립"],
     "desc": "독거·취약 어르신 안부확인 및 정서지원 연계.",
     "how": "주민센터 신청"},
    {"name": "일상돌봄 통합지원(돌봄·심리)",
     "keywords": ["돌봄", "보호자", "간병", "소진", "번아웃"],
     "desc": "돌봄이 필요한 가구에 가사·심리지원 등 통합 제공.",
     "how": "주민센터 신청"},
]


# ---------------------------------------------------------------------------
# 공공데이터 API 호출 (data.go.kr)
# ---------------------------------------------------------------------------
# 사용 API:
#   전국정신건강복지센터표준데이터
#   endpoint: https://api.data.go.kr/openapi/tn_pubr_public_imbclty_cnter_api
#   신청: data.go.kr 검색 > "전국정신건강복지센터표준데이터" > 활용신청

_CENTER_API_URL = (
    "https://api.data.go.kr/openapi/tn_pubr_public_imbclty_cnter_api"
)


def _fetch_centers_from_api(region: str, topn: int) -> list[dict] | None:
    """공공데이터 API로 정신건강복지센터를 조회한다. 실패 시 None 반환."""
    if not _API_KEY:
        return None
    try:
        params = {
            "serviceKey": _API_KEY,
            "pageNo": "1",
            "numOfRows": str(topn * 3),  # 여유있게 가져와서 지역 필터
            "type": "xml",
        }
        if region:
            params["ctpvNm"] = region  # 시도명 필터 (서울, 경기 등)

        url = _CENTER_API_URL + "?" + urlencode(params, quote_via=quote_plus)
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        centers = []
        for item in items:
            def g(tag: str) -> str:
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            name = g("instNm") or g("fcltyNm")
            addr = g("rdnmadr") or g("lnmadr")
            phone = g("phoneNumber") or g("telno")
            hours = g("operTime") or "평일 09:00-18:00"
            region_val = g("ctpvNm") or region

            if not name:
                continue
            centers.append({
                "region": region_val,
                "name": name,
                "tags": ["일반"],
                "phone": phone,
                "hours": hours,
                "addr": addr,
            })
        return centers if centers else None
    except Exception:
        return None


def _get_centers(region: str, situation: str, topn: int) -> list[dict]:
    """JSON 파일 데이터 우선, 없으면 API, 그것도 없으면 더미."""
    pool = _CENTERS or _fetch_centers_from_api(region, topn * 3) or _DUMMY_CENTERS

    if region:
        # 주소에 지역명이 포함된 것 우선
        matched = [c for c in pool if region in c.get("addr", "") or region in c.get("region", "")]
        pool = matched or pool

    if situation:
        # 업무 내용에 상황 키워드가 있으면 상위 정렬
        pool = sorted(pool, key=lambda c: -sum(k in c.get("업무", "") for k in situation.split()))

    return pool[:max(1, topn)]


def _get_welfare(situation: str, household: str) -> list[dict]:
    """복지 제도 추천 — 현재는 더미 키워드 매칭 (추후 복지로 API 연동 예정)."""
    text = f"{situation} {household}"
    scored = [(sum(k in text for k in w["keywords"]), w) for w in _DUMMY_WELFARE]
    scored = [(s, w) for s, w in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [w for _, w in scored[:3]] or _DUMMY_WELFARE[:2]


# ---------------------------------------------------------------------------
# MCP 도구
# ---------------------------------------------------------------------------
@mcp.tool()
def crisis_resources(region: str = "") -> str:
    """위기 시 즉시 연락할 수 있는 상담 전화·기관을 안내합니다.
    힘들다는 신호가 조금이라도 보이면 다른 도구보다 먼저 이 도구를 부르세요."""
    return _crisis_block()


@mcp.tool()
def find_counseling_centers(region: str, situation: str = "", topn: int = 3) -> str:
    """지역(region)과 상황(situation: 예 '직장 스트레스', '청년', '산후')을 받아
    가까운 정신건강·심리상담 기관을 추천하고 연락처·운영시간을 안내합니다."""
    out = []
    if _detect_crisis(situation):
        out.append(_crisis_block())
        out.append("\n아래는 이어서 연결해드릴 수 있는 기관이에요.\n")

    centers = _get_centers(region, situation, topn)

    label = f"'{region}'" if region else "전국"
    out.append(f"{label} 기준 상담 가능한 곳을 정리했어요:")
    for c in centers:
        업무 = f"\n  {c['업무']}" if c.get("업무") else ""
        out.append(
            f"\n· {c['name']}"
            f"\n  {c['addr']}"
            f"\n  전화 {c['phone']} · {c['hours']}"
            + 업무
        )
    out.append("\n전화 전 운영시간을 확인하시고, 비용·예약은 기관에 직접 문의해 주세요.")
    return "\n".join(out)


@mcp.tool()
def recommend_welfare(situation: str, age: int | None = None,
                      household: str = "", region: str = "") -> str:
    """현재 상황(situation)을 말로 받아 받을 수 있는 복지·심리지원 제도를 추천합니다.
    age(나이), household(가구형태), region(지역)은 선택 입력입니다."""
    out = []
    if _detect_crisis(situation):
        out.append(_crisis_block())
        out.append("\n급한 마음이 좀 가라앉으면 아래 제도도 살펴보세요.\n")

    picks = _get_welfare(situation, household)

    out.append("상황에 맞을 만한 제도예요(자격은 기관에서 최종 확인):")
    for w in picks:
        out.append(f"\n· {w['name']}\n  {w['desc']}\n  신청: {w['how']}")
    out.append("\n정확한 자격·금액은 복지로(bokjiro.go.kr)나 주민센터 상담을 권해요.")
    return "\n".join(out)


if __name__ == "__main__":
    import uvicorn
    from mcp.server.fastmcp import FastMCP as _FastMCP  # noqa: F401

    app = mcp.streamable_http_app()
    uvicorn.run(app, host=_HOST, port=_PORT)
