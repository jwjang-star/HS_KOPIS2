# Phase 8 — 스포츠 행사 연동 (큐레이션 + 자동 태깅)

**상태: 구현 + 로컬 브라우저 검증 완료 (2026-09-07). 프로덕션 배포 대기 (새 키 불필요).**

## 배경

캘린더/리스트에 공연·축제·공휴일·날씨가 있고, 여기에 스포츠 행사를 추가. 프로젝트 목적이 **지점 주변 숙박 수요 예측**이므로 판단 기준은 **"이 이벤트가 외지 방문·숙박을 유발하는가"** 하나.

**깨끗한 스포츠 경기일정 오픈API가 없다** (data.go.kr는 지자체별 파편 파일·지도자 등록정보뿐, KBO/KBL/K리그 공식 API 미제공). → **큐레이션 리스트 + 기존 축제 데이터 자동 태깅** 하이브리드.

## 포함 기준 (T1~T5)

| 티어 | 대상 | 2026 시드 |
|---|---|---|
| T1 전국 종합대회 | 전국체전·소년체전·장애인체전·동계체전 | 전국체전 제주 10/16~22, 장애인체전 제주 9/11~16, 소년체전 부산 5/23~26, 동계체전 강원 2/25~28 |
| T2 메이저 마라톤 | 서울·춘천·동아·JTBC·경주 등 | 서울하프 4/26, 춘천 10/25, JTBC서울 11/1(개최 유동적) |
| T3 국제·국가대표 | 세계선수권·월드컵예선·A매치·그랑프리 | (확정 후 추가) |
| T4 프로 포스트시즌·올스타 | KBO 한국시리즈·PO, K리그 승강PO, KBL·V리그 챔프전 | (시즌 말 대진 확정 후) |
| T5 e스포츠 메이저 오프라인 (**"온라인 스포츠"**) | LCK 결승, MSI·롤드컵 등 국내 개최 국제대회 | MSI 대전 DCC 6/28~7/12 |

**제외**: 프로/e스포츠 정규시즌 개별 경기(건수 폭증), 해외 개최(롤드컵 2026 뉴욕 등 — 국내 숙박 무관), 소규모 지역대회.

## 구현 — 기존 축제/캘린더 파이프라인 재사용

### `main.py`
- `SPORTS_EVENTS` — `_sport()` 헬퍼로 만든 큐레이션 리스트(축제와 동일 dict 셰이프 + `"kind": "sports"`). `SUPPLEMENTAL_FESTIVALS`(한화 불꽃축제) 패턴과 동일.
- `_SPORTS_RE` + `_infer_kind(name)` — `normalize_festival()`/`normalize_festival_tourapi()` 반환에 `"kind"` 추가. 기본 `"festival"`, 타이트한 화이트리스트(`마라톤|트라이애슬론|[eE]스포츠|이스포츠|롤드컵|LCK|MSI|월드컵\s*예선|세계\s*선수권|A매치|...`)에 걸리면 `"sports"`. 로컬 검증: 마라톤·e스포츠 11건 잡고 "빵지자랑"·"버스킹 월드컵"·"키스포츠페스티벌"은 안 잡음.
- `_merge_festivals(SPORTS_EVENTS, SUPPLEMENTAL_FESTIVALS, std, tour)` — 큐레이션 최우선(자동 태깅분과 dedup 시 큐레이션 승).
- `/api/festivals`에 `kind` 파라미터 추가(`?kind=sports`|`festival`, 생략 시 전체). `kind` 필드는 응답에 그대로 실림(기존 필드 불변).
- `/api/festivals/sync`에 `sports`/`sports_curated`/`sports_tagged` 카운트.

### `index.html`
- `.stabs`에 `🏅 스포츠` 탭. `pickSource`/`pickView`의 `isFestival` → `isPerf` 반전(축제·스포츠 둘 다 공연 전용 컨트롤 비활성).
- `doSearch()` 디스패치 `sourceMode === 'festival'` → `!== 'perf'`.
- `doFestivalSearch()` — `/api/festivals` 전량 받아 `lastFestivals`에 저장(지도 마커는 축제+스포츠 합산), 리스트는 `sourceMode`로 필터(`festival`→`kind!=='sports'`, `sports`→`kind==='sports'`). 라벨 "축제"/"스포츠" 동적.
- `createFestivalCard(item)` — `kind==='sports'`면 아이콘(`_sportsIcon`: 롤드컵/LCK/MSI/e스포츠/게임 → 🎮, else 🏅), 태그 `🏅 스포츠`, 포스터 아이콘 `ti-trophy`.
- 캘린더: `bucketByDate` 버킷 `{perfs, festivals, sports}`, `renderCalGrid` 셀에 `스 N`(초록 `.cal-badge.sport`) 배지, `renderCalDayList`에 `🏅 스포츠 N` 섹션, `loadCalendarMonth` `festCount`(kind≠sports)/`sportCount` 분리, `#cal-body` `.stats`에 4번째 카드(`이달 스포츠`, `.stats-4`).
- CSS: `.stats-4`, `.cal-badge.sport`, `.tag-sport`.

### 무수정
DB·발송 경로·`generate_data_insight()`·`/api/kopis`·`/api/holidays`·`/api/weather`·그리드 뷰·`doSearch()` 공연 경로.

## 검증 (2026-09-07 로컬, 실키)

- `/api/festivals/sync` → `{total: 1745, sports: 19, sports_curated: 8, sports_tagged: 11}`
- `?kind=sports`/`?kind=festival` 분리, `signgucode`·날짜 필터 그대로 적용
- 브라우저: 리스트 🏅 스포츠 탭(장애인체전·GES2026), 캘린더 9월 `이달 스포츠 2` + `스 1` 배지(11~16, 18~20), 10월 전국체전(16~22)·춘천마라톤(25), 제주 필터 시 스포츠 1, 날짜 상세 🏅 스포츠 섹션. 축제 탭엔 스포츠 카드 0. 그리드 뷰·콘솔 에러 없음.

## 배포

`main.py`+`index.html` → `git push origin master:main` (Render 재배포). **새 키·환경변수 불필요.**

## 유지보수 — `SPORTS_EVENTS` 손 관리

| 시점 | 할 일 |
|---|---|
| 연초 | 대한체육회 [전국종합체육대회 일정](https://meet.sports.or.kr/history/index.do)에서 그 해 T1 5~6건, 각 마라톤 조직위 발표에서 T2 날짜 |
| 국제대회·MSI/롤드컵 개최지 발표 | T3·T5 추가/갱신 (롤드컵은 국내 개최일 때만) |
| LCK 스프링(~3월)·서머(~8월) 결승 장소 발표 | T5 갱신 |
| 프로 시즌 종료 직전 (10·11월, 이듬해 봄) | T4 포스트시즌 대진 확정 → 잠정 윈도우를 정확 날짜·개최지로 |

**e스포츠 경기장 → KOPIS signgucode**: LoL Park(종로)·고척돔·잠실 = 서울 `11` / 부산 벡스코·사직 = 부산 `26` / 인스파이어 아레나(영종도) = 인천 `28` / 대전 DCC = 대전 `30` / 광주 염주체육관 = 광주 `29`.

## 범위 밖
- 프로/e스포츠 정규시즌 API 연동
- 스코어·중계·티켓·순위
- 지도에 스포츠 전용 마커 (1차는 축제 마커에 합산)
- 자동 태깅 화이트리스트 정밀 튜닝 (현재 소수 오탐/누락 허용)
