# Phase 4 — 캘린더 대시보드 (탭 전환형 2번째 뷰)

**상태: 구현 + 날짜 리스트 2단화 완료 + 프로덕션 배포·라이브 확인 완료 (2026-09-03).**

2026-08-07 설계 제안 → 2026-09-02 사용자 재검토 후 착수 → 2026-09-03 날짜 클릭 리스트 2단화 + 배포(`b01a67c`, `master→main`, GitHub Pages 라이브 확인). 미정이던 2건 확정: ① 장르/상태 필터 = 그리드 뷰와 공유 ② 날짜 클릭 = 정보 열람만(체크박스·선택발송 없음).

## 배경

지금의 지도+리스트 대시보드는 그대로 두고, 최상위에 탭 메뉴를 추가해 "지도·리스트 뷰"와 "캘린더 뷰"를 전환할 수 있게 하는 두 번째 대시보드 요청. 캘린더 뷰에서는 공연과 축제(행사)를 한 달력 안에 같이 볼 수 있어야 함.

## 핵심 판단 요약

| 난제 | 판단 |
|---|---|
| 탭 메뉴 위치 | `.topbar`와 `.body` 사이에 새 최상위 바 `.dtabs` 신설 (`.stabs`/`.rtabs`보다 한 단계 위 계층) |
| 달력 데이터 완전성 | `/api/kopis`는 페이지네이션(100건/페이지)이라 한 달 전체 건수를 모름. **지역 선택 강제는 안 하되(읽기전용이라 하드블록 과함), 프론트에서 최대 3페이지(300건)까지 자동 순회 + 넘으면 "더 있을 수 있음" 배너로 정직하게 고지** |
| 공연+축제 동시 표시 | 달력 셀은 소스탭 없이 항상 공연·축제를 함께 집계. 날짜 클릭 시 `createPerfCard`/`createFestivalCard` 그대로 재사용 |
| topbar 컨트롤 | 기존 `.ctrl-festival-disabled` 패턴 답습 → `.ctrl-calendar-disabled` 신설. 기간/신규만/전체선택/선택발송 비활성화, 장르/상태는 그리드 뷰와 공유 |
| 백엔드 변경 | **불필요.** `/api/kopis`·`/api/festivals`·`/api/holidays` 3개 다 무수정으로 충분 |

## 구조

```
.db
 ├─ .topbar                    (무수정, id 속성만 추가)
 ├─ .dtabs  ← 신규             "🗺️ 지도·리스트" | "📅 캘린더"
 ├─ #body-grid (= 기존 .body)  그대로 보존
 └─ #cal-body ← 신규
     ├─ .stats                 (기존 클래스 재사용) 이달 공연/축제/공휴일 요약
     ├─ .cal-toolbar           ◀ 2026년 8월 ▶ / 오늘
     ├─ .rtabs                 (기존 클래스 그대로 재사용 — 지역탭 자동 동기화됨)
     ├─ .cal-grid               요일 헤더 + 날짜 셀 7×6
     └─ .cal-daylist            클릭한 날짜의 공연/축제 카드
```

기존 `.body`는 내부를 한 줄도 안 건드리고 형제 컨테이너로 병치.

## 재사용 vs 신규

- **`.rtabs`/`.rtab` 그대로 재사용** — `syncTabs()`가 문서 전체를 `.rtab` 클래스로 스캔해서 `data-c` 기준 동기화하므로, 캘린더 안에 같은 클래스로 지역탭을 복제하면 코드 수정 없이 두 스트립이 자동 동기화됨.
- **`.stabs`/`.stab`는 재사용 안 함** — `pickSource()`가 `.stab` 클래스 전체를 스캔해 `dataset.src` 매칭하므로, 최상위 탭에 재사용하면 공연/축제 전환 시 최상위 탭까지 충돌함. 새 클래스 `.dtabs`/`.dtab`(`data-view="grid"|"calendar"`)로 분리하되 시각 스타일(진한 네이비 선택색)만 `.stab.on`에서 복사.
- **카드 렌더러 100% 재사용** — `createPerfCard`/`createFestivalCard`는 순수 함수라 어디서 호출하든 동일 동작. 단, `createPerfCard`에 선택적 2번째 인자 `{showCheckbox=true}` 추가해 캘린더에서는 체크박스 숨김(날짜 이동 시 선택이 조용히 사라지는 문제 방지 — 1차는 캘린더에서 선택발송 기능 자체를 안 만듦).
- **공휴일 로직(`loadHolidays`, `holidayList`, `holidaysBase` 캐시무효화 패턴) 그대로 재사용.**

