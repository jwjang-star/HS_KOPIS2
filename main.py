from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET
import csv
import os
import re
from datetime import datetime, timezone, timedelta

# 🌟 Pydantic 및 Typing (선택 발송용 그릇)
from pydantic import BaseModel
from typing import List, Dict, Optional

# 🌟 Supabase 클라이언트 라이브러리
from supabase import create_client, Client

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# KOPIS API 정보
API_KEY = "1c235bf039644a5da499d3dfab103750"
KOPIS_URL = "http://www.kopis.or.kr/openApi/restful/pblprfr"

# Supabase 연결 설정 (Render 환경변수에 꼭 등록해 주세요! — service_role 키 사용, 코드에는 하드코딩하지 않음)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bnicadeeglrnymggybig.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
try:
    supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_KEY else None
except Exception as e:
    print(f"🚨 Supabase 클라이언트 생성 실패: {e}")
    supabase = None

# 공휴일(특일) API — data.go.kr 한국천문연구원_특일 정보 (Phase 1: 연휴 가산점)
KASI_API_KEY = os.environ.get("KASI_API_KEY", "")
KASI_URL = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getHoliDeInfo"

# 선택 발송 데이터 수신용 그릇 정의
# 🔧 performances의 값에 is_new(boolean) 등 문자열이 아닌 필드가 섞여 들어와도
#    Pydantic 검증(422)에 걸리지 않도록 Dict로 완화 (build_email_body는 .get으로 안전 접근)
class SendRequest(BaseModel):
    regions: List[str]
    performances: List[Dict]


# 🔹 [보완 완료] 메인 조회 API (신규 공연 감지 + 벌크 적재 기능 탑재)
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/kopis")
def get_kopis_data(stdate: str, eddate: str, cpage: int = 1, rows: int = 100, signgucode: str = "", shcate: str = "", prfstate: str = ""):
    params = {
        "service": API_KEY,
        "stdate": stdate,
        "eddate": eddate,
        "cpage": cpage,
        "rows": rows
    }
    if signgucode: params["signgucode"] = signgucode
    if shcate: params["shcate"] = shcate
    if prfstate: params["prfstate"] = prfstate

    response = requests.get(KOPIS_URL, params=params)
    root = ET.fromstring(response.content)
    
    # 💡 [지역 매칭 보완] 해당 지역코드로 저장된 기록만 딱 집어서 가져옵니다.
    target_region = signgucode if signgucode else "전체"
    KST = timezone(timedelta(hours=9))
    today_kst = datetime.now(KST).date()

    def is_new_today(created_at_str: str) -> bool:
        try:
            dt = datetime.fromisoformat(created_at_str).astimezone(KST)
            return dt.date() == today_kst
        except Exception:
            return False

    try:
        db_res = supabase.table("HS_KOPIS2").select("mt20id, created_at").eq("region", target_region).execute()
        existing = {row["mt20id"]: row["created_at"] for row in db_res.data}
    except Exception as db_err:
        print(f"🚨 Supabase 조회 실패 (처음에는 비어있음): {db_err}")
        existing = {}

    data = []
    to_insert = [] # 🌟 [성능 최적화] 신규 공연들을 모아둘 보따리 생성

    for db in root.findall('db'):
        mt20id = db.findtext('mt20id') or ""
        prfnm = db.findtext('prfnm') or ""
        fcltynm = db.findtext('fcltynm') or ""
        genrenm = db.findtext('genrenm') or ""
        prfpdfrom = db.findtext('prfpdfrom') or ""
        prfpdto = db.findtext('prfpdto') or ""
        
        # 오늘(KST 0시 이후) 처음 발견된 공연이면 NEW 딱지!
        is_new = False
        if mt20id:
            if mt20id not in existing:
                is_new = True
                to_insert.append({
                    "mt20id": mt20id,
                    "region": target_region,
                    "prfnm": prfnm,
                    "prfpdfrom": prfpdfrom
                })
            elif is_new_today(existing[mt20id]):
                is_new = True

        item = {
            "mt20id": mt20id,
            "prfnm": prfnm,
            "fcltynm": fcltynm,
            "genrenm": genrenm,
            "poster": db.findtext('poster') or "",
            "prfstate": db.findtext('prfstate') or "",
            "openrun": db.findtext('openrun') or "",
            "prfpdfrom": prfpdfrom,
            "prfpdto": prfpdto,
            "is_new": is_new
        }
        data.append(item)
        
    # 🌟 [성능 최적화의 핵심] 모아둔 신규 데이터가 있다면 단 한 번의 요청으로 초고속 벌크 저장!
    if to_insert:
        try:
            supabase.table("HS_KOPIS2").insert(to_insert).execute()
            print(f"🚀 신규 공연 {len(to_insert)}건 Supabase 벌크 저장 완료!")
        except Exception as ins_err:
            print(f"🚨 Supabase 벌크 저장 에러: {ins_err}")
        
    return {"status": "success", "total_count": len(data), "data": data}


