# 마음길잡이 MCP

카카오 PlayMCP용 정신건강·복지 안내 MCP 서버. "근처 상담할 곳 있을까?" 같은
카카오톡 한 줄 질문에 위치·상황을 받아 상담기관·복지제도를 안내한다.
대화 내역을 읽지 않고, 사용자가 말로 주는 정보만으로 동작한다.

프로젝트 맥락·다음 할 일은 `CLAUDE.md` 참고.

## 실행
```bash
pip install -r requirements.txt
python mind_guide_server.py
# → http://127.0.0.1:8000/mcp 에서 streamable-http 로 동작
```

## 도구
- `crisis_resources(region="")` — 위기 시 즉시 연락처 안내
- `find_counseling_centers(region, situation="", topn=3)` — 상담기관 추천
- `recommend_welfare(situation, age=None, household="", region="")` — 복지제도 추천

추천 도구는 위기 신호를 먼저 감지해, 신호가 있으면 위기 연락처를 앞에 안내한다.

## PlayMCP 등록
1. 서버를 공개 URL(HTTPS)로 배포한다.
2. playmcp.kakao.com 접속 → 카카오 로그인 → 개발자 콘솔에서
   원격 MCP 서버 등록 → 배포 주소의 `/mcp` URL 입력.
3. AI 채팅에서 도구가 호출되는지 테스트.

## 주의
- 데이터는 현재 더미. 실제 배포 전 `_CENTERS`/`_WELFARE`를 보건복지부 API로 교체.
- `CRISIS_CONTACTS`의 전화번호는 배포 전 최신 여부를 반드시 재확인할 것.
