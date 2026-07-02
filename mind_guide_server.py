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
    instructions="""당신은 마음길잡이입니다. 정신건강 상담기관과 복지제도로 연결해주는 따뜻한 안내자입니다.

## 말투와 태도

- 따뜻하고 진심 어린 상담사처럼 대화하세요. 위로하고, 격려하고, 친절하고,
  온화하고, 편안하고 안정감 있게. 사용자가 "이 사람은 나를 이해해준다"고
  느끼는 것이 최우선입니다.
- 사용자가 쓴 단어를 그대로 받아서 마음을 알아주세요.
  (예: "실직까지 겹쳤으니 하루하루가 얼마나 무거우셨을까요. 그동안 정말 애쓰셨어요.")
- 위로가 먼저, 질문은 그 다음. 질문은 한 번에 하나만.
- 짧고 부드러운 문장을 쓰세요. "~해 주실 수 있을까요?", "~찾아드리겠습니다" 같은
  사무적인 안내문 말투는 금지입니다.
- 절대 진단하거나 판단하지 마세요. ("우울증 같아요", "번아웃이에요" 금지)

## 낙인 제거와 용기 북돋기 (매우 중요)

도움을 받으러 가는 것에 대해 사용자가 망설이거나 부담을 느낄 수 있습니다.
추천을 안내할 때 반드시 아래 메시지를 자연스럽게 녹여주세요.

- "마음이 힘든 건 감기 걸린 것과 같아요. 치료받는 게 당연한 거예요."
- "상담 받는다고 큰 문제가 있는 사람인 게 아니에요. 오히려 용기 있는 거예요."
- "지금 연락하는 게 절대 늦지 않았어요."
- "혼자 다 해결하려고 버텨온 것 자체가 이미 대단한 거예요."
- "잘못한 게 없어요. 누구나 이런 시간이 올 수 있어요."

모든 말을 다 쓸 필요는 없고, 상황에 맞는 한두 마디를 골라 자연스럽게 건네세요.

## 대화 흐름 (단계별로 따르세요)

### 1단계 — 온전히 공감만 하는 턴
힘들다는 말이 나온 첫 턴에는 도구를 쓰지 말고, 상담기관·복지제도 이야기도
아예 꺼내지 마세요. 오직 마음을 받아주고 어떤 일이 있었는지 하나만 물어보세요.
예) "그 말을 꺼내기까지도 쉽지 않으셨을 것 같아요. 요즘 어떤 일들이 마음을
무겁게 하고 있어요?"

### 2단계 — 충분히 들은 후 안내 의사 확인
2~3번 대화를 나눈 뒤, 안내 여부를 먼저 물어보세요.
예) "말씀해주신 상황에 맞는 상담 기관이나 지원 제도를 찾아드릴까요?"

### 3단계 — 도구 호출 후 추천 안내
사용자가 원하면 도구를 호출해 안내하세요.
대화에서 파악한 지역·상황을 꼭 파라미터에 담으세요.
추천 결과를 그대로 읽어주지 말고, 자연스럽게 소개해주세요.
예) "○○ 기관에 전화 한 통만 하시면 되는데, 처음엔 보통 이렇게 진행돼요..."

### 4단계 — 원하면 첫 이용 가이드 안내
추천 후 실제로 해볼 마음이 있는지 물어보고,
사용자가 원하면 usage_guide 도구를 호출해 단계별 절차를 안내하세요.

### 5단계 — 마무리 체크인
안내가 끝난 후 대화를 바로 끊지 말고 한마디 더 건네세요.
예) "연락해보시고 어떻게 됐는지 알려주실 수 있어요? 같이 다음 단계도 생각해볼게요."

## 위기 상황

'죽고 싶다', '자해', '살기 싫다' 등 명확한 위기 신호가 있을 때만
즉시 crisis_resources를 호출하세요.
단순히 힘들다, 지쳤다는 표현은 위기 신호가 아닙니다.
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

# 한국사회보장정보원_복지서비스정보 (odcloud)
_WELFARE_API_URL = (
    "https://api.odcloud.kr/api/15083323/v1"
    "/uddi:3929b807-3420-44d7-a851-cc741fce65a1"
)


def _fetch_welfare_from_api(situation: str, topn: int) -> list[dict] | None:
    """복지로 API로 복지서비스를 조회한다. 실패 시 None 반환."""
    if not _API_KEY:
        return None
    try:
        params = urlencode({
            "page": "1",
            "perPage": "100",
            "serviceKey": _API_KEY,
        })
        resp = httpx.get(f"{_WELFARE_API_URL}?{params}", timeout=8.0)
        resp.raise_for_status()
        items = resp.json().get("data", [])

        if situation:
            keywords = situation.replace(",", " ").split()
            scored = []
            for item in items:
                text = item.get("서비스명", "") + item.get("서비스요약", "")
                score = sum(k in text for k in keywords)
                if score > 0:
                    scored.append((score, item))
            scored.sort(key=lambda x: -x[0])
            items = [item for _, item in scored]

        result = []
        for item in items[:max(1, topn)]:
            contact = item.get("대표문의", "복지로 129")
            link = item.get("서비스URL", "https://www.bokjiro.go.kr")
            result.append({
                "name": item.get("서비스명", ""),
                "desc": item.get("서비스요약", ""),
                "how": f"{contact} / 복지로(bokjiro.go.kr)에서 신청",
                "keywords": [],
            })
        return result if result else None
    except Exception:
        return None


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

    keywords = _normalize_region(region) if region else []
    if keywords:
        # 키워드 중 하나라도 주소에 포함된 것만 필터
        matched = [
            c for c in pool
            if any(k in c.get("addr", "") for k in keywords)
        ]
        if not matched:
            # 매칭 실패 → 엉뚱한 지역 안내하지 않고 빈 목록
            return []
        pool = matched

    # 지역 키워드가 많이 겹칠수록(구 단위 일치 등) 앞으로, 그 다음 상황 일치순
    sit_keywords = situation.split() if situation else []
    pool = sorted(pool, key=lambda c: (
        -sum(k in c.get("addr", "") for k in keywords),
        -sum(k in c.get("업무", "") for k in sit_keywords),
    ))

    return pool[:max(1, topn)]


def _get_welfare(situation: str, household: str) -> list[dict]:
    """복지 제도 추천 — 실데이터 API 우선, 실패 시 더미 데이터."""
    text = f"{situation} {household}"
    api_results = _fetch_welfare_from_api(text, 3)
    if api_results:
        return api_results
    scored = [(sum(k in text for k in w["keywords"]), w) for w in _DUMMY_WELFARE]
    scored = [(s, w) for s, w in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [w for _, w in scored[:3]] or _DUMMY_WELFARE[:2]


# ---------------------------------------------------------------------------
# MCP 도구
# ---------------------------------------------------------------------------
@mcp.tool(annotations={"title": "마음길잡이 — 위기 연락처 안내"})
def crisis_resources(region: str = "") -> str:
    """마음길잡이 위기 연락처 안내 도구.
    사용자가 '죽고 싶다', '자해', '살기 싫다', '사라지고 싶다' 등
    즉각적인 위기 신호를 명확히 표현할 때만 호출하세요.
    단순히 '힘들다', '지쳤다', '도움받고 싶다'는 표현은 위기 신호가 아닙니다.
    그런 경우엔 find_counseling_centers 또는 recommend_welfare를 먼저 사용하세요."""
    return _crisis_block()


@mcp.tool(annotations={"title": "마음길잡이 — 정신건강복지센터 찾기"})
def find_counseling_centers(region: str, situation: str = "", topn: int = 3) -> str:
    """마음길잡이 상담기관 안내 도구. 대화에서 파악한 지역·상황에 맞는 정신건강복지센터의
    연락처·운영시간·담당 업무를 안내합니다.

    대화 태도(모든 턴에서 지키세요): 당신은 따뜻하고 진심 어린 상담사처럼 말합니다.
    사용자가 한 말을 그대로 받아 마음을 알아주세요.
    (예: "실직까지 겹쳤으니 하루하루가 얼마나 무거우셨을까요. 그동안 정말 애쓰셨어요.")
    위로와 격려를 먼저, 질문은 그 다음에 한 번에 하나만. 문장은 짧고 부드럽게.
    "~해 주실 수 있을까요?", "~찾아드리겠습니다" 같은 사무적인 안내문 말투는 쓰지 마세요.
    정보(지역 등)를 물을 때도 반드시 공감 한두 문장을 먼저 건넨 뒤 물어보세요.

    호출 시점(중요):
    - 사용자가 처음 힘든 마음을 털어놓은 턴에는 이 도구를 호출하지 말고,
      상담기관·복지제도 이야기도 아예 꺼내지 마세요. 그 턴은 오직 마음을 받아주고
      어떤 일이 있었는지 하나만 물어보는 턴입니다.
    - 두 번째 턴부터 자연스럽게 "괜찮으시면 도움받을 수 있는 곳을 같이 찾아볼까요?"라고
      부드럽게 제안하고, 지역·상황을 파악한 뒤 사용자가 원할 때 호출하세요.
    - 단, '죽고 싶다' 등 명확한 위기 신호가 보이면 대화를 끌지 말고 즉시
      crisis_resources를 호출하세요.

    region: 대화에서 파악한 지역(예 '화성', '서울'). 끝내 모르면 빈 문자열.
    situation: 대화에서 파악한 상황(예 '직장 스트레스', '실직', '청년', '산후우울', '중독')."""
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
    keywords = _normalize_region(region) if region else []
    if keywords and not any(
        all(k in c.get("addr", "") for k in keywords) for c in centers
    ):
        out.append("(말씀하신 지역과 정확히 일치하는 기관 데이터가 없어, 같은 지역권의 가까운 기관을 안내해요.)")
    for c in centers:
        업무 = f"\n  {c['업무']}" if c.get("업무") else ""
        out.append(
            f"\n· {c['name']}"
            f"\n  {c['addr']}"
            f"\n  전화 {c['phone']} · {c['hours']}"
            + 업무
        )
    out.append("\n처음이라 뭐라고 말할지 막막하면, 상담을 받고 싶어 연락했다고만 해도 충분해요.")
    out.append(
        "\n[AI 참고: 이 도구 결과는 사용자 화면에 보이지 않습니다. 위 기관 목록"
        "(이름·전화번호·운영시간)을 반드시 응답 본문에 포함해서 보여주세요."
        " 목록 앞에는 사용자의 마음을 알아주는 말 한 문장을, 목록 뒤에는"
        " '혼자 다 감당하지 않아도 된다'는 안심과 함께 연락해볼 마음이 드는지"
        " 부드럽게 물어보세요. 이용 방법을 궁금해하면 usage_guide 도구로 안내하세요.]"
    )
    return "\n".join(out)


@mcp.tool(annotations={"title": "마음길잡이 — 복지제도 추천"})
def recommend_welfare(situation: str, age: int | None = None,
                      household: str = "", region: str = "") -> str:
    """마음길잡이 복지제도 추천 도구. 대화에서 파악한 상황에 맞는 복지·심리지원 제도를 추천합니다.

    대화 태도: 따뜻하고 진심 어린 상담사처럼 말하세요. 사용자의 말을 그대로 받아
    마음을 알아주고, 위로와 격려를 먼저 건넨 뒤 질문은 한 번에 하나만.
    사무적인 안내문 말투는 쓰지 마세요.

    호출 시점(중요):
    - 사용자가 처음 힘든 마음을 털어놓은 턴에는 호출하지 말고, 제도 이야기도
      꺼내지 마세요. 그 턴은 오직 공감하는 턴입니다.
    - 두 번째 턴부터 자연스럽게 상황(나이대, 가구형태, 어떤 어려움인지)을 파악하고,
      받을 수 있는 지원을 같이 찾아볼지 부드럽게 물어본 뒤 사용자가 원할 때 호출하세요.
    - 단, 명확한 위기 신호가 보이면 즉시 crisis_resources를 호출하세요.

    situation: 대화에서 파악한 상황(예 '실직으로 지친 30대', '산후우울', '독거 어르신').
    age(나이), household(가구형태), region(지역)은 파악된 만큼만 선택 입력."""
    out = []
    if _detect_crisis(situation):
        out.append(_crisis_block())
        out.append("\n급한 마음이 좀 가라앉으면 아래 제도도 살펴보세요.\n")

    picks = _get_welfare(situation, household)

    out.append("상황에 맞을 만한 제도예요(자격은 기관에서 최종 확인):")
    for w in picks:
        out.append(f"\n· {w['name']}\n  {w['desc']}\n  신청: {w['how']}")
    out.append("\n✅ 첫 번째 할 일:")
    out.append("  복지로(bokjiro.go.kr)에서 '복지서비스 모의계산'으로 내가 받을 수 있는지 먼저 확인해보세요.")
    out.append("  인터넷이 어려우시면 주민센터에 방문하거나 복지로 콜센터(129)에 전화해도 됩니다.")
    out.append(
        "\n[AI 참고: 이 도구 결과는 사용자 화면에 보이지 않습니다. 위 제도 목록"
        "(이름·내용·신청 방법)을 반드시 응답 본문에 포함해서 보여주세요."
        " 목록 앞에는 사용자의 마음을 알아주는 말 한 문장을, 목록 뒤에는"
        " '받을 수 있는 도움은 당연히 받아도 된다'는 안심과 함께 신청해볼 마음이"
        " 드는지 부드럽게 물어보세요. 신청 방법을 궁금해하면 usage_guide 도구로 안내하세요.]"
    )
    return "\n".join(out)


_GUIDE_COUNSELING = """상담기관 첫 이용, 이렇게 진행돼요:

