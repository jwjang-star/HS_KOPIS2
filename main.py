from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET
import csv
import os
from datetime import datetime, timezone, timedelta

# 🌟 Pydantic 및 Typing (선택 발송용 그릇)
from pydantic import BaseModel
from typing import List, Dict

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

# Supabase 연결 설정 (Render 환경변수에 꼭 등록해 주세요!)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bnicadeeglrnymggybig.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_srOFgWBdXvCInVC6dcGDrA_tz2xPkmy")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
            insight = generate_data_insight(prf)
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