## 데이터 로딩 전략 (가장 중요한 결정)

- 새 함수 `loadCalendarPerfPages()` — 그 달 stdate/eddate로 `/api/kopis`를 `cpage` 늘려가며 순차 호출, 페이지가 덜 차면 중단, **`CAL_MAX_PAGES=3`(300건) 도달 시 강제 중단 + 배너 고지**.
- 서버에 새 "월 병합" 엔드포인트를 만드는 대안은 기각 — Render가 단일 프로세스라 서버 안에서 루프 돌리면 다른 요청이 밀림. 프론트에서 여러 번 호출하면 지연이 그 사용자 브라우저 안에만 머무름("가능하면 프론트만으로" 기존 기조와 일치).
- `/api/festivals`는 이미 전량 반환이라 한 번만 호출, `/api/holidays`도 기존 로직 그대로. 공연 페이지루프와 축제 호출은 `Promise.all`로 병렬.
- 프론트에 `calCache = {}`(키: `연월|지역|장르|상태`)로 세션 동안 재요청 방지. 서버 주소 바뀌면 무효화(`holidaysBase`와 동일 패턴 복제).

## 캘린더 그리드 시각화

- 새 색 안 만들고 기존 토큰 재사용: 공연=파란 점(`#378ADD`), 축제=주황 점(`#E8820C`, `renderFestivalDots()`와 동일), 공휴일=옅은 배경(`#FEF5F4`), 오늘=테두리, 선택=옅은 파랑 배경(`#E6F1FB`).
- 셀 안에 개별 항목 나열 안 함(하루 20건 넘는 지역도 있음) — 집계 숫자만(99+ 캡, 지도 마커와 동일 패턴).
- 순수 CSS Grid 7×6, `buildMap()`처럼 `createElement`로 프로그래밍적 생성. 캘린더 폭은 `.body`의 380px 지도폭 제약을 안 받는 전체 폭 단일 컬럼.

## 기존 코드 터치 지점 (전부 "새 진입점 배선"이지 "동작 변경" 아님)

1. `pickRegion(el)`의 `doSearch()` 호출 → `refreshActiveView()`(신규 1줄 디스패처)로 교체
2. `#btn-go` 클릭 리스너를 활성 뷰에 따라 분기하는 디스패처로 교체
3. `createPerfCard(item)`에 선택적 2번째 인자 추가(기본값 유지, 기존 호출부 무변경)
4. 마크업에 `id` 속성 2개 추가(`#body-grid`, `#ctrl-period`) — 순수 속성 추가

`doSearch()`, `/api/kopis`, `generate_data_insight()`, 발송 경로, `load_recipients`는 전부 무수정.

## 단계 구분

| 단계 | 범위 |
|---|---|
| 1차(이번 제안 범위) | 최상위 탭, 캘린더 그리드, 페이지루프+캡, 날짜클릭 인라인 패널(체크박스 없음), topbar 컨트롤 비활성화. main.py 무수정 |
| 2차 후보(보류) | "이 날짜만" 하루 단위 선택발송, 300건 캡이 실제로 문제되면 서버사이드 병합 엔드포인트, 그리드+상세 좌우분할, 주간/아젠다 뷰 |
| 범위 밖 | PMS 예약 데이터 연동, 월간 리포트 인쇄/내보내기 |

## 열린 질문 (재개 시 확인 필요)

- 캘린더의 장르/상태 드롭다운을 그리드 뷰와 공유할지(제안, 트레이드오프: 그리드에서 좁혀둔 필터가 캘린더에도 그대로 적용됨) vs 캘린더 전용 상태를 따로 둘지
- `CAL_MAX_PAGES=3`(300건) 캡이 실사용에 충분한지는 실측 필요(01/02와 동일하게 "실키로 검증 후 확정" 절차 적용)

## 1차 구현 결과 (2026-09-02, `index.html` 단독 — `main.py` 무수정)

커밋: `index.html`에 마크업 삽입 3곳 + `<style>` 캘린더 블록 + `<script>` 캘린더 모듈(~300줄) + 기존 `doSearch()` 호출부 6곳을 `refreshActiveView()` 디스패처 경유로 배선.

