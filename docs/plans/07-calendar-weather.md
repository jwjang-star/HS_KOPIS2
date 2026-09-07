# Phase 7 — 캘린더 날씨 (기상청 단기예보 + 중기예보)

**상태: 구현 + 로컬 브라우저 검증 완료 (2026-09-07). 프로덕션 배포 대기 — Render에 `KMA_MID_API_KEY` 등록 필요.**

## 배경

캘린더는 앞으로의 공연·축제를 보고 계획하는 뷰인데 날씨가 없었다. 사용자가 기상청 예보 API 활용신청·발급 완료. **캘린더에만** 반영("너무 여러 군데 들어가는 것보다") — 지도·리스트·이메일·그리드 뷰 무변경.

처음엔 중기예보만(D+4~D+10) 넣었으나 사용자 요청으로 **단기예보(D+0~D+3)까지 합쳐 오늘~10일 전 구간** 커버.

- **단기예보** `getVilageFcst` (data.go.kr `15084084`, `1360000/VilageFcstInfoService_2.0`) — 오늘 + 3일. ⚠️ 구버전 `VilageFcstInfoService`(_2.0 없음)는 폐기됨(`NO_OPENAPI_SERVICE_ERROR`)
- **중기예보** `getMidLandFcst`+`getMidTa` (data.go.kr `15059468`, `1360000/MidFcstInfoService`) — D+4~D+10. D+3 필드는 개편 때 제거돼서 D+4부터
- 둘 다 **기존 data.go.kr 일반 인증키로 조회됨**(2026-09-07 실키 확인). 별도 활용신청 필요 없었음(계정 공용)

## 구현

### `main.py` (날씨 섹션, 축제 다음 — 전부 격리 추가)

- `KMA_MID_API_KEY`(env, 단기·중기 공용), `MID_BASE`, `SHORT_BASE`
- `KOPIS_TO_WEATHER` — signgucode → `(중기육상 regId, 중기기온 도시 regId, 단기 격자 nx, ny)` 4-튜플. "" → 서울. 17개 지역 전부 2026-09-07 실키 검증
- `_to_int(v)` — `round(float(...))`로 `"29.0"` 같은 소수 문자열도 처리
- `_mid_tmfc()` — 중기 발표시각(KST 06/18시)
- `_short_base()` — 단기 base_date/time(KST, 발표 02/05/08/11/14/17/20/23시, ~45분 뒤 조회)
- `_vilage_wf(sky_list, pty_set)` — 단기 SKY(1맑음/3구름많음/4흐림) + PTY(1비/2비눈/3눈/4소나기/…) → 한 단어. 강수 있으면 비/눈, 없으면 낮 SKY 최빈값
- `fetch_short_weather(nx, ny)` — `getVilageFcst` 1회, 오늘~D+3 각 날짜를 TMX/TMN/POPmax/낮시간 SKY·PTY로 집계 → `{"YYYYMMDD": {wf,pop,tmn,tmx}}`
- `fetch_mid_weather(land_reg, ta_reg)` — `getMidLandFcst`(wf, rnSt) + `getMidTa`(taMin/Max), D+4~D+10 병합. D+4~7은 오후(`wfNPm`) + 강수확률 max(오전,오후)
- `get_weather_for_region(signgucode)` — `fetch_mid_weather` + `fetch_short_weather` 병합(**단기가 D+0~D+3, 중기가 D+4~D+10, 겹치면 단기 우선**). 완전결과 **1시간** 캐시(단기예보가 8회/일 갱신), 기온 누락 등 부분결과는 15분 후 재시도(`tmx` 유무로 판단). 알 수 없는 signgucode는 서울 폴백
- `@app.get("/api/weather")` `region` → `{"status":"success","base_date":오늘,"days":{...}}`. 실패해도 200 + 빈 `days`. KMA 호출 타임아웃 8s
- `/api/kopis`·`/api/festivals`·`/api/holidays`·발송 경로 **무수정**

### `index.html` (캘린더 함수만)

