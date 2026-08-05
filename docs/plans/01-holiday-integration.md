# Phase 1 — 공휴일(연휴) API 연동

**상태: 완료 (구현 2026-08-05, 실제 키로 검증 완료, 배포 완료)**

## 배경

공연이 하나도 없어도 순수하게 "연휴"라는 이유만으로 지점 주변 숙박 수요가 오르는 경우를 기존 시스템은 전혀 잡지 못했다. 한국천문연구원(KASI) 특일정보 API가 공식·무료로 존재함을 확인하고, "공연 기간이 연휴와 겹치면 인사이트에 가산 문구를 추가"하는 기능을 추가했다.

## 사용 API

- 데이터셋: 한국천문연구원_특일 정보 (data.go.kr, publicDataPk `15012690`)
- 오퍼레이션: `getHoliDeInfo`
- 요청 URL: `https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getHoliDeInfo`
- 파라미터: `ServiceKey`(**Decoding 키** 사용 — Python `requests`의 `params=`가 자체 인코딩하므로 Encoding 키를 넣으면 이중 인코딩 에러), `pageNo`, `numOfRows`(=100이면 연간 전체 커버), `solYear`(필수), `solMonth`(생략 시 연간 전체 반환)
- 실응답 구조(2026-08-05 실키로 라이브 검증 완료): `<response><header><resultCode>00</resultCode>...</header><body><items><item><dateKind>.. </dateKind><dateName>..</dateName><isHoliday>Y</isHoliday><locdate>YYYYMMDD</locdate><seq>..</seq></item>...</items></body></response>` — `get_holidays()`의 `.//resultCode`, `.//item` 방어적 XPath 파싱이 정확히 들어맞음(수정 불필요했음).
- 확인 시점(2026-08-05) 기준 **2027년 데이터도 이미 존재**. 전국동시지방선거 같은 임시공휴일도 `isHoliday=Y`로 잡힘.

## 구현 내용

**main.py**
- `KASI_API_KEY`(env, 없으면 빈 문자열) / `KASI_URL` 상수
- `_holiday_cache: dict` — 모듈 레벨 in-memory 캐시(연도별). Supabase 새 테이블은 만들지 않음 — Render 무료 인스턴스가 단일 프로세스+슬립형 휘발성 환경이라 캐시 유실 비용이 "무료 API 재호출" 수준밖에 안 되고, 예전 Supabase RLS 사고(쓰기 경로 실패)와 달리 상태 없는 읽기 캐시라 실패 모드가 다름
- `get_holidays(year)` — KASI 호출 + 파싱, 실패 시 캐시하지 않고 빈 리스트 반환(다음 요청에서 재시도)
- `compute_holiday_periods(holidays, min_days=2)` — 공휴일(KASI) + 주말(직접 계산, KASI는 평범한 토/일을 안 줌)을 연속 구간으로 묶음. **실제 공휴일이 최소 1일 포함된 구간만** "연휴"로 인정(안 그러면 공휴일 없는 순수 주말까지 전부 잡혀서 뱃지가 무의미해짐). `min_days` 미만 단독 평일 공휴일도 제외(예: 2026년 어린이날 5/5는 화요일 단독이라 연휴 아님으로 정상 제외됨 — 검증 시 실제로 확인됨)
- `enrich_insight_with_holiday(insight, prf)` — `generate_data_insight()`의 반환 dict를 감싸서 연휴 겹침 시 `comment`에 문구만 추가. **`generate_data_insight()` 자체는 1바이트도 수정 안 함**
- `GET /api/holidays?year=` — `compute_holiday_periods()` 결과(병합된 구간)를 반환. 병합 로직을 Python 한 곳에만 둬서 프론트와 중복 구현 안 되게 함
- 기존 코드 수정은 `build_email_body()` 내부 딱 한 줄: `insight = enrich_insight_with_holiday(generate_data_insight(prf), prf)` — 이 한 줄로 `send-daily-email`/`send-selected` 두 발송 경로 모두 자동 적용됨

**index.html**
- `.tag-holiday` CSS
- `loadHolidays(years)` / `collectYears(items)` / `isHolidayOverlap(item)` 헬퍼 — `doSearch()`가 실제 반환된 공연들의 연도만 뽑아 필요한 연도만 로드
- `createPerfCard()`의 `.ptags`에 "🎌 연휴" 뱃지 조건부 추가

## 검증 결과 (2026-08-05, 실제 발급받은 키로 진행)