1️⃣ 운영시간 내에 전화하기
   "상담을 받고 싶어서 연락했어요"라고만 해도 충분해요.
   전화가 부담되면 기관에 직접 방문해도 됩니다.

2️⃣ 간단한 안내 질문에 답하기
   거주 지역, 나이, 어떤 어려움인지 등을 물어봐요.
   편한 만큼만 이야기하면 되고, 비밀은 보장됩니다.

3️⃣ 초기 상담 일정 잡기
   보통 며칠 안에 첫 상담 날짜를 잡아줘요. 방문 시 신분증을 챙기세요.

4️⃣ 첫 상담 (30분~1시간)
   지금 상황을 편하게 이야기하면, 담당자가 맞는 프로그램이나
   필요하면 다른 기관·제도로 연결해줍니다.

💰 비용: 정신건강복지센터 상담은 대부분 무료예요.
📌 처음 한 번만 용기 내면, 그 다음은 기관이 이끌어줘요."""

_GUIDE_WELFARE = """복지제도 신청, 이렇게 진행돼요:

1️⃣ 자격 확인하기
   복지로(bokjiro.go.kr) → '복지서비스 모의계산'에서
   소득·나이 기준으로 받을 수 있는지 먼저 확인해보세요.

2️⃣ 신청하기 (둘 중 편한 방법으로)
   · 온라인: 복지로에서 신청 (공동인증서 필요)
   · 방문: 주소지 주민센터에 신분증 들고 방문
   뭘 준비할지 모르겠으면 빈손으로 가서 물어봐도 됩니다.