- 전역 `calWeather`, `calWeatherKey`
- `_wxEmoji(wf)` — "맑음"→☀️ "구름많음"→⛅ "흐림"→☁️ "비"→🌧️ "눈"→🌨️ "소나기"→🌦️
- `calMonthHasWeather()` — 지금 그리는 달이 `[오늘, 오늘+10]`과 겹치나
- `loadCalendarWeather()` — 겹칠 때만 `fetch(base + "/api/weather?region=" + selCode)`. 캐시키 `selCode|base`, 서버 바뀌면 초기화. 자체 try/catch, abort 18s
- `renderCalendar()` — `await loadCalendarMonth()` → `renderCalGrid()`로 캘린더 **먼저** 렌더. 그다음 `loadCalendarWeather().then(() => renderCalGrid(calCurrentBuckets))`로 날씨 칩만 뒤에서 채움. **날씨 API가 느려도 캘린더 렌더 안 막음**(KMA API 간헐적 15s+). 재렌더 시 `calSelDate` 유지
- `renderCalGrid()` — 셀 최상단 `.cal-cell-top` flex 행(`daynum` + `.cal-wx`). `.cal-wx` = `{emoji}{tmx}°/{tmn}°`, 강수확률 ≥50%면 `☔{pop}` 덧붙임
- `renderCalDayList()` — 헤더 밑에 `.cal-daylist-wx` 한 줄(`☀️ 맑음 · 29° / 22° · 강수확률 0%`)
- CSS: `.cal-cell-top`(flex, gap 5px), `.cal-wx`, `.cal-daylist-wx`

## 검증 (2026-09-07 로컬, 실키 = 기존 data.go.kr 키)

- `/api/weather?region=11` → **11일**(09-07~09-17): 07~10일 단기, 11~17일 중기. 각 `{wf, pop, tmn, tmx}`. `region=26/50/""` 지역별 다른 값. `region=99` → 서울 폴백. 키 제거 시 `days: {}` 200
- 브라우저: 캘린더 9월 → **오늘(7일)~17일** 셀에 `7 ☀️29°/22°` 형태 칩. 지역탭 제주 클릭 → `⛅27°/24°`로 갱신. 10월 이동 → 칩 0개. 오늘 날짜 클릭 → 상세 `☀️ 맑음 · 29° / 22° · 강수확률 0%`
- **스코프 확인**: 그리드 뷰·지도·리스트에 날씨 없음
- 회귀: `/api/kopis`·`/api/holidays`·`/api/festivals` 정상. 콘솔·서버 에러 0. `python -m py_compile`·`node --check` 통과

## 배포

1. **Render Environment에 `KMA_MID_API_KEY` 추가** — 값은 `FESTIVAL_API_KEY`와 **동일**. **Decoding 형태** — Encoding(`%2B`) 넣으면 이중인코딩 사고([[03]])
2. `git push origin master:main` → Render 재배포(백엔드 변경)
3. 프로덕션 `/api/weather?region=11` 확인(11일), 캘린더에서 날씨 노출 확인
   - 키 없이 배포해도 안전(캘린더는 날씨 없이 정상)

## 운영/로컬 참고

- 단기 `getVilageFcst` 응답: `{baseDate, baseTime, category, fcstDate, fcstTime, fcstValue, nx, ny}` 다수 행. 카테고리 TMP/TMN/TMX/SKY/PTY/POP 등. 날짜별로 aggregate 필요
- 중기 `getMidLandFcst`/`getMidTa`: `response.body.items.item[0]` 단일 행. `wf4Am/Pm`~`wf10`, `taMin4`~`taMax10`
- 단기는 격자 좌표(nx,ny), 중기는 예보구역코드(regId) — 완전히 다른 체계
- `apis.data.go.kr`이 간헐적으로 connect timeout — `getMidTa`만 실패하면 기온 없는 부분결과가 캐시됨 → 15분 후 자동 재시도. KMA 호출 타임아웃 8s
- data.go.kr 4번째 키(`KASI`/`FESTIVAL`/`TOUR` 다음) — 전부 같은 값

## 범위 밖

- 시간별 예보, 강수량(mm), 미세먼지, 초단기실황(현재 날씨)
- 지도/리스트/그리드/이메일 날씨
- 날씨 기반 자동 인사이트 코멘트