# 🔹 구글 명부 실시간 조회 함수
def load_recipients():
    recipients = {}
    sheet_url = os.environ.get("SHEET_CSV_URL", "")
    if not sheet_url:
        print("🚨 환경변수 SHEET_CSV_URL이 설정되지 않았습니다.")
        return recipients

    try:
        response = requests.get(sheet_url, timeout=10)
        response.raise_for_status()
        decoded = response.content.decode("utf-8")
        reader  = csv.DictReader(decoded.splitlines())

        for row in reader:
            region = row.get("지역", "").strip()
            email  = row.get("지점 이메일", "").strip()
            if not region or not email: continue
            if region not in recipients: recipients[region] = []
            recipients[region].append(email)
    except Exception as e:
        print(f"🚨 명부 불러오기 실패: {e}")
    return recipients


# 🔹 GAS 웹훅 발송 함수 (HTML 메일 지원)
def send_email(to_email: str, subject: str, body: str):
    gas_url = os.environ.get("GAS_URL", "")
    if not gas_url: return

    payload = {"to": to_email, "subject": subject, "body": body, "isHtml": True}
    try:
        response = requests.post(gas_url, json=payload, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"🚨 GAS 웹훅 발송 에러: {e}")


# 🔹 [Phase 4] Data Insight 자동 생성 함수
def generate_data_insight(prf: dict) -> dict:
    """공연장 규모 + 기간 + 공연명 키워드 기반으로 수요 예측 인사이트를 생성합니다."""
    genre = prf.get("genrenm", "")
    name  = prf.get("prfnm", "")
    venue = prf.get("fcltynm", "")
    pfrom = prf.get("prfpdfrom", "")
    pto   = prf.get("prfpdto", "")

    # 공연 기간(일수) 계산
    duration = 1
    try:
        d1 = datetime.strptime(pfrom, "%Y.%m.%d")
        d2 = datetime.strptime(pto,   "%Y.%m.%d")
        duration = (d2 - d1).days + 1
    except Exception:
        pass

    # 공연장 규모 키워드
    mega_venue_kw  = ["올림픽", "아시아드", "아레나", "인스파이어", "KSPO", "kspo",
                      "잠실", "고척", "상암", "월드컵", "체조경기장"]
    large_venue_kw = ["문화회관", "예술회관", "아트센터", "콘서트홀", "공연장", "아트홀"]
    is_mega  = any(kw in venue for kw in mega_venue_kw)
    is_large = any(kw in venue for kw in large_venue_kw)

    # 공연명 유형 키워드
    is_festival = any(kw in name for kw in ["페스티벌", "페스타", "FESTIVAL", "Festival", "축제", "뮤직페스"])
    is_awards   = any(kw in name for kw in ["AWARDS", "Awards", "어워즈", "시상식", "가요대상", "음악대상"])
    is_tour     = any(kw in name for kw in ["TOUR", "Tour", "투어", "전국투어"])
    is_memorial = any(kw in name for kw in ["주년", "기념", "Anniversary", "ANNIVERSARY"])

    # ── 대중음악: 세분화 판별 ──────────────────────────────────────────────────
    if "대중음악" in genre:

        # 1순위: 페스티벌
        if is_festival:
            return {
                "level": "&#9733; 초고수요 예상",
                "color": "#C0392B", "bg": "#FEF0EF", "border": "#E74C3C",
                "comment": "대형 페스티벌 기간 중 인근 숙박 수요 급증이 예상됩니다. "
                           "요금 30~50% 인상 및 최소 투숙일 설정을 강력히 권장합니다."
            }

        # 2순위: 시상식 (당일 집중)
        if is_awards:
            return {
                "level": "&#9733; 초단기 집중 수요",
                "color": "#C0392B", "bg": "#FEF0EF", "border": "#E74C3C",
                "comment": "시상식 특성상 공연 당일 전·후 숙박 수요가 집중됩니다. "
                           "1~2일 한정 최고가 설정 및 빠른 예약 마감을 권장합니다."
            }

        # 3순위: 초대형 공연장
        if is_mega:
            if duration >= 2:
                return {
                    "level": "&#9650; 초고수요 예상",
                    "color": "#C0392B", "bg": "#FEF0EF", "border": "#E74C3C",
                    "comment": f"대형 공연장 {duration}일 연속 공연으로 주변 숙박 만실이 우려됩니다. "
                               "전 기간 최고가 설정 및 연박 패키지 구성을 강력히 권장합니다."
                }
            return {
                "level": "&#9650; 높은 수요 예상",
                "color": "#1A5276", "bg": "#EBF5FB", "border": "#2E86C1",
                "comment": "대형 공연장 단독 공연으로 공연 전날·당일 숙박 수요 급증이 예상됩니다. "
                           "해당 기간 최고가 설정을 권장합니다."
            }

        # 4순위: 전국 투어
        if is_tour:
            return {
                "level": "&#9650; 투어 집중 수요",
                "color": "#1A5276", "bg": "#EBF5FB", "border": "#2E86C1",
                "comment": "전국 투어 공연으로 타 지역 팬덤의 이동 숙박 수요가 예상됩니다. "
                           "공연일 기준 1박 패키지 요금 최적화를 검토하세요."
            }

        # 5순위: 기념 공연
        if is_memorial:
            return {
                "level": "&#9670; 팬덤 집중 수요",
                "color": "#6C3483", "bg": "#F5EEF8", "border": "#8E44AD",
                "comment": "기념 공연 특성상 충성 팬덤의 원거리 이동 숙박 수요가 예상됩니다. "
                           "조기 예약 할인 종료 및 요금 인상을 검토하세요."
            }

        # 6순위: 중형 공연장 + 다일
        if is_large and duration >= 2:
            return {
                "level": "&#9654; 안정적 수요",
                "color": "#2C3E50", "bg": "#F2F3F4", "border": "#95A5A6",
                "comment": f"{duration}일 연속 공연으로 안정적인 숙박 수요가 기대됩니다. "
                           "현행 요금 유지 또는 소폭 인상을 검토하세요."
            }

        # 기본 (소규모 단일 공연)
        return {
            "level": "&#9654; 안정적 수요",
            "color": "#2C3E50", "bg": "#F2F3F4", "border": "#95A5A6",
            "comment": "공연 당일 주변 숙박 수요 소폭 증가가 예상됩니다. "
                       "현행 요금을 유지하되 당일 취소 정책 강화를 검토하세요."
        }

    # ── 기타 장르 ─────────────────────────────────────────────────────────────
    if "뮤지컬" in genre:
        return {
            "level": "&#9670; 주말 집중 수요",
            "color": "#6C3483", "bg": "#F5EEF8", "border": "#8E44AD",
            "comment": "뮤지컬 관람객은 주말 집중 방문 패턴을 보입니다. "
                       "주말 요금 차등 적용 및 조기 예약 할인 중단을 권장합니다."
        }
    if "서양음악" in genre or "클래식" in genre:
        return {
            "level": "&#9733; 프리미엄 수요",
            "color": "#1E4D2B", "bg": "#EAFAF1", "border": "#27AE60",
            "comment": "클래식 공연 관람객은 고급 숙박 선호도가 높습니다. "
                       "프리미엄 룸 위주의 요금 인상과 업셀링 전략을 추천합니다."
        }
    if "한국음악" in genre or "국악" in genre:
        return {
            "level": "&#9834; 문화 관광 수요",
            "color": "#784212", "bg": "#FEF9E7", "border": "#F39C12",
            "comment": "전통 공연 연계 문화 관광객의 숙박 수요 증가가 예상됩니다. "
                       "지역 문화 패키지 상품 연계를 검토하세요."
        }

    return {
        "level": "&#9650; 수요 증가 예상",
        "color": "#1A5276", "bg": "#EBF5FB", "border": "#2E86C1",
        "comment": "공연 기간 중 지점 주변 숙박 수요 증가가 예상됩니다. "
                   "해당 기간 요금 최적화를 검토하세요."
    }