3️⃣ 심사 기다리기
   보통 2~4주 안에 결과가 문자·우편으로 와요.

4️⃣ 이용 시작
   선정되면 안내에 따라 바우처 사용·서비스 이용을 시작하면 됩니다.

📞 중간에 막히면 보건복지상담센터 129(24시간)에 물어보세요.
📌 신청했다가 안 되더라도 불이익은 전혀 없어요."""


@mcp.tool(annotations={"title": "마음길잡이 — 첫 이용 가이드"})
def usage_guide(kind: str = "counseling") -> str:
    """마음길잡이 첫 이용 가이드 도구. 상담기관이나 복지제도를 추천한 뒤,
    사용자가 "실제로 해보고 싶다", "어떻게 하는 거예요?", "신청 방법이 궁금해요"처럼
    다음 단계를 물을 때 호출하세요. 추천 전에 미리 호출하지 마세요.

    kind: 'counseling'(상담기관 첫 전화·방문 절차) 또는 'welfare'(복지제도 신청 절차)."""
    guide = _GUIDE_WELFARE if kind == "welfare" else _GUIDE_COUNSELING
    return (
        guide
        + "\n\n[AI 참고: 이 도구 결과는 사용자 화면에 보이지 않습니다. 위 단계들을"
        " 응답 본문에 포함해 사용자 상황에 맞게 풀어서 안내하고, 마지막에"
        " 연락해보고 어땠는지 나중에 알려달라고 따뜻하게 한마디 건네세요.]"
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
