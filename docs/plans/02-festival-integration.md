# Phase 2 — 전국 축제 연동

**상태: 완료 (백엔드+UI 구현·검증·배포·프로덕션 실데이터 확인까지 전부 완료, 2026-08-05)** — 프로덕션 `/api/festivals/sync` 기준 `total:1300, unmatched_region:0` 확인됨. Render 환경변수 등록 트러블슈팅은 [03-render-env-var-incident.md](./03-render-env-var-incident.md) 참고.

## Phase 3 — UI 구현 결과

리스트 상단에 "🎭 공연 / 🎪 축제" 소스 탭을 추가(`.stabs`, 기존 `.rtabs`와 같은 시각 패턴). 축제 모드에선 장르/상태/신규만/선택발송 등 공연 전용 컨트롤을 `.ctrl-festival-disabled` 클래스로 흐리게 비활성화(숨기지 않고 회색 처리). 지역 탭은 공연/축제 양쪽 다 그대로 동작(축제도 `region` 필드가 KOPIS 코드로 매핑돼 있어 재사용 가능). 공휴일 스트립·카드 "연휴" 뱃지도 축제 카드에 동일하게 적용됨(날짜 포맷이 달라도 `normDate()`가 숫자만 추출해서 문제없음).

지도 보조마커는 지역별 축제 건수를 작은 주황 배지(숫자 포함)로 `LABEL_POS` 좌표 근처에 표시. 탭을 "공연"으로 되돌려도 마커는 유지됨(요청사항 그대로 반영) — `doFestivalSearch()`가 성공할 때만 `renderFestivalDots()`를 호출하고 `doSearch()`는 건드리지 않는 구조라서 자연스럽게 그렇게 됨. 단, 지역 필터를 걸면 마커도 그 지역 결과 기준으로 다시 그려지므로 "전국 전체" 마커를 보려면 지역은 "전체"로 둬야 함(의도된 동작 — 필터링된 결과와 지도가 항상 일치해야 하므로).

**브라우저 실측 확인(claude-in-chrome)**: 탭 전환 정상, 축제 49건 중 통영한산대첩축제·당진 댄스 페스티벌 등에 연휴 뱃지 정상 표시, 지역 탭(경기) 클릭 시 5건으로 정상 필터링, 공연 전용 컨트롤 비활성화/재활성화 정상, 지도 마커가 탭 전환 후에도 유지되는 것까지 전부 스크린샷으로 확인.

## 배경

KOPIS(`pblprfr`)는 "유료 티켓 기반 공연장 공연"만 다룬다. 벚꽃축제·불꽃축제·지역 먹거리축제처럼 무료·야외·지자체 주최 행사는 KOPIS에 아예 안 잡히는데, 지점 주변 유동인구·숙박 수요를 만드는 완전히 다른 카테고리라 새 데이터 소스로 추가했다.

## 후보 API 비교 (최종 판단)

### 채택 — 전국문화축제표준데이터 (data.go.kr 15013104)
- 소관 문화체육관광부, 지자체가 분기마다 표준 스키마로 제출
- 오픈API: `https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api` — ⚠️ **`api.data.go.kr`(s 없음)**. KASI·TourAPI가 쓰는 `apis.data.go.kr`(s 있음)과 다른 도메인이라 헷갈리기 쉬움. 잘못된 도메인은 403이 아니라 404를 반환해서 "권한 문제인가?" 하고 삽질하기 쉬움
- XML(`type=xml`) 정상 동작 확인. 응답 envelope는 KASI와 동일한 `<response><header><resultCode>00</resultCode>...</header><body><items><item>...` 구조라 `xml.etree.ElementTree` + `.//resultCode`/`.//item` 방어적 파싱 패턴 그대로 재사용
- 전체 1,300건 (2026-08-05 기준 `totalCount` 확인)
- **`numOfRows`는 최대 1000까지만 허용됨**(그 이상 요청하면 `INVALID_REQUEST_PARAMETER_ERROR`) → 페이지네이션 필수. 1,300건이면 2페이지로 끝남

### 기각(1차) — TourAPI 4.0 `searchFestival2`
관광 종합 API(15종 콘텐츠 통합)의 일부라 KOPIS와 겹칠 수 있는 노이즈가 섞이고, 보통 목록+상세 2단 호출 구조라 구현 부담이 더 큼. 전환 여지는 열어두되(아래 "확장 여지" 참고) 1차 구현 대상은 아님.

## 실제 필드명 (2026-08-05, 실키로 확인 — 문서상 한글 컬럼명과 실제 XML 태그명이 다름)

| 태그 | 의미 | 비고 |
|---|---|---|
| `fstvlNm` | 축제명 | |
| `opar` | 개최장소 | |
| `fstvlStartDate` / `fstvlEndDate` | 축제 시작/종료일 | `YYYY-MM-DD`(대시 구분) |
| `fstvlCo` | 축제내용 | |
| `mnnstNm` / `auspcInsttNm` / `suprtInsttNm` | 주관/주최/후원기관명 | |
| `phoneNumber` / `homepageUrl` / `relateInfo` | 연락처/홈페이지/관련정보 | |
| `rdnmadr` / `lnmadr` | 도로명/지번주소 | |
| `latitude` / `longitude` | 위도/경도 | |
| `referenceDate` | 데이터기준일자 | |
| **`insttCode` / `insttNm`** | 담당 지자체 행정코드/명칭 | 문서에 없던 필드. 지역 매핑에 제일 유용함(아래) |

## 지역 매핑 — 중요한 정정

