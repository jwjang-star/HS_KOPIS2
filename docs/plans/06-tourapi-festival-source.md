# Phase 6 — 축제 2차 소스(TourAPI) + 수동 보완

**상태: 구현 + 프로덕션 배포·라이브 확인 완료 (2026-09-03, 커밋 `9597ddd`, `master`==`main`).**
프로덕션 `/api/festivals/sync` → `{total: 1734, supplemental: 1, std: 1305, tour: 668, tour_added: 505, unmatched_region: 1}`. 9/5 서울 필터에 한화 서울세계불꽃축제 2026 노출 확인.

## 배경

축제 데이터가 전국문화축제표준데이터(`tn_pubr_public_cltur_fstvl_api`) 한 곳뿐이라, 지자체가 표준 스키마로 등록한 "문화축제"만 잡혔다. 사용자가 **한화 서울세계불꽃축제 2026(9/4~5, 여의도)** 가 캘린더에 안 뜬다고 지적 → 확인 결과 표준데이터에 아예 없음(민간 주최라 등록 안 됨).

조사 중 확인한 것:
- TourAPI 4.0(`KorService2/searchFestival2`)에 **한화 불꽃축제 항목은 있음**(contentid 631268) — 그러나 `detailIntro2`의 행사일자가 **전년도(2025-09-27)로 고정**돼 있어, 날짜 필터 기반인 `searchFestival2`에서 누락됨. `modifiedtime`은 2026-08-25인데도 일정만 안 바뀜.
- `searchKeyword2`로는 잡히지만(날짜 필터 없음) 거기서도 날짜는 전년도.
- **결론: 어느 API로도 이 축제를 2026 일정으로 가져올 방법이 지금은 없다** → 수동 보완 필요.

한화 2026 공식 발표(2026-08-06, 다수 언론): **9/4 전야제 + 9/5 불꽃쇼**, 여의도·이촌 한강공원. 작년보다 3주 앞당김(추석·해외관광객 고려).

## 구현 (`main.py` 축제 섹션, +141줄 — 전부 격리 추가, 기존 로직 무수정)

### 1. TourAPI 2차 소스
- `TOUR_API_KEY`(env) / `TOUR_API_URL` = `http://apis.data.go.kr/B551011/KorService2/searchFestival2` (⚠️ `apis`(s), B551011 — 표준데이터 도메인과 다름)
- `_TOUR_AREACODE`: TourAPI areaCode → KOPIS signgucode 폴백 맵(주소 파싱 실패 시만)
- `fetch_festivals_from_tourapi()` — `eventStartDate={올해}0101`로 올해 진행/예정 축제, 100건씩 최대 25페이지. JSON. `resultCode` `"0000"`/`"00"` 아니면 로그+`[]`. `items`가 빈 문자열(0건)·단일 dict 모두 방어. 키 없거나 실패 시 `[]`.
- `normalize_festival_tourapi(item)` — 기존 `normalize_festival()`과 **완전히 동일한 10개 키 셰이프**. 날짜는 `_fmt_date()`로 `YYYY-MM-DD` 통일. `region`은 기존 `guess_region("", addr1)` 재사용(1순위) → areacode 폴백. `content`는 빈값(목록 호출엔 개요 없음), 이미지·전화는 안 씀.

### 2. 수동 보완 리스트
- `SUPPLEMENTAL_FESTIVALS` — 표준데이터·TourAPI 어디에도 최신 일정이 없는 대형 축제. 현재 1건: 한화 서울세계불꽃축제 2026(9/4~5, region 11, 여의도 좌표).
- 코드 주석에 "왜 수동인지"(민간 주최 + TourAPI 전년도 일정 고정) + 출처(한화 발표일) 명시.

### 3. 병합 (`_merge_festivals(*sources)` — variadic로 변경)
- 우선순위 = 인자 순서: `_merge_festivals(SUPPLEMENTAL, std, tour)`.
- 키 `(_dedup_name(name), 시작연월)`. `_dedup_name`은 "제N회 "·"YYYY년 " 접두 제거 + 한글/영숫자만.
- **소스 간 + 소스 내 중복 모두 정리**. 부수효과로 표준데이터 자체의 동일축제 재등록 오류(예: "무주반딧불축제" + "제30회 무주반딧불축제")도 병합 — 로컬 검증 시 std 1305건 중 77건이 이런 내부중복이었음.
- 반환: `(병합 리스트, 소스별 실제 추가 건수)`.
- API가 나중에 한화 축제를 정상 일정으로 주기 시작하면 → 수동 항목이 먼저라 dedup으로 TourAPI 쪽이 스킵됨(중복 안 남). 그때 `SUPPLEMENTAL_FESTIVALS`에서 제거.