1. 라이브 API 호출로 XML 구조 확인 — 코드 가정과 정확히 일치, 수정 불필요
2. 로컬 `/api/holidays?year=2026` → 연휴 11개 구간 정상 반환 (설날 2/14~18 5일, 삼일절 2/28~3/2 3일 등 실제 달력과 부합)
3. `enrich_insight_with_holiday()`: 연휴 겹침 더미 공연엔 가산 문구 추가, 비겹침 더미 공연은 `generate_data_insight()` 원본과 **완전히 동일**(회귀 없음 확인)
4. `build_email_body()` 전체 렌더링 정상
5. **실제 발송 엔드포인트(`/api/send-selected` 등)는 검증 과정에서 호출하지 않음** — 로컬 환경에 `GAS_URL`/`SHEET_CSV_URL`이 우연히 설정돼 있으면 실제 지점 메일함으로 발송될 위험이 있어, `build_email_body()` 등 순수 함수만 직접 호출해 결과 문자열만 검사하는 방식으로 안전하게 검증함

## 후속 — 선택 기간 공휴일 위젯 (2026-08-05 추가)

카드 뱃지만으로는 "지금 조회 중인 기간에 공휴일이 뭐가 있는지"를 한눈에 보기 어렵다는 피드백으로, 리스트 상단(`.lhead`와 `.rtabs` 사이)에 선택한 기간(`st`~`ed`)의 공휴일을 전부 나열하는 스트립을 추가했다. 조회된 공연이 0건이어도 항상 표시됨(연휴 뱃지와 달리 검색 결과와 무관하게 날짜 범위 자체가 기준).

**main.py**: `/api/holidays` 응답에 병합된 `periods`와 별개로 개별 `holidays`(날짜+이름) 필드를 추가(순수 추가, 기존 `periods` 응답 형태 불변).

**index.html**: `holidayList`(원본 공휴일 배열) 신설, `yearsInRange(st,ed)`로 검색창 날짜 범위 자체의 연도를 계산(조회 결과가 0건이어도 정확해야 하므로 `collectYears(items)`와 별개로 필요), `renderHolidayStrip()`이 범위 내 공휴일을 칩 형태로 렌더링. `doSearch()`에서 공연 0건 조기 반환보다 **앞에서** 공휴일 로드/렌더가 실행되도록 순서 조정.

**검증 중 발견한 실제 버그 2건 (둘 다 수정 완료)**
1. `main.py`의 예외 로그 `print(f"🚨 Supabase 조회 실패...")`가 Windows 로컬 콘솔(cp949)에서 이모지 인코딩 실패로 크래시 → `/api/kopis`가 500을 반환하는 문제. Render(Linux)에서는 로케일이 달라 발생한 적 없었던 것으로 보이나, **로컬 Windows 개발 시엔 재현됨**. 이번엔 서버 실행 시 `PYTHONIOENCODING=utf-8`로 우회했을 뿐 main.py 자체는 고치지 않음 — 코드 수정이 필요하면 별도 논의 필요.
2. 프론트 `loadedHolidayYears`가 **연도만으로 캐싱**돼서, `srv-url`(서버 주소)을 바꿔도 이미 로드된 연도는 새 서버로 재요청하지 않는 버그. `holidaysBase`(마지막으로 로드한 base URL)를 추적해서 base가 바뀌면 `holidayPeriods`/`holidayList`/`loadedHolidayYears`를 전부 초기화하도록 수정. 실사용 시나리오(서버 URL을 프로덕션↔로컬로 바꿔가며 쓰는 것)에서 실제로 재현되는 버그였음.

**브라우저 검증**: 로컬 서버(uvicorn) + 별도 정적 파일 서버(index.html 서빙용)를 띄우고 claude-in-chrome으로 실제 클릭/입력 후 확인. 08/05~08/20 범위 검색 시 "🎌 선택 기간 공휴일 [08/15 광복절] [08/17 대체공휴일(광복절)]" 정상 표시, 08/21~09/05(공휴일 없는 구간)엔 "선택 기간 중 공휴일 없음" 정상 표시, 8/15 공연 카드엔 기존 "🎌 연휴" 뱃지도 함께 정상 표시됨을 스크린샷으로 확인.

## 로컬 개발 시 참고

- Windows에서 `[Environment]::SetEnvironmentVariable("KASI_API_KEY","<Decoding 키>","User")`로 영구 등록 가능하나, 이미 떠 있는 셸/프로세스에는 즉시 반영 안 됨(레지스트리 값과 프로세스 상속 환경변수가 별개). 확인은 `[Environment]::GetEnvironmentVariable("KASI_API_KEY","User")`로, 실제 실행 시엔 같은 커맨드라인에서 `$env:KASI_API_KEY = [Environment]::GetEnvironmentVariable(...)`로 재주입해야 함.
- Render 배포 시엔 이런 로컬 프로세스 상속 문제와 무관 — 대시보드 Environment 탭에 등록하면 그대로 반영됨.

## 범위 밖 (Phase 2/3로 이관)

- 전국 행사/축제 연동 → [02-festival-integration.md](./02-festival-integration.md)
- "탭 + 지도 마커" UI (Phase 2용)
- ~~"다가오는 공휴일" 상단 위젯~~ → "선택 기간 공휴일" 스트립으로 2026-08-05에 구현 완료(위 섹션 참고)
