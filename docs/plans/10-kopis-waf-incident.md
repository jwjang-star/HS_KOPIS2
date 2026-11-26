# KOPIS WAF 차단 장애 기록 (2026-11-24)

약 두 달 만에 서버를 열어보니 대시보드 공연 목록이 안 떴다. `/api/kopis`가 모든 요청에 500을 뱉고 있었음. 원인은 코드도 Render도 아니고 **KOPIS 쪽이 `python-requests`를 차단하기 시작한 것**. 다음에 "서버는 사는데 특정 API만 죽었다"가 나오면 이 문서부터 볼 것.

## 증상

- `/api/kopis` → 500 (날짜·지역·rows 무엇으로 바꿔도 동일, **0.4초 만에** 즉시 실패)
- `/health` 200, `/docs` 200, `/api/festivals` 200(실데이터 50건), `/api/weather` 200(실데이터) — **다른 엔드포인트는 전부 정상**
- 대시보드에는 "FastAPI 서버에 연결할 수 없습니다"로만 표시됨

## 원인

KOPIS가 WAF를 걸어서 `python-requests/2.x` 기본 User-Agent를 차단한다. 차단 시 XML이 아니라 HTML을 돌려줌:

```
GET http://www.kopis.or.kr/openApi/restful/pblprfr  (UA: python-requests)
→ HTTP 400  <HTML><HEAD><TITLE>400 Bad Request</TITLE></HEAD><BODY><H1>Request Blocked</H1>
→ ET.fromstring(response.content) → ParseError: syntax error: line 1, column 48
→ 500
```

브라우저 UA 헤더 하나만 붙이면 200 + 정상 XML. http/https, www 유무 전부 무관하고 **오직 UA만 본다**(검증: UA 없음 12회 전부 400, UA 있음 24회 전부 200).

## 진단에 실제로 도움된 것

1. **curl은 되는데 코드는 안 되는 상황** — curl로 같은 URL을 때리면 멀쩡한 XML이 왔다. 여기서 "KOPIS 서버/키 문제가 아니라 우리 쪽 요청 특성 문제"로 범위가 좁혀졌다. curl은 자기 UA를 보내서 차단을 안 당했던 것.
2. **로컬에서 그대로 재현** — `uvicorn main:app --reload`로 띄우고 호출하니 Render와 똑같이 ParseError. 트레이스백이 `main.py:74 ET.fromstring`을 정확히 가리켰다. 라이브 로그 접근 없이 원인을 잡을 수 있었음.
3. 실패 응답의 **본문 앞부분을 직접 찍어본 것** — `print(r.content[:300])` 한 줄로 `Request Blocked`가 바로 보였다.

## 조치 (`d1236e7`)

```python
# KOPIS WAF가 python-requests 기본 UA를 "400 Request Blocked"로 차단함 → 브라우저 UA 필수
KOPIS_HEADERS = {"User-Agent": "Mozilla/5.0"}
```

- KOPIS 호출 2곳(`/api/kopis`, `/api/send-daily-email`)에 `headers=KOPIS_HEADERS` 적용
- `/api/kopis`에 `timeout=10` 추가 (원래 타임아웃이 아예 없었음)
- XML 파싱 실패 시 500이 아니라 **502 + upstream 상태코드·응답 앞 200자**를 노출. 다음에 또 막히면 로그 안 봐도 화면에 `KOPIS 응답이 XML이 아님 (status=400): ...Request Blocked...`로 찍힌다.

## 같이 드러난 조용한 사고 — 빈 메일 발송

`/api/send-daily-email`의 KOPIS 호출도 같은 차단을 당하고 있었는데, 이쪽은 `except Exception: performances = []`로 삼키고 있었다. 즉 **차단된 기간 내내 "공연 0건"짜리 빈 메일이 지점에 정상 발송된 것처럼 나갔다.** 500으로 티가 난 `/api/kopis`와 달리 아무도 모를 뻔했음.