이전 판단("위경도가 있어 지역코드 매핑이 필요 없다")은 **틀린 전제**였다. `index.html`의 지도는 실좌표 투영이 없는 손그림 SVG(`REAL_MAP_PATHS`, `LABEL_POS` 하드코딩)라 위경도를 화면에 직접 꽂을 방법이 없고, 결국 KOPIS의 17개 시도 코드로 매핑하는 정적 테이블이 필요하다.

다만 검증 과정에서 **`insttNm`(담당 지자체명, 예: "경상북도 영양군")** 이 주소 파싱보다 훨씬 안전한 매핑 소스라는 걸 발견했다 — 항상 "시도 시군구" 형태로 깔끔하게 오기 때문. `insttNm`을 1순위로, 실패 시 `rdnmadr`/`lnmadr`로 폴백하는 `guess_region()`을 만들었고, **실제 1,300건 전체를 돌려본 결과 매칭 실패율 0%**(전량 성공)를 확인했다. 신구 행정구역명(강원도→강원특별자치도 2023, 전라북도→전북특별자치도 2024)과 정식명칭/약칭(충청북도/충북)을 모두 매핑 테이블에 등록해뒀다.

## NEW 배지 — 이번엔 도입하지 않음

이 데이터는 분기 갱신이라 KOPIS처럼 "직전 상태와 비교해 신규 판별"을 붙이면 최초 적재 시 수백 건이 몰려 NEW로 뜨고 이후 3개월간 조용하다가 또 몰리는 어색한 경험이 된다. 게다가 Render 무료 인스턴스는 15분 무트래픽 시 슬립되는 단일 프로세스라, 신규판별을 인메모리로 하면 재시작마다 전체가 다시 NEW로 뜨는 더 나쁜 현상이 생긴다. 이를 막으려면 영속 저장소(Supabase 새 테이블)가 필요한데, 그건 정확히 예전 RLS 사고 구간이다.

→ **NEW 개념 자체를 안 쓰기로 함.** 결과적으로 이번 Phase 2는 Supabase를 전혀 건드리지 않는다 — 공휴일과 동일하게 모듈 레벨 in-memory 캐시(24시간 TTL)만 쓴다. 지점 담당자에게 실제 필요한 건 "지금 보는 기간에 무슨 축제가 있는지"이므로(Phase 1의 "선택 기간 공휴일 스트립"과 같은 성격) 이걸로 충분하다는 판단.

**나중에 NEW를 붙이고 싶어지면**(v2, 지금 구현 안 함): `HS_FESTIVALS` 테이블에 `festival_key`(이름+시작일+장소 앞부분 합성 유니크키, 안정적 ID가 없어서), `is_seed` bool(최초 적재 배치는 NEW 제외)을 두고, **코드를 연결하기 전에 Supabase SQL Editor에서 수동 insert/select로 실제 저장되는지 먼저 확인**하는 절차를 반드시 거칠 것 — `HS_KOPIS2` 사고("에러 없이 도는데 실제로는 안 쌓이고 있었다")를 반복하지 않기 위함.

## 구현 내용 (main.py, 신규 삽입만)

`get_holiday_periods()`(공휴일 엔드포인트) 다음, `build_email_body()` 이전에 삽입. `re` import 1줄 추가.

- `FESTIVAL_API_KEY`(env) / `FESTIVAL_URL`
- `FESTIVAL_REGION_MAP` + `guess_region(insttNm, address)` — insttNm 우선, 주소 폴백
- `fetch_festivals_from_std_api()` — 페이지당 1000건 페이지네이션으로 전량 수집(최대 10페이지 안전장치), 키 없거나 실패 시 빈 리스트
- `normalize_festival(item)` — 공통 셰이프 `{name, place, start_date, end_date, content, address, lat, lng, region, data_ref_date}`로 변환
- `_festival_cache` + 24시간 TTL — `get_festivals_raw()`. 실패 시 이전 캐시 유지(화면이 갑자기 비지 않게)
- `GET /api/festivals?stdate=&eddate=&signgucode=` — 캐시에서 날짜 겹침/지역 필터링
- `GET /api/festivals/sync` — 캐시 무시하고 즉시 재수집(검증/수동 새로고침용), `unmatched_region` 카운트 반환

## 검증 결과 (2026-08-05, 실키로 진행)

1. `fetch_festivals_from_std_api()` 직접 호출 → 1,300건 전량 정상 수집(페이지네이션 확인)
2. `normalize_festival()` 전체 적용 → **지역 매칭 실패 0건(0.0%)**
3. `/api/festivals/sync` → `{"status":"success","total":1300,"unmatched_region":0}`
4. `/api/festivals?stdate=20260101&eddate=20261231&signgucode=11`(서울, 2026년) → 48건, 날짜/지역 필터 모두 정상 동작 확인(겸재책거리축제, 강동선사문화축제 등 실제 데이터)
5. 기존 `/health`, `/api/kopis`, `/api/holidays` 회귀 확인 — 정상(코드상 신규 삽입뿐이라 예상대로)

## 확장 여지 → TourAPI 병합 (2026-09-03 완료, [06-tourapi-festival-source.md](./06-tourapi-festival-source.md))

여기 적어둔 대로(`fetch_festivals_from_tourapi()` + `normalize_festival()`과 같은 dict 셰이프, 추상화 없이) TourAPI `searchFestival2`를 2차 소스로 병합함. 한화 서울세계불꽃축제 같은 민간·미등록 축제 보강용. 상세는 06번 문서.

## 범위 밖 (아직 안 함)

- **이메일 본문에 축제 포함**: 별도 템플릿 설계 필요해 이후 논의로 미룸

*(백엔드+UI 배포는 커밋 `2a7b952`로 완료됨 — 위 상태 줄 참고. 이 줄은 최초 작성 시점 기준이었음)*
