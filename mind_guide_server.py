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

_API_KEY = os.getenv("DATA_GO_KR_API_KEY", "")
_HOST = os.getenv("HOST", "0.0.0.0")
_PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP(
    "마음길잡이",
    instructions="""당신은 마음길잡이입니다. 힘든 사람이 실제 상담기관과 복지제도를 찾을 수 있도록 돕는 역할입니다.

## 대화 패턴 (반드시 따르세요)

1. **먼저 공감하고 상황을 파악하세요.**
   사용자가 힘들다고 하면 바로 도구를 호출하지 말고,
   짧게 공감한 뒤 상황을 1~2가지 질문으로 파악하세요.
   예) "많이 힘드셨겠어요. 요즘 어떤 일이 있으셨나요?"

2. **충분히 들은 후, 안내 의사를 먼저 물어보세요.**
   예) "가까운 상담 기관을 찾아드릴까요?"
   사용자가 원한다고 하면 그때 도구를 호출해 안내하세요.

3. **도구 호출 시 지역과 상황을 함께 넘기세요.**
   대화에서 파악한 지역·상황 정보를 find_counseling_centers에 활용하세요.

## 절대 하지 말아야 할 것

- 감정을 진단하지 마세요. ("우울증 같아요", "번아웃이에요" 금지)
- 치료 조언을 하지 마세요.
- 사용자가 원하기 전에 먼저 전화번호를 나열하지 마세요.
- AI가 상담사인 척하지 마세요. 항상 실제 기관 연결로 마무리하세요.

## 위기 상황

'죽고 싶다', '자해', '살기 싫다' 등 명확한 위기 신호가 있을 때만
즉시 crisis_resources를 호출하세요. 단순히 힘들다는 표현은 위기 신호가 아닙니다.
""",
    stateless_http=True,
    host=_HOST,
    port=_PORT,
)

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
        "지금 이 말을 꺼내기까지 많이 힘드셨을 것 같아요.",
        "혼자 버티지 않아도 됩니다. 지금 바로 연락할 수 있는 곳이 있어요.", "",
        "전화 한 통으로 훈련된 상담사와 바로 연결됩니다:",
        "",
    ]
    for name, num, hours in CRISIS_CONTACTS:
        lines.append(f"· {name}  {num}  ({hours})")
    lines += [
        "",
        "전화가 어렵다면 문자나 채팅 상담도 가능해요.",
        "지금 많이 지쳐 있어도, 도움을 받으면 달라질 수 있어요.",
    ]
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
    # ── 청년 ──────────────────────────────────────────────────────────────────
    {
        "name": "청년 마음건강 바우처",
        "keywords": ["청년", "스트레스", "직장", "취업", "불안", "우울", "고립"],
        "desc": "만 19~34세 청년 대상 전문 심리상담 비용 지원(회당 본인부담 1만 원 내외, 연 8~12회).",
        "how": "복지로(bokjiro.go.kr) 또는 주민센터 신청",
    },
    {
        "name": "청소년 정신건강 지원 서비스",
        "keywords": ["청소년", "학교", "왕따", "학업", "10대", "중학생", "고등학생"],
        "desc": "만 9~24세 청소년 대상 심리검사·상담·치료비 지원. 학교 밖 청소년도 가능.",
        "how": "청소년상담복지센터(1388) 또는 주민센터 신청",
    },
    {
        "name": "자립준비청년 심리지원",
        "keywords": ["자립", "보호종료", "청년", "고립", "외로움"],
        "desc": "아동양육시설·위탁가정 퇴소 청년(만 18~24세) 대상 심리상담·멘토링 지원.",
        "how": "아동자립지원사업단 또는 주민센터 문의",
    },
    # ── 산모·육아 ─────────────────────────────────────────────────────────────
    {
        "name": "산모·신생아 건강관리 및 산후 정서지원",
        "keywords": ["산후", "출산", "육아", "산모", "임신", "우울", "산후우울"],
        "desc": "출산 가정 대상 건강관리사 파견·정서지원. 산후우울 위험군엔 심리상담 연계.",
        "how": "보건소·복지로 신청 (출산 후 30일 이내 권장)",
    },
    {
        "name": "아동 심리지원 서비스",
        "keywords": ["아동", "초등학생", "아이", "자녀", "발달", "ADHD", "불안"],
        "desc": "만 18세 이하 아동 대상 심리검사·놀이치료·미술치료 등 지원(소득 기준 있음).",
        "how": "드림스타트·주민센터 신청",
    },
    # ── 노인 ──────────────────────────────────────────────────────────────────
    {
        "name": "노인 맞춤돌봄 서비스",
        "keywords": ["노인", "어르신", "외로움", "고립", "독거", "우울", "60대", "70대", "80대"],
        "desc": "65세 이상 독거·취약 어르신 안부확인·정서지원·사회참여 연계. 우울 고위험군 집중 지원.",
        "how": "주민센터 신청 또는 노인맞춤돌봄시스템",
    },
    {
        "name": "치매 가족 심리지원",
        "keywords": ["치매", "부모", "어르신", "간병", "보호자", "소진"],
        "desc": "치매 환자 가족 대상 상담·힐링 프로그램 지원. 치매안심센터에서 운영.",
        "how": "치매안심센터(치매상담콜 치매안심센터 검색) 또는 보건소",
    },
    # ── 직장·성인 ─────────────────────────────────────────────────────────────
    {
        "name": "근로자 심리상담 서비스(EAP)",
        "keywords": ["직장", "직장인", "번아웃", "회사", "업무", "스트레스", "퇴직", "실직"],
        "desc": "재직·구직 근로자 대상 무료 심리상담. 고용복지플러스센터·근로자지원프로그램(EAP) 운영.",
        "how": "고용복지플러스센터 방문 또는 고용노동부 상담 1350",
    },
    {
        "name": "중독 치료비 지원",
        "keywords": ["중독", "알코올", "도박", "마약", "게임", "술"],
        "desc": "알코올·도박·마약·인터넷 중독자 치료비·재활 프로그램 지원. 중독관리통합지원센터 연계.",
        "how": "중독관리통합지원센터 또는 보건소 문의",
    },
    # ── 돌봄·간병 ─────────────────────────────────────────────────────────────
    {
        "name": "가족돌봄청년(영케어러) 지원",
        "keywords": ["간병", "돌봄", "보호자", "부모", "가족", "청년", "소진"],
        "desc": "가족을 돌보는 만 13~34세 청년 대상 심리상담·일시돌봄 서비스 지원.",
        "how": "주민센터 또는 복지로 신청",
    },
    {
        "name": "일상돌봄 통합지원",
        "keywords": ["돌봄", "보호자", "간병", "소진", "번아웃", "혼자"],
        "desc": "질병·부상 등으로 일상이 어려운 가구에 가사·심리지원 통합 제공.",
        "how": "주민센터 신청",
    },
    # ── 위기·재난 ─────────────────────────────────────────────────────────────
    {
        "name": "재난 심리회복 지원",
        "keywords": ["사고", "재난", "트라우마", "충격", "피해", "PTSD"],
        "desc": "자연재해·사건사고 피해자 대상 심리회복 지원. 국가트라우마센터·정신건강복지센터 연계.",
        "how": "국가트라우마센터(02-2204-0001) 또는 지역 정신건강복지센터",
    },
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