# 🔹 [Phase 1] 공휴일/연휴 가산점 — data.go.kr 한국천문연구원 특일 정보 연동
# ⚠️ generate_data_insight()는 절대 수정하지 않고, 그 결과를 감싸는 방식으로만 확장합니다.
_holiday_cache: dict = {}  # {연도(int): [{"date": datetime, "name": str, "is_holiday": bool}, ...]}

def get_holidays(year: int) -> list:
    """KASI 특일 정보 API에서 연도별 공휴일 목록을 가져옵니다 (연도 단위 in-memory 캐시)."""
    if year in _holiday_cache:
        return _holiday_cache[year]
    if not KASI_API_KEY:
        return []

    params = {"ServiceKey": KASI_API_KEY, "pageNo": 1, "numOfRows": 100, "solYear": year}
    try:
        response = requests.get(KASI_URL, params=params, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        if root.findtext('.//resultCode') != '00':
            print(f"🚨 KASI 공휴일 API 응답 오류 ({year}): {root.findtext('.//resultMsg')}")
            return []  # 캐시하지 않음 — 다음 요청에서 재시도

        holidays = []
        for item in root.findall('.//item'):
            locdate = item.findtext('locdate') or ""
            try:
                d = datetime.strptime(locdate, "%Y%m%d")
            except ValueError:
                continue
            holidays.append({
                "date": d,
                "name": item.findtext('dateName') or "",
                "is_holiday": (item.findtext('isHoliday') == "Y"),
            })

        _holiday_cache[year] = holidays  # 성공했을 때만 캐시
        return holidays
    except Exception as e:
        print(f"🚨 KASI 공휴일 API 호출 실패 ({year}): {e}")
        return []  # 캐시하지 않음


def compute_holiday_periods(holidays: list, min_days: int = 2) -> list:
    """공휴일(KASI) + 주말(토/일, 직접 계산)을 연속 구간으로 묶어 '연휴' 목록을 만듭니다.
    - KASI 응답에는 실제 공휴일만 들어있고 평범한 주말은 없으므로, 주말은 이 함수가 직접 채워 넣습니다.
    - 실제 공휴일이 하나도 안 낀 순수 주말 구간은 제외합니다.
    - min_days(기본 2일) 미만인 단독 평일 공휴일도 제외합니다."""
    real_holidays = {h["date"] for h in holidays if h["is_holiday"]}
    if not real_holidays:
        return []

    d = min(real_holidays) - timedelta(days=3)
    end = max(real_holidays) + timedelta(days=3)
    off_days = set(real_holidays)
    while d <= end:
        if d.weekday() >= 5:  # 5=토, 6=일
            off_days.add(d)
        d += timedelta(days=1)

    sorted_days = sorted(off_days)
    periods, seg_start, seg_prev = [], sorted_days[0], sorted_days[0]
    for d in sorted_days[1:]:
        if (d - seg_prev).days > 1:
            periods.append((seg_start, seg_prev))
            seg_start = d
        seg_prev = d
    periods.append((seg_start, seg_prev))

    return [
        {"start": s, "end": e}
        for s, e in periods
        if (e - s).days + 1 >= min_days and any(s <= h <= e for h in real_holidays)
    ]


def enrich_insight_with_holiday(insight: dict, prf: dict) -> dict:
    """generate_data_insight()의 결과를 감싸서 연휴 가산 문구를 덧붙입니다.
    generate_data_insight()는 건드리지 않습니다."""
    try:
        d1 = datetime.strptime(prf.get("prfpdfrom", ""), "%Y.%m.%d")
        d2 = datetime.strptime(prf.get("prfpdto", ""), "%Y.%m.%d")
    except Exception:
        return insight  # 날짜 파싱 실패(오픈런 등) — 원본 그대로 반환

    holidays = []
    for y in sorted({d1.year, d2.year}):
        holidays.extend(get_holidays(y))
    periods = compute_holiday_periods(holidays)

    if any(d1 <= p["end"] and d2 >= p["start"] for p in periods):
        insight = dict(insight)
        insight["comment"] += " 🎌 공연 기간이 연휴와 겹쳐 숙박 수요가 한층 더 높을 것으로 예상됩니다."
    return insight


@app.get("/api/holidays")
def get_holiday_periods(year: int):
    """지정 연도의 연휴 구간(카드 뱃지용) + 개별 공휴일 목록(선택 기간 표시용)을 반환합니다."""
    raw = get_holidays(year)
    periods = compute_holiday_periods(raw)
    return {
        "status": "success",
        "year": year,
        "periods": [
            {"start": p["start"].strftime("%Y%m%d"), "end": p["end"].strftime("%Y%m%d")}
            for p in periods
        ],
        "holidays": [
            {"date": h["date"].strftime("%Y%m%d"), "name": h["name"]}
            for h in raw if h["is_holiday"]
        ],
    }


# 🔹 [Phase 2] 전국 축제 연동 — 전국문화축제표준데이터 (data.go.kr 15013104)
# ⚠️ 기존 로직 무수정. Supabase 새 테이블도 만들지 않음(NEW 배지를 안 쓰기로 함 —
#    분기 갱신 데이터에 KOPIS식 신규판별을 붙이면 재시작마다 전체가 NEW로 뜨는
#    문제가 생기고, 이를 막으려면 영속 저장소가 필요해져 RLS 리스크가 되돌아옴)
FESTIVAL_API_KEY = os.environ.get("FESTIVAL_API_KEY", "")
FESTIVAL_URL = "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api"  # api.data.go.kr (s 없음) 주의

# 🔹 2차 소스: 한국관광공사 TourAPI 4.0 searchFestival2
#    전국문화축제표준데이터는 지자체 등록 "문화축제"만 담아 한화 서울세계불꽃축제 같은
#    민간 주최·대형 행사가 누락됨. TourAPI(관광 진흥 DB)로 보강. 키 없으면 조용히 미사용.
#    ⚠️ apis.data.go.kr (s 있음), B551011 — 표준데이터 도메인과 다름.
TOUR_API_KEY = os.environ.get("TOUR_API_KEY", "")
TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/searchFestival2"
_TOUR_AREACODE = {  # TourAPI areaCode → KOPIS signgucode (주소 파싱 실패 시 폴백)
    "1": "11", "2": "28", "3": "30", "4": "27", "5": "29", "6": "26", "7": "31",
    "8": "36", "31": "41", "32": "51", "33": "43", "34": "44", "35": "47",
    "36": "48", "37": "45", "38": "46", "39": "50",
}

FESTIVAL_REGION_MAP = {
    "서울특별시": "11", "서울": "11", "부산광역시": "26", "부산": "26",
    "대구광역시": "27", "대구": "27", "인천광역시": "28", "인천": "28",
    "광주광역시": "29", "광주": "29", "대전광역시": "30", "대전": "30",
    "울산광역시": "31", "울산": "31",
    "세종특별자치시": "36", "세종시": "36", "세종": "36",
    "경기도": "41", "경기": "41",
    "강원특별자치도": "51", "강원도": "51", "강원": "51",
    "충청북도": "43", "충북": "43", "충청남도": "44", "충남": "44",
    "전북특별자치도": "45", "전라북도": "45", "전북": "45",
    "전라남도": "46", "전남": "46",
    "경상북도": "47", "경북": "47", "경상남도": "48", "경남": "48",
    "제주특별자치도": "50", "제주도": "50", "제주": "50",
}
_REGION_KEYS_BY_LEN = sorted(FESTIVAL_REGION_MAP, key=len, reverse=True)


def guess_region(insttNm: str, address: str) -> str:
    """insttNm(담당 지자체명, 예: '경상북도 영양군')을 1순위로, 실패 시 주소로 폴백."""
    for src in (insttNm, address):
        s = (src or "").strip()
        for key in _REGION_KEYS_BY_LEN:
            if s.startswith(key):
                return FESTIVAL_REGION_MAP[key]
    return ""


def fetch_festivals_from_std_api() -> list:
    """전국문화축제표준데이터 전량(약 1,300건)을 페이지네이션으로 가져옵니다.
    numOfRows는 API 제약상 최대 1000까지만 허용됨. 실패 시 그때까지 모은 결과를 버리고 빈 리스트 반환."""
    if not FESTIVAL_API_KEY:
        return []
    page_size = 1000
    items = []
    try:
        for page in range(1, 10):  # 안전장치: 최대 10페이지(=10,000건)까지만
            res = requests.get(FESTIVAL_URL, params={
                "serviceKey": FESTIVAL_API_KEY, "pageNo": page, "numOfRows": page_size, "type": "xml"
            }, timeout=20)
            res.raise_for_status()
            root = ET.fromstring(res.content)
            if root.findtext('.//resultCode') != '00':
                print(f"[festival] API 응답 오류: {root.findtext('.//resultMsg')}")
                return []
            rows = root.findall('.//item')
            items.extend(rows)
            total = int(root.findtext('.//totalCount') or 0)
            if len(rows) < page_size or len(items) >= total:
                break
        return items
    except Exception as e:
        print(f"[festival] fetch 실패: {e}")
        return []


def fetch_festivals_from_tourapi() -> list:
    """TourAPI 4.0 searchFestival2 — 올해(1/1 기준) 진행/예정 축제 목록(dict).
    키 없거나 실패 시 빈 리스트 → 기존 표준데이터만으로 정상 동작."""
    if not TOUR_API_KEY:
        return []
    year = datetime.now().year
    items = []
    try:
        for page in range(1, 26):  # 안전장치: 최대 25페이지(2,500건)
            res = requests.get(TOUR_API_URL, params={
                "serviceKey": TOUR_API_KEY, "MobileOS": "ETC", "MobileApp": "HSKOPIS",
                "_type": "json", "numOfRows": 100, "pageNo": page,
                "arrange": "C", "eventStartDate": f"{year}0101",
            }, timeout=20)
            try:
                body = res.json()
            except ValueError:
                print(f"[tourapi] 응답이 JSON 아님 (HTTP {res.status_code}): {res.text[:200]}")
                return []
            resp = body.get("response")
            if not resp:  # data.go.kr 에러 봉투 {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}}
                hdr = (body.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader", {})
                print(f"[tourapi] API 오류: {hdr.get('errMsg')} / {hdr.get('returnAuthMsg')}")
                return []
            hdr = resp.get("header") or {}
            if hdr.get("resultCode") not in ("0000", "00"):
                print(f"[tourapi] resultCode={hdr.get('resultCode')} msg={hdr.get('resultMsg')}")
                return []
            b = resp.get("body") or {}
            raw = b.get("items") or ""
            if not raw:  # 결과 0건이면 items가 빈 문자열
                break
            page_items = raw.get("item") or []
            if isinstance(page_items, dict):
                page_items = [page_items]
            items.extend(page_items)
            total = int(b.get("totalCount") or 0)
            if len(page_items) < 100 or len(items) >= total:
                break
        return items
    except Exception as e:
        print(f"[tourapi] fetch 실패: {e}")
        return []


def _fmt_date(s: str) -> str:
    """'20260905' → '2026-09-05' (표준데이터 포맷과 통일). 8자리 아니면 원본 유지."""
    d = re.sub(r"\D", "", s or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else (s or "")


def normalize_festival(item) -> dict:
    def g(tag): return (item.findtext(tag) or "").strip()
    address = g('rdnmadr') or g('lnmadr')
    return {
        "name": g('fstvlNm'), "place": g('opar'),
        "start_date": g('fstvlStartDate'), "end_date": g('fstvlEndDate'),
        "content": g('fstvlCo'), "address": address,
        "lat": g('latitude') or None, "lng": g('longitude') or None,
        "region": guess_region(g('insttNm'), address),
        "data_ref_date": g('referenceDate'),
    }


def normalize_festival_tourapi(item: dict) -> dict:
    """TourAPI item(dict)을 normalize_festival()과 완전히 동일한 키 셰이프로 변환."""
    def g(k): return (item.get(k) or "").strip()
    addr = g("addr1")
    return {
        "name": g("title"), "place": addr,
        "start_date": _fmt_date(g("eventstartdate")), "end_date": _fmt_date(g("eventenddate")),
        "content": "", "address": addr,
        "lat": g("mapy") or None, "lng": g("mapx") or None,  # TourAPI: mapy=위도, mapx=경도
        "region": guess_region("", addr) or _TOUR_AREACODE.get(g("areacode"), ""),
        "data_ref_date": g("modifiedtime")[:8],
    }


# 표준데이터·TourAPI 어디에도 최신 일정이 없는 대형 축제 수동 보완.
# 공식 발표 후 날짜만 갱신하면 됨. API가 해당 항목을 정상 제공하기 시작하면
# 병합 시 이 항목이 우선(dedup)되므로 중복 없이 자연스럽게 유지 → 검증 후 이 리스트에서 제거.
SUPPLEMENTAL_FESTIVALS = [
    {
        # 한화 주최(민간)라 전국문화축제표준데이터에 없음. TourAPI엔 항목(contentid 631268)이
        # 있으나 전년도 일정(2025-09-27)으로 고정돼 searchFestival2에서 누락됨.
        # 2026 일정: 한화 공식 발표(2026-08-06) — 9/4 전야제, 9/5 불꽃쇼, 여의도 한강공원.
        "name": "한화와 함께하는 서울세계불꽃축제 2026",
        "place": "여의도 한강공원 일대",
        "start_date": "2026-09-04", "end_date": "2026-09-05",
        "content": "", "address": "서울특별시 영등포구 여의동로 330",
        "lat": "37.5285", "lng": "126.9327",
        "region": "11", "data_ref_date": "20260903",
    },
]

_festival_cache: list = []
_festival_cached_at = None
_festival_stats = {"supplemental": 0, "std": 0, "tour": 0, "tour_added": 0}
_FESTIVAL_CACHE_TTL = timedelta(hours=24)


def _dedup_name(name: str) -> str:
    """'제30회 무주반딧불축제' / '2026년 무주반딧불축제' → '무주반딧불축제' 핵심만."""
    n = re.sub(r"^\s*제?\s*\d+\s*회\s*", "", name or "")
    n = re.sub(r"20\d{2}\s*년?\s*", "", n)
    return re.sub(r"[^가-힣0-9a-z]", "", n.lower())


def _merge_festivals(*sources: list):
    """앞 소스 우선. (핵심이름, 시작연월) 키가 이미 나왔으면 스킵 —
    소스 간 중복 + 소스 내 중복(표준데이터의 동일 축제 재등록 오류 포함) 모두 정리.
    반환: (병합 리스트, 소스별 실제 추가 건수)."""
    seen, merged, kept = set(), [], []
    for src in sources:
        n0 = len(merged)
        for f in src:
            key = (_dedup_name(f["name"]), _digits(f["start_date"])[:6])
            if key in seen:
                continue
            seen.add(key)
            merged.append(f)
        kept.append(len(merged) - n0)
    return merged, kept


def _rebuild_festival_cache() -> None:
    """세 소스(수동 보완 → 표준데이터 → TourAPI) fetch·정규화·병합·캐시.
    표준·TourAPI 둘 다 빈 결과일 때만 이전 캐시 유지."""
    global _festival_cache, _festival_cached_at, _festival_stats
    std = [normalize_festival(r) for r in fetch_festivals_from_std_api()]
    tour = [normalize_festival_tourapi(r) for r in fetch_festivals_from_tourapi()]
    merged, kept = _merge_festivals(SUPPLEMENTAL_FESTIVALS, std, tour)
    if std or tour:
        _festival_cache = merged
        _festival_cached_at = datetime.now()
        _festival_stats = {"supplemental": kept[0], "std": len(std), "tour": len(tour), "tour_added": kept[2]}


def get_festivals_raw() -> list:
    """정규화된 축제 목록(표준데이터 + TourAPI 병합, 24시간 in-memory 캐시)."""
    stale = _festival_cached_at is None or (datetime.now() - _festival_cached_at) > _FESTIVAL_CACHE_TTL
    if stale:
        _rebuild_festival_cache()
    return _festival_cache


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _period_overlaps(start_s, end_s, q_start, q_end) -> bool:
    s, e = _digits(start_s), _digits(end_s)
    if len(s) != 8 or len(e) != 8:
        return True
    return s <= _digits(q_end) and e >= _digits(q_start)


@app.get("/api/festivals")
def get_festival_list(stdate: str = "", eddate: str = "", signgucode: str = ""):
    items = get_festivals_raw()
    if signgucode:
        items = [it for it in items if it["region"] == signgucode]
    if stdate and eddate:
        items = [it for it in items if _period_overlaps(it["start_date"], it["end_date"], stdate, eddate)]
    return {"status": "success", "total_count": len(items), "data": items}


@app.get("/api/festivals/sync")
def force_festival_sync():
    """캐시 무시하고 즉시 재수집(검증/수동 새로고침용). 소스별 카운트 포함."""
    global _festival_cached_at
    _festival_cached_at = None
    items = get_festivals_raw()
    unmatched = sum(1 for it in items if not it["region"])
    return {
        "status": "success", "total": len(items),
        "supplemental": _festival_stats["supplemental"], "std": _festival_stats["std"],
        "tour": _festival_stats["tour"], "tour_added": _festival_stats["tour_added"],
        "unmatched_region": unmatched,
    }


# 🔹 [Phase 4] HTML 이메일 본문 생성 함수 (수익 최적화 가이드 템플릿)
def build_email_body(region: str, performances: list):
    today     = datetime.today().strftime("%Y년 %m월 %d일")
    today_sub = datetime.today().strftime("%Y-%m-%d")
    dashboard_url = "https://jwjang-star.github.io/HS_KOPIS2/"

    # 공연 카드 블록 생성
    perf_blocks = ""
    if not performances:
        perf_blocks = """
        <tr><td style="padding:24px 32px;text-align:center;color:#888;font-size:14px;">
          선택된 공연 정보가 없습니다.
        </td></tr>"""
    else:
        for i, prf in enumerate(performances):
            insight = enrich_insight_with_holiday(generate_data_insight(prf), prf)
            # 홀짝 배경 구분
            bg = "#ffffff" if i % 2 == 0 else "#FAFAFA"
            perf_blocks += f"""
        <tr><td style="padding:22px 32px;border-bottom:1px solid #EAECEE;background:{bg};">
          <div style="font-size:16px;font-weight:700;color:#1A2940;margin-bottom:12px;">
            {i+1}. {prf.get('prfnm','정보 없음')}
          </div>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
            <tr>
              <td style="font-size:11px;color:#999;width:48px;padding:3px 0;">장소</td>
              <td style="font-size:13px;color:#333;padding:3px 0;">{prf.get('fcltynm','정보 없음')}</td>
            </tr>
            <tr>
              <td style="font-size:11px;color:#999;padding:3px 0;">기간</td>
              <td style="font-size:13px;color:#333;padding:3px 0;">{prf.get('prfpdfrom','?')} ~ {prf.get('prfpdto','?')}</td>
            </tr>
            <tr>
              <td style="font-size:11px;color:#999;padding:3px 0;">장르</td>
              <td style="font-size:13px;color:#333;padding:3px 0;">{prf.get('genrenm','정보 없음')}</td>
            </tr>
            <tr>
              <td style="font-size:11px;color:#999;padding:3px 0;">상태</td>
              <td style="font-size:13px;color:#333;padding:3px 0;">{prf.get('prfstate','정보 없음')}</td>
            </tr>
          </table>
          <!-- Data Insight -->
          <div style="background:{insight['bg']};border-left:3px solid {insight['border']};border-radius:0 6px 6px 0;padding:12px 14px;">
            <div style="font-size:11px;font-weight:700;color:{insight['color']};letter-spacing:0.5px;margin-bottom:4px;">
              {insight['level']}
            </div>
            <div style="font-size:13px;color:#333;line-height:1.7;">
              {insight['comment']}
            </div>
          </div>
        </td></tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#F0F3F7;font-family:'Apple SD Gothic Neo',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F3F7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.09);">

  <!-- 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#1A2940 0%,#2E5D8E 100%);padding:30px 32px;">
    <div style="font-size:10px;color:#7FB3D3;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">
      전략기획실 · REVENUE OPTIMIZATION GUIDE
    </div>
    <div style="font-size:20px;font-weight:700;color:#ffffff;line-height:1.4;">
      {region} 성수기 가격 최적화 가이드
    </div>
    <div style="font-size:12px;color:#A8C8E0;margin-top:8px;">
      KOPIS 공연 리스트 · {today}
    </div>
  </td></tr>

  <!-- 도입부 -->
  <tr><td style="padding:24px 32px;border-bottom:1px solid #EAECEE;background:#F8FAFC;">
    <p style="margin:0;font-size:14px;color:#555;line-height:1.9;">
      <strong>KOPIS 공연 데이터를 기반으로 가격 설정 전략을 제안</strong>합니다.<br>
      지점 주변 대규모 공연/페스티벌 정보를 참고하여 <strong>객실 요금 최적화</strong>를 검토하세요.
    </p>
  </td></tr>

  <!-- 공연 데이터 섹션 (반복) -->
  {perf_blocks}

  <!-- 결론부 -->
  <tr><td style="padding:24px 32px;border-bottom:1px solid #EAECEE;">
    <p style="margin:0;font-size:12px;color:#888;line-height:1.8;text-align:center;">
      본 가이드는 <strong>전략기획실의 수요 예측 모델</strong>에 기반하여 작성되었습니다.<br>
      문의사항은 전략기획실로 연락 주시기 바랍니다.
    </p>
  </td></tr>

  <!-- 액션 버튼 -->
  <tr><td style="padding:24px 32px;text-align:center;background:#F8FAFC;">
    <a href="{dashboard_url}"
       style="display:inline-block;padding:12px 28px;background:#1A2940;color:#ffffff;
              text-decoration:none;border-radius:8px;font-size:13px;font-weight:600;
              letter-spacing:0.3px;">
      HSO X KOPIS 공연 대시보드 바로가기 →
    </a>
    <div style="margin-top:16px;font-size:10px;color:#bbb;">
      © {datetime.today().year} HSO 전략기획실 · 본 메일은 발신 전용입니다.
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return html


# 🔹 기존 자동 발송 API (백업용 유지)
@app.get("/api/send-daily-email")
def send_daily_email(regions: str = ""):
    try:
        today = datetime.today().strftime("%Y%m%d")
        recipients = load_recipients()
        region_code = {
            "서울": "11", "경기": "41", "인천": "28", "대전": "30",
            "충남": "44", "충북": "43", "경북": "47", "전북": "45",
            "부산": "26", "경남": "48", "세종": "36", "강원": "51"
        }
        results = []
        if regions:
            region_list = [r.strip() for r in regions.split(",")]
            recipients = {k: v for k, v in recipients.items() if k in region_list}

        for region, email_list in recipients.items():
            code = region_code.get(region, "")
            params = {
                "service": API_KEY, "stdate": today, "eddate": today,
                "cpage": 1, "rows": 50, "signgucode": code, "prfstate": "02"
            }
            try:
                response = requests.get(KOPIS_URL, params=params, timeout=10)
                root = ET.fromstring(response.content)
                performances = []
                for db in root.findall("db"):
                    performances.append({
                        "prfnm":     db.findtext("prfnm") or "",
                        "fcltynm":   db.findtext("fcltynm") or "",
                        "prfpdfrom": db.findtext("prfpdfrom") or "",
                        "prfpdto":   db.findtext("prfpdto") or "",
                        "genrenm":   db.findtext("genrenm") or "",
                        "prfstate":  db.findtext("prfstate") or "",
                    })
            except Exception as kopis_err:
                performances = []

            subject = f"[HSO] {region} 공연 일정 안내 ({today})"
            body = build_email_body(region, performances)

            for email in email_list:
                try:
                    send_email(email, subject, body)
                    results.append({"email": email, "status": "success"})
                except Exception as mail_err:
                    results.append({"email": email, "status": "fail", "error": str(mail_err)})
        return {"status": "done", "results": results}
    except Exception as total_err:
        return {"status": "error", "detail": str(total_err)}


# 🔹 화면 체크박스 선택 발송 신규 API (완벽 보존)
@app.post("/api/send-selected")
def send_selected_email(payload: SendRequest):
    try:
        today_str = datetime.today().strftime("%Y-%m-%d")
        recipients = load_recipients()
        results = []

        target_emails = []
        for region in payload.regions:
            if region in recipients:
                target_emails.extend(recipients[region])
        target_emails = list(set(target_emails))

        if not target_emails: return {"status": "fail", "detail": "선택한 지역에 등록된 수신 지점이 없습니다."}
        if not payload.performances: return {"status": "fail", "detail": "선택된 공연 정보가 없습니다."}

        for region in payload.regions:
            if region not in recipients: continue
            subject = f"[HSO] {region} 공연 일정 & 요금 최적화 안내"
            body = build_email_body(region, payload.performances)

            for email in recipients[region]:
                try:
                    send_email(email, subject, body)
                    results.append({"email": email, "region": region, "status": "success"})
                except Exception as mail_err:
                    results.append({"email": email, "region": region, "status": "fail", "error": str(mail_err)})
        return {"status": "done", "total_sent": len(results), "results": results}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)