# Phase 7 — 캘린더 날씨 (기상청 중기예보)

**상태: 구현 + 로컬 브라우저 검증 완료 (2026-09-07). 프로덕션 배포 대기 — Render에 `KMA_MID_API_KEY` 등록 필요.**

## 배경

캘린더는 앞으로의 공연·축제를 보고 계획하는 뷰인데 날씨가 없었다. 사용자가 기상청 **중기예보 조회서비스**(data.go.kr `15059468`, `1360000/MidFcstInfoService`) 활용신청·발급 완료. **캘린더에만** 반영("너무 여러 군데 들어가는 것보다") — 지도·리스트·이메일·그리드 뷰 무변경.

중기예보 실제 커버리지(2026-09-07 실키 확인): **D+4 ~ D+10** (7일). D+3 필드는 과거 개편 때 제거됨. 발표 1일 2회(06시/18시). D+0~D+3(오늘~모레)는 단기예보 영역이라 이번 범위 아님 → 캘린더 근접일엔 날씨 없음.

## 구현

### `main.py` (축제 섹션 다음, +114줄 — 전부 격리 추가)

- `KMA_MID_API_KEY`(env), `MID_BASE = "http://apis.data.go.kr/1360000/MidFcstInfoService"`
- `KOPIS_TO_MID_REGID` — signgucode → (중기육상 regId, 중기기온 도시 regId). "" → 서울. 17개 지역 전부 2026-09-07 실키로 getMidTa 응답 확인
- `_mid_tmfc()` — KST 기준 발표시각(`now.hour >= 18` → 오늘 1800 / `>= 6` → 오늘 0600 / else 어제 1800)
- `fetch_mid_weather(land_reg, ta_reg)` — `getMidLandFcst`(wf, rnSt) + `getMidTa`(taMin/Max) 각각 호출, D+4~D+10을 `{"YYYYMMDD": {"wf","pop","tmn","tmx"}}`로 병합. D+4~D+7은 오후(`wfNPm`) + 강수확률 max(오전,오후), D+8~D+10은 단일값. 부분 실패 허용, 키 없으면 `{}`
- `_weather_cache` / `_weather_cached_at` (키 `(land_reg, ta_reg)`), TTL **3시간** — 공휴일/축제와 동일한 모듈 레벨 캐시 패턴
- `get_weather_for_region(signgucode)` — 매핑 → 캐시. 알 수 없는 코드는 서울 폴백
- `@app.get("/api/weather/mid")` `region` 파라미터 → `{"status":"success","base_date":..., "days":{...}}`. 실패해도 200 + 빈 `days`
- `/api/kopis`·`/api/festivals`·`/api/holidays`·발송 경로 **무수정**

### `index.html` (캘린더 함수만, +75/−2줄)

- 전역 `calWeather`, `calWeatherKey`
- `_wxEmoji(wf)` — "맑음"→☀️ "구름많음"→⛅ "흐림"→☁️ "비"→🌧️ "눈"→🌨️ "소나기"→🌦️
- `calMonthHasWeather()` — 지금 그리는 달이 `[오늘+4, 오늘+10]`과 겹치나
- `loadCalendarWeather()` — 겹칠 때만 `fetch(base + "/api/weather/mid?region=" + selCode)`. 캐시키 `selCode|base`, 서버 바뀌면 초기화. 자체 try/catch(리젝트 안 함)
- `renderCalendar()` — `await loadCalendarMonth()` → `await Promise.all([loadCalendarMonth(), loadCalendarWeather()])`
- `renderCalGrid()` — 셀 최상단에 `.cal-cell-top` flex 행 신설(`daynum` + `.cal-wx`). `.cal-wx` = `{emoji}{tmx}°/{tmn}°`, 강수확률 ≥50%면 `☔{pop}` 덧붙임
- `renderCalDayList()` — 헤더 밑에 `.cal-daylist-wx` 한 줄(`⛅ 구름많음 · 28° / 18° · 강수확률 20%`)
- CSS: `.cal-cell-top`(flex, gap 5px), `.cal-wx`, `.cal-daylist-wx`

## 검증 (2026-09-07 로컬, 실키 = 기존 data.go.kr 키)

- `/api/weather/mid?region=11` → 7일(09-11~09-17) 각 `{wf, pop, tmn, tmx}`. `region=26/50/""` 지역별로 다른 값. `region=99` → 서울 폴백. 키 제거 시 `days: {}` 200
- 브라우저: 캘린더 9월 → 11~17일 셀에 `11 ☀️26°/16°` 형태 칩. 지역탭 부산 클릭 → `28°/20°`로 갱신. 10월 이동 → 칩 0개. 날짜 클릭 → 상세에 날씨 한 줄
- **스코프 확인**: 그리드 뷰·지도·리스트에 날씨 없음(`cal-wx` 0개)
- 회귀: `/api/kopis`·`/api/holidays`·`/api/festivals` 정상. 콘솔·서버 에러 0. `node --check` 통과

## 배포

1. **Render Environment에 `KMA_MID_API_KEY` 추가** — 값은 `FESTIVAL_API_KEY`와 **동일**(같은 data.go.kr 일반 인증키. 사용자가 중기예보 서비스 활용신청 완료). **Decoding 형태** — Encoding(`%2B`) 넣으면 이중인코딩 사고([[03]])
2. `git push origin master:main` → Render 재배포(백엔드 변경)
3. 프로덕션 `/api/weather/mid?region=11` 확인, 캘린더에서 날씨 노출 확인
   - 키 없이 배포해도 안전(캘린더는 날씨 없이 정상)

## 운영/로컬 참고

- `getMidLandFcst`/`getMidTa` 응답 봉투: `response.body.items.item[0]` 단일 행. 필드 `wf4Am/Pm`~`wf10`, `rnSt4Am/Pm`~`rnSt10`, `taMin4`~`taMax10`
- `wfN` → 날짜 = `tmFc의 날짜 + N일`
- 중기예보는 하루 2회(06/18시)만 갱신 → 3시간 캐시로 충분. Render 재시작 시 캐시 비지만 무료 API라 비용 없음
- data.go.kr 4번째 키(`KASI`/`FESTIVAL`/`TOUR` 다음) — 전부 같은 값

## 범위 밖

- D+0~D+3 날씨(단기예보 `getVilageFcst` — 별도 서비스 활용신청 필요)
- 지도/리스트/그리드/이메일 날씨
- 시간별 예보, 강수량(mm), 미세먼지, 날씨 기반 인사이트 코멘트