**추가된 것**
- `.dtabs`/`.dtab` 최상위 탭(`pickView()`), `#body-grid`(기존 `.body`에 id만), `#cal-body`(신규 형제)
- `.view-hidden{display:none!important}` 클래스로 뷰 토글(`.body`가 grid라 인라인 display 조작 대신)
- `.ctrl-calendar-disabled` — 캘린더 뷰에서 `#ctrl-period`/`#lbl-only-new`/`#row-select-all`/`#btn-send` 흐리게(`.ctrl-festival-disabled` 미러). `#sel-genre`/`#sel-state`는 유지(그리드와 공유)
- 캘린더 모듈: `activeView` 전역, `refreshActiveView()`, `calMonthRange()`, `loadCalendarPerfPages()`(cpage 1→`CAL_MAX_PAGES=3` 순회, 100건 미만이면 중단, 상한 도달+가득이면 `truncated`), `loadCalendarFestivals()`, `bucketByDate()`(기간을 날짜별 버킷으로), `loadCalendarMonth()`(`Promise.all` 병렬 + `연월|지역|장르|상태` 세션 캐시, 서버 바뀌면 폐기), `renderCalendar()`/`renderCalToolbar()`/`renderCalGrid()`/`renderCalDayList()`
- `createPerfCard(item, opts={})` — `opts.showCheckbox===false`면 `.pcheck` 블록 생략. 기존 호출부(renderList) 무영향
- 지역탭: `#cal-body` 안에 `.rtab` 마크업 복제 → `syncTabs()`가 문서 전체 스캔이라 그리드↔캘린더 양방향 자동 동기화(수정 0)

**로컬 검증(claude-in-chrome, 실 KOPIS/축제/공휴일 데이터)**
- 월 이동·연도 롤오버(12↔1월)·[오늘] 정상
- 지역탭 클릭 시 캘린더 재집계 + 그리드탭 동기화 확인(양방향)
- 추석 24~26 음영+이름, 오늘 파란 테두리, 일요일 빨강, 날짜 선택 하이라이트+목록(체크박스 0개) 확인
- 300건 초과 시 절삭 배너 노출(서울·전체장르·전체상태 8월)
- 그리드 뷰 회귀 없음: 조회·페이징·공연/축제탭·공휴일 스트립·선택발송 버튼 정상
- `node --check` 통과, 콘솔 에러 0, 백엔드 크래시 0(로컬은 `PYTHONIOENCODING=utf-8` 필수 — memory `project-holiday-event-api` 참고)

## 날짜 클릭 리스트 2단화 (2026-09-03 완료)

기존: 공연+축제가 한 줄로 세로 스택(최대 ~90장, 스크롤 김). 변경: `renderCalDayList()`를 DOM 빌드로 재작성 — 헤더(`MM/DD · 공연 N · 축제 N`) 다음 `🎭 공연 N` 섹션 + `🎪 축제 N` 섹션, 건수 0 섹션은 생략. 각 섹션 안에서 카드는 `.cal-daylist-grid`(`repeat(auto-fill,minmax(240px,1fr))`, `align-items:start`) — 1120px에서 4열, 좁아지면 3→2→1열 자동. 카드는 기존 `.pitem`(`createPerfCard`/`createFestivalCard`) 그대로 재사용. CSS `.cal-daylist-sec`/`.cal-daylist-grid` 추가, `.cal-daylist .pitem` margin-bottom 제거(grid gap이 대체).

- 좌우 2칼럼(공연│축제)은 건수 불균형(추석 24 = 공연1:축제25) 때문에 기각 → 섹션 세로쌓기
- 공연 섹션 NEW/기존 분리 안 함(캘린더 열람 전용)
- 로컬 검증: 불균형일(09/24 공연1/축제25), 대량일(09/19 공연41/축제51 → 4열 그리드), 단일 섹션(09/01 축제만), 0건일(2027-07-01 안내 메시지), 반응형 열 수(1092→4, 760→3, 500→2, 320→1), 그리드 뷰 회귀 없음, 콘솔 에러 0

## 배포 (2026-09-03 완료)

`git push origin master:main` → `main` `c3b8a2a`..`b01a67c`. GitHub Pages 자동 반영, `https://jwjang-star.github.io/HS_KOPIS2/`에서 캘린더 탭·2단 리스트 라이브 확인. 백엔드(`main.py`) 무변경이라 Render 재배포 영향 없음. 로컬 백업 브랜치 `master`도 동일 커밋.

**운영 참고**: 캘린더 뷰가 `/api/kopis`를 월 단위 최대 3페이지 호출 → 그 달 미확인 mt20id를 Supabase에 자동 INSERT(기존 그리드 조회와 같은 경로). 캘린더를 자주 열면 해당 월 공연의 NEW 판별이 그만큼 빨리 소진됨. 문제되면 `CAL_MAX_PAGES` 축소 또는 캘린더용 read-only 조회 경로 분리 검토.

## 남은 것

- `CAL_MAX_PAGES=3`(300건) 캡 실사용 적정성 — 실측 후 조정