### 4. `get_festivals_raw()` / `_rebuild_festival_cache()`
- 세 소스 fetch·정규화·병합 후 24h in-memory 캐시(기존 TTL·구조 유지). **std·tour 둘 다 빈 결과일 때만** 이전 캐시 유지(수동 항목만으로 덮어쓰지 않게).
- `/api/festivals` 라우트·`_period_overlaps`·`guess_region`·`normalize_festival`·`fetch_festivals_from_std_api` **무수정**.
- `/api/festivals/sync` 응답에 `supplemental`/`std`/`tour`/`tour_added` 카운트 추가(검증용).

### 프론트(`index.html`)
- **무변경.** `/api/festivals` 응답 셰이프 동일 → 캘린더·리스트가 그대로 더 많은 축제를 받음.

## 검증 결과 (2026-09-03 로컬, 실키)

`/api/festivals/sync` → `{total: 1734, supplemental: 1, std: 1305, tour: 668, tour_added: 505, unmatched_region: 1}`
- TourAPI 668건 수집, dedup 후 **505건 순증**. 지역 매칭 실패 1/668(주소에 시도 누락된 1건).
- std 내부중복 77건 정리(1305 → merged 기준 1228 유지).

브라우저(claude-in-chrome):
- 캘린더 9월 → 축제 103 → **230건**. 9/5 셀 "축 99".
- **9/5 날짜 클릭 → 🎪 축제 섹션 첫 카드 "한화와 함께하는 서울세계불꽃축제 2026 / 여의도 한강공원 일대 / 2026-09-04~05 / 🎪 서울"** ✅
- 리스트 뷰 축제 탭에도 동일하게 노출. 서울 지역 필터 정상.
- 회귀: `/api/kopis`·`/api/holidays`·`/health` 정상, 그리드 뷰·페이징·공연/축제 탭·2단 날짜 리스트 정상. 콘솔·서버 에러 0.
- 키 없이 기동 시: `sync` = `{std: 1305, tour: 0, tour_added: 0}` — 기존과 100% 동일(회귀 없음, 사전 검증).

## 배포 (2026-09-03 완료)

1. `git push origin master:main` → Render 자동 재배포. `main` `a2620af`..`9597ddd`.
2. **Render Environment `TOUR_API_KEY` 추가** — 값은 `FESTIVAL_API_KEY`와 **동일**(같은 data.go.kr 일반 인증키. "한국관광공사_국문 관광정보 서비스_GW" 활용신청 완료 → 같은 키가 KorService2에도 통함).
   - ⚠️ **1차 시도에서 Encoding 형태(`...NJ%2BopWrI...Mw%3D%3D`)를 넣어 `tour: 0` (이중인코딩 → SERVICE_KEY_IS_NOT_REGISTERED_ERROR).** `docs/plans/03`의 그 사고 재발. Decoding 형태(`%` 없이 `+`/`==`)로 교체 → 정상. 제일 확실한 건 `FESTIVAL_API_KEY` 값 그대로 복사.
3. 재배포 후 `/api/festivals/sync` → `tour: 668, tour_added: 505` 확인. 9/5 서울 필터에 한화 불꽃축제 확인.
   - `TOUR_API_KEY` 없이 배포해도 안전(수동 보완 1건 + 표준데이터는 그대로 동작). 키가 있어야 TourAPI 505건이 켜짐.

## 로컬/운영 참고

- **data.go.kr 키는 계정 공용**: 새 서비스 활용신청만 하면 기존 일반 인증키가 그 서비스에도 통함. 별도 키 아님. 이번에도 `TOUR_API_KEY` == `FESTIVAL_API_KEY` == `KASI_API_KEY`(전부 같은 값).
- TourAPI `searchFestival2` 응답 봉투: `response.header.resultCode`(`"0000"`) / `response.body.items.item[]` / `response.body.totalCount`. 에러 시엔 `{"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}}` (구조 자체가 다름).
- TourAPI `mapx`=경도, `mapy`=위도 (표준데이터 `longitude`/`latitude`와 반대 이름).
- 일부 축제 주소가 "전남광주통합특별시 …"(비표준 통합명)로 와서 `guess_region` 실패 → region "". "전체" 뷰엔 그대로 뜨고 지역 필터에서만 빠짐. 소수라 미조치.

## 범위 밖 (안 함)

- 축제 NEW 배지 (plan 02 판단 유지)
- `detailCommon2`/`detailIntro2`로 축제 개요·프로그램 채우기
- 이름 표기 차이로 남는 소수 near-중복(예: "새연교 새연쇼" 2종) 2차 정리
- `SUPPLEMENTAL_FESTIVALS` 자동 만료(현재는 수동 관리 — 매년 발표 후 날짜 갱신, API 정상화되면 제거)