def _normalize_region(region: str) -> list[str]:
    """'서울 용산구' → ['서울', '용산'] 처럼 검색에 쓸 키워드 리스트 반환."""
    tokens = region.replace(",", " ").split()
    keywords = []
    for t in tokens:
        # 시도명 정규화: '서울특별시'·'서울시'·'서울' 모두 '서울'로
        t = t.rstrip("특별시광역자치도")
        if t:
            keywords.append(t)
    return keywords


def _get_centers(region: str, situation: str, topn: int) -> list[dict]:
    """JSON 파일 데이터 우선, 없으면 API, 그것도 없으면 더미."""
    pool = _CENTERS or _fetch_centers_from_api(region, topn * 3) or _DUMMY_CENTERS

    if region:
        keywords = _normalize_region(region)
        # 키워드 중 하나라도 주소에 포함된 것만 필터
        matched = [
            c for c in pool
            if any(k in c.get("addr", "") for k in keywords)
        ]
        if not matched:
            # 매칭 실패 → 엉뚱한 지역 안내하지 않고 빈 목록
            return []
        pool = matched

    if situation:
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
    """사용자가 '죽고 싶다', '자해', '살기 싫다', '사라지고 싶다' 등
    즉각적인 위기 신호를 명확히 표현할 때만 호출하세요.
    단순히 '힘들다', '지쳤다', '도움받고 싶다'는 표현은 위기 신호가 아닙니다.
    그런 경우엔 find_counseling_centers 또는 recommend_welfare를 먼저 사용하세요."""
    return _crisis_block()


@mcp.tool()
def find_counseling_centers(region: str, situation: str = "", topn: int = 3) -> str:
    """사용자가 힘들다, 지쳤다, 상담받고 싶다, 스트레스 받는다고 할 때 호출하세요.
    지역(region)과 상황(situation: 예 '직장 스트레스', '청년', '산후우울', '중독')을 받아
    가까운 정신건강복지센터 연락처·운영시간·담당 업무를 안내합니다.
    지역을 모를 경우 region을 빈 문자열로 호출하세요."""
    out = []
    if _detect_crisis(situation):
        out.append(_crisis_block())
        out.append("\n아래는 이어서 연결해드릴 수 있는 기관이에요.\n")

    centers = _get_centers(region, situation, topn)

    if not centers:
        out.append(f"'{region}' 지역 데이터가 현재 없어요.")
        out.append("자살예방상담전화 109(24시간)로 연락하시면 가까운 기관을 직접 안내받을 수 있어요.")
        return "\n".join(out)

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
    mcp.run(transport="streamable-http")
