# Supabase 보안 강화 기록 (2026-08-26)

동료에게 프로젝트 폴더를 공유해도 되는지 점검하다가 발견한 문제와 그 조치 기록. 코드 로직(`generate_data_insight()`, `/api/kopis` 등)은 전혀 건드리지 않았고, Supabase 연결 설정과 DB 정책만 손댔다.

## 발견된 문제

1. **GitHub 저장소(`jwjang-star/HS_KOPIS2`)가 이미 Public**이었음 (GitHub Pages로 프론트를 서빙하는 구조상 예견된 결과). 이 때문에 `main.py`에 하드코딩돼 있던 `SUPABASE_URL`/`SUPABASE_KEY`(publishable) 값이 이미 전세계에 노출된 상태였음.
2. Supabase `HS_KOPIS2` 테이블의 RLS 정책이 `anon` 역할에 대해 **SELECT 전체허용 + INSERT 전체허용**으로 열려 있었음. 노출된 publishable 키와 조합되면, 제3자가 서버(`main.py`)를 거치지 않고 테이블을 직접 읽거나 가짜 데이터를 밀어넣을 수 있는 상태였음.
3. (조치 중 우연히 발견, 이번 건과 무관) Supabase 무료 티어 프로젝트가 비활성 기간 후 **자동 일시정지(paused)** 상태였음 — 대시보드 진입 시 "Upgrade to Pro" 버튼이 뜨는 화면과 헷갈리기 쉬우나, 실제로는 **무료로 "Resume project" 버튼만 누르면 해결**됨(Pro 불필요).

## 조치 내용

1. Supabase 프로젝트 Resume (무료).
2. Supabase 설정에서 **Secret key**(구 service_role 키 격 — 이 프로젝트는 신형 publishable/secret 키 체계 사용 중)를 새로 확인, Render 환경변수 `SUPABASE_KEY` 값을 이 키로 교체 → 재배포.
   - service_role/secret 키는 RLS를 완전히 우회하므로, 정책이 어떻게 설정되든 서버는 항상 정상 동작함.
3. `main.py`의 `SUPABASE_KEY` 하드코딩 fallback 제거, 클라이언트 생성 실패 시에도 앱이 죽지 않고 `supabase = None`으로 안전하게 넘어가도록 처리 (커밋 `c3b8a2a`).
4. Supabase SQL Editor에서 기존 정책 삭제:
   ```sql
   drop policy "allow anon insert" on "HS_KOPIS2";
   drop policy "allow anon select" on "HS_KOPIS2";
   ```
   `anon`에 대한 정책이 하나도 남지 않아, 이제 외부 요청은 기본적으로 전부 거부됨.

## 검증 결과 (2026-08-26, 실제로 확인)

- 새 키로 `/api/kopis` 호출 → Supabase에 실제로 새 행이 오늘 날짜·올바른 지역으로 insert되는 것을 SQL로 직접 확인.
- 예전 publishable 키로 Supabase REST API(`/rest/v1/HS_KOPIS2`)를 직접 호출 → `200 OK`이지만 응답 바디는 `[]` (RLS가 조용히 전부 필터링 — 정상적인 차단 동작).
- 정책 삭제 후에도 운영 서버(`/api/kopis`, `/health`)는 계속 정상 응답 — service_role 키가 정책과 무관하게 동작하는 것 확인.

## 남은 항목 (오늘 손대지 않음)

- **KOPIS `API_KEY`는 여전히 `main.py`/`init_data.py`/`index.html` 세 곳에 하드코딩**돼 있고 이미 Public 저장소에 노출된 상태. 이번 작업 범위 밖이라 그대로 둠 — 필요 시 KOPIS 쪽에서 키 재발급 검토.
- Render의 별도 빈 Environment(`"Key: EMAIL_CONFIG..."`)에 있던 16자리 문자열은 확인 결과 비밀번호가 아니었음 (Gmail 앱 비밀번호로 추정했던 것은 오판) — 조치 불필요.

## 로컬/운영 참고

- Supabase 무료 프로젝트는 일정 기간(통상 7일) API 요청이 없으면 자동 일시정지된다. 대시보드 진입이 막힌 것처럼 보이면 먼저 프로젝트가 paused 상태인지부터 확인할 것 — Pro 업그레이드가 필요한 상황이 아닌 경우가 많다.
- 이 프로젝트는 Supabase 신형 API 키 체계(publishable/secret)를 쓴다. 대시보드에서 옛 용어인 "anon"/"service_role"으로 검색하면 안 보일 수 있음 — **Settings → API Keys**에서 "Publishable key" / "Secret keys" 섹션을 볼 것.