[[03-render-env-var-incident]]의 "200 OK는 성공의 증거가 아님"과 같은 계열의 함정이다. **조용히 빈 값을 반환하는 설계**(작업 원칙상 의도된 것)는 키/네트워크 사고를 숨기므로, 외부 API 연동이 늘어날수록 "빈 결과가 정상인지 사고인지" 구분할 방법을 같이 둬야 한다.

## 별건 1 — 푸시했는데 배포가 안 돌았음

`git push origin master`로 올렸더니 Render가 아무 반응이 없었다. 이 리포는 **로컬 `master` / 배포 `main`** 구조라 `git push origin master:main`이어야 한다(README 작업 원칙 참고). `origin/master`는 9/8에서 멈춰 있던 방치 브랜치라, 거기 푸시해봐야 아무 데도 반영되지 않는다. 푸시 후 2~3분 안에 라이브가 안 바뀌면 **브랜치부터 확인할 것**.

## 별건 2 — "연결 실패" 배지 (`be3f18e`)

백엔드를 고친 뒤에도 대시보드 배지가 빨간 "연결 실패"였다. 서버는 200인데 `checkServer()`의 타임아웃이 4초였고, Render 실측이 그보다 느렸던 것:

| 대상 | 응답 시간 |
|---|---|
| localhost `/api/kopis` (Supabase 미연결) | 0.10초 |
| live `/health` | 0.25초 |
| live `/api/holidays` (캐시) | 0.25초 |
| live `/api/festivals` | 5.5초 |
| **live `/api/kopis`** | **7.5초** (3회 모두 7.4~7.8초) |

Render 무료 인스턴스(미국 리전)에서 한국 KOPIS + Supabase를 왕복하는 구조상 7.5초가 **정상값**이다. 버그도 슬립도 아님. `index.html`의 `checkServer()` 타임아웃을 4초 → 15초로 올려 해결. 나머지 fetch 타임아웃(공연 12초·축제 15초·날씨 18초)은 실측 대비 여유가 있어 그대로 뒀다.

> 근본 처방은 Render 리전을 한국 가까이(싱가포르) 옮기는 것인데, 리전 변경은 서비스 재생성이라 별건으로 남김.

## 로컬에서 띄울 때 주의

```bash
cd HS_KOPIS2-main
PYTHONIOENCODING=utf-8 python -m uvicorn main:app --reload --port 8000
```

- `PYTHONIOENCODING=utf-8` 없으면 Windows 콘솔(cp949)이 `print("🚨...")`에서 `UnicodeEncodeError`로 터져서 **원인과 무관한 500**이 난다. Render는 UTF-8이라 무관.
- `SUPABASE_KEY` 없이 띄우면 `supabase = None`이라 적재 경로를 건너뛴다 → 응답의 `is_new`가 전부 `true`로 나오는 건 정상.
- 서버 루트(`/`)는 라우트가 없어 `{"detail":"Not Found"}`가 뜬다. 정상이며, 확인은 `/health`나 `/docs`로 할 것.

## 최종 확인 (2026-11-24)

- 라이브 `/api/kopis` **10회 연속 200**, 실데이터 정상(`PF307279 옷깃 프로젝트 [청주]` 등). 지역 필터(`signgucode=11`)도 200
- GitHub Pages 반영 확인 — `timeout(4000)` 잔존 0건
- 중간에 502가 1회 떴으나 직후 13회 연속 200. KOPIS 쪽 간헐적 차단으로 보이며 상시 문제가 아니라 재시도 로직은 넣지 않았다. **502 메시지가 자주 보이기 시작하면 그때 재시도 1회를 넣을 것.**

## 보류 중인 건

GitHub Pages 주소에서 `jwjang-star.github.io`를 떼는 작업(커스텀 도메인 연결). 방법은 커스텀 도메인뿐이며 ①도메인 결정 ②DNS CNAME → `jwjang-star.github.io.` ③리포 루트에 `CNAME` 파일 ④GitHub Settings → Pages에서 등록 + HTTPS 적용, 4단계가 필요하다. 2026-11-24 기준 보류. 진행할 때 **`index.html:2181`에 하드코딩된 `https://hs-kopis.onrender.com/api/send-selected`도 같이 정리할 것** — 서버 주소를 바꿔도 이 호출만 옛 주소로 샌다.
