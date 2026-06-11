from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET
import csv
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = FastAPI()

# CORS 설정: 클로드의 HTML 파일이 파이썬 서버에 접근할 수 있도록 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용 (실제 서비스 배포 시에는 도메인 지정)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# KOPIS API 정보
API_KEY = "1c235bf039644a5da499d3dfab103750"
KOPIS_URL = "http://www.kopis.or.kr/openApi/restful/pblprfr"

@app.get("/api/kopis")
def get_kopis_data(stdate: str, eddate: str, cpage: int = 1, rows: int = 100, signgucode: str = "", shcate: str = "", prfstate: str = ""):
    # 1. KOPIS에 보낼 파라미터 조립
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

    # 2. KOPIS API 서버로 직접 요청 (CORS 문제 없음)
    response = requests.get(KOPIS_URL, params=params)
    
    # 3. 받아온 XML 데이터를 파이썬 딕셔너리(JSON) 형태로 깔끔하게 변환
    root = ET.fromstring(response.content)
    
    data = []
    for db in root.findall('db'):
        item = {
            "mt20id": db.findtext('mt20id') or "",
            "prfnm": db.findtext('prfnm') or "",
            "fcltynm": db.findtext('fcltynm') or "",
            "genrenm": db.findtext('genrenm') or "",
            "poster": db.findtext('poster') or "",
            "prfstate": db.findtext('prfstate') or "",
            "openrun": db.findtext('openrun') or "",
            "prfpdfrom": db.findtext('prfpdfrom') or "",
            "prfpdto": db.findtext('prfpdto') or ""
        }
        data.append(item)
        
    return {"status": "success", "total_count": len(data), "data": data}


# 🌟 [수정 완료] 들여쓰기 원상복구!
def load_recipients():
    """
    구글 스프레드시트(웹에 게시된 CSV URL)에서 수신자 목록을 읽어옵니다.
    반환 형태: {"서울": ["email1@...", "email2@..."], "경기": [...], ...}
    """
    recipients = {}

    # 환경변수에서 구글 시트 CSV URL 불러오기
    sheet_url = os.environ.get("SHEET_CSV_URL", "")
    if not sheet_url:
        print("🚨 환경변수 SHEET_CSV_URL이 설정되지 않았습니다.")
        return recipients

    try:
        # 구글 시트에서 CSV 데이터 가져오기
        response = requests.get(sheet_url, timeout=10)
        response.raise_for_status()  # HTTP 오류 시 예외 발생

        # 텍스트 디코딩 후 DictReader로 파싱
        decoded = response.content.decode("utf-8")
        reader  = csv.DictReader(decoded.splitlines())

        for row in reader:
            region = row.get("지역", "").strip()
            email  = row.get("지점 이메일", "").strip()

            if not region or not email:    # 빈 줄 건너뛰기
                continue

            if region not in recipients:
                recipients[region] = []    # 지역 첫 등장 시 리스트 생성

            recipients[region].append(email)
            
    except Exception as e:
        print(f"🚨 명부 불러오기 실패: {e}")

    return recipients


def send_email(to_email: str, subject: str, body: str):
    """
    Gmail SMTP를 통해 이메일 1건을 발송합니다.
    to_email : 수신자 이메일 주소
    subject  : 이메일 제목
    body     : 이메일 본문 (현재는 텍스트, 추후 HTML로 교체 예정)
    """
    # 환경변수에서 발신자 정보 불러오기 (Render에 등록한 값)
    config        = os.environ.get("EMAIL_CONFIG", ":").split(":")
    sender_email  = config[0]   # jw.jang@thehyoosik.com
    sender_pw     = config[1]   # 앱 비밀번호

    # 이메일 구조 조립
    msg = MIMEMultipart()
    msg["From"]    = sender_email
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))  # 본문 텍스트 첨부

    # Gmail SMTP 서버에 연결 후 발송
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, sender_pw)   # 로그인
        smtp.send_message(msg)                # 발송


def build_email_body(region: str, performances: list):
    """
    지역명과 공연 리스트를 받아서 이메일 본문 텍스트를 만들어 반환합니다.
    """
    today = datetime.today().strftime("%Y-%m-%d")

    # 이메일 본문 상단 헤더
    body = f"[{today}] {region} 지역 공연 일정 안내\n"
    body += "=" * 40 + "\n\n"

    if not performances:
        body += "오늘 해당 지역의 공연 정보가 없습니다.\n"
        return body

    # 공연 목록 한 줄씩 추가
    for i, prf in enumerate(performances, start=1):
        body += f"{i}. {prf['prfnm']}\n"           # 공연명
        body += f"   장소 : {prf['fcltynm']}\n"    # 공연장
        body += f"   기간 : {prf['prfpdfrom']} ~ {prf['prfpdto']}\n"  # 기간
        body += f"   장르 : {prf['genrenm']}\n"    # 장르
        body += f"   상태 : {prf['prfstate']}\n\n" # 공연상태

    return body


@app.get("/api/send-daily-email")
def send_daily_email(regions: str = ""):
    # 🌟 함수 전체에 무적 방어막(try)을 칩니다!
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
                "service": API_KEY,
                "stdate": today,
                "eddate": today,
                "cpage": 1,
                "rows": 50,
                "signgucode": code,
                "prfstate": "02"
            }
            
            # 🌟 [방어막 2] KOPIS가 이상한 데이터를 줘도 뻗지 않게 막기
            try:
                response = requests.get(KOPIS_URL, params=params)
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
                print(f"🚨 [{region}] KOPIS 데이터 불러오기 에러: {kopis_err}")
                performances = []  # 에러나면 빈 리스트로 처리

            subject = f"[더휴식] {region} 공연 일정 안내 ({today})"
            body = build_email_body(region, performances)

            for email in email_list:
                try:
                    send_email(email, subject, body)
                    results.append({"email": email, "status": "success"})
                except Exception as mail_err:
                    print(f"🚨 메일 발송 에러: {mail_err}")
                    results.append({"email": email, "status": "fail", "error": str(mail_err)})

        return {"status": "done", "results": results}

    except Exception as total_err:
        print(f"🚨 서버 전체 치명적 에러: {total_err}")
        return {"status": "error", "detail": str(total_err)}

# main.py 맨 밑에 추가
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
