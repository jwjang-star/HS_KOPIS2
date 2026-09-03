# HS_KOPIS2 확장 로드맵

KOPIS 공연 데이터를 지역별로 조회해서 지점 주변 숙박 수요를 예측하고, 담당자에게 "숙박 요금 최적화 가이드" 메일을 보내는 시스템(`main.py`의 `generate_data_insight()`가 핵심 인사이트 엔진). 이 문서는 공연 데이터 외에 공휴일·전국 행사 등 다른 공식 데이터로 수요 예측을 보강하는 작업의 진행 상황을 기록한다. 세션이 바뀌어도 여기서부터 이어서 진행할 수 있게 유지한다.

## 진행 상황

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | 공휴일(연휴) 연동 — 한국천문연구원 특일정보 API | ✅ 구현+검증+배포+**프로덕션 실데이터 확인 완료** (2026-08-05) |
| 2 | 전국 축제 연동(백엔드) — 전국문화축제표준데이터 | ✅ 구현+검증+배포+**프로덕션 실데이터 확인 완료** (2026-08-05) |
| 3 | UI 통합 (리스트 상단 "공연\|축제" 탭 + 지도 보조마커) | ✅ 구현+브라우저 검증+배포 완료 (2026-08-05) |
| 4 | 캘린더 대시보드 (최상위 탭으로 지도·리스트 뷰와 전환, 공연+축제+공휴일을 한 달력에) | ✅ 구현 + 날짜 리스트 2단화 + **프로덕션 배포·라이브 확인 완료** (2026-09-03) |
| 5 | Supabase 보안 강화 (RLS 잠금 + 키 로테이션, 저장소 Public 확인 대응) | ✅ 조치+검증 완료 (2026-08-26) |

## 문서 목록

- [01-holiday-integration.md](./01-holiday-integration.md) — Phase 1 상세 설계·구현·검증 기록 (완료, 프로덕션 확인됨)
- [02-festival-integration.md](./02-festival-integration.md) — Phase 2+3 상세 설계·구현·검증 기록 (완료, 프로덕션 확인됨)
- [03-render-env-var-incident.md](./03-render-env-var-incident.md) — 2026-08-05 Render 환경변수 설정 중 겪은 실제 사고와 교훈
- [04-calendar-dashboard.md](./04-calendar-dashboard.md) — Phase 4 캘린더 대시보드 설계 + 구현 + 배포 기록 (2026-09-03 라이브)
- [05-supabase-security-hardening.md](./05-supabase-security-hardening.md) — Phase 5 Supabase RLS 잠금 + 키 로테이션 조치 기록 (완료)

## 작업 원칙 (모든 Phase 공통)

- 기존 로직(`generate_data_insight()`, `/api/kopis`, 발송 경로 `send-daily-email`/`send-selected`, `load_recipients`) 절대 수정하지 않는다. 새 함수로 감싸거나 새 엔드포인트를 추가하는 "격리 추가" 방식만 쓴다.
- Render 무료 티어는 단일 프로세스 + 15분 무트래픽 시 슬립되는 휘발성 환경이다. 새로 캐싱이 필요하면 Supabase에 테이블을 새로 만들기보다(RLS 정책 설정 부담·과거 사고 이력) 모듈 레벨 in-memory dict를 우선 검토한다.
- 새 외부 API 연동은 항상 "키/설정이 없어도 기존 기능이 안 깨지는" 형태(조용히 빈 값 반환)로 만든다.
- 배포 브랜치는 `main`(GitHub) — 로컬 작업은 `master` 브랜치에서 하고 `git push origin master:main`으로 배포한다. Render(백엔드)와 GitHub Pages(프론트엔드, `index.html`)가 `main`을 보고 자동 배포되는 구조로 추정됨(둘 다 대시보드 UI로 연결돼 있어 리포지토리 내 별도 설정 파일은 없음).
