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

def load_recipients(filepath="recipients.csv"):
    """
    CSV 파일을 읽어서 지역별로 그룹핑된 딕셔너리를 반환합니다.
    반환 형태: {"서울": ["email1@...", "email2@..."], "경기": [...], ...}
    """
    recipients = {}  # 빈 딕셔너리 준비

    with open(filepath, encoding="euc-kr") as f:
        reader = csv.DictReader(f)  # 첫 줄을 헤더로 자동 인식
        for row in reader:
            region = row["지역"].strip()   # 지역 컬럼
            email  = row["지점 이메일"].strip()  # 이메일 컬럼

            if not region or not email:    # 빈 줄 건너뛰기
                continue

            if region not in recipients:
                recipients[region] = []    # 지역 첫 등장 시 리스트 생성

            recipients[region].append(email)  # 지역에 이메일 추가

    return recipients


def send_email(to_email: str, subject: str, body: str):
    """
    Gmail SMTP를 통해 이메일 1건을 발송합니다.
    to_email : 수신자 이메일 주소
    subject  : 이메일 제목
    body     : 이메일 본문 (현재는 텍스트, 추후 HTML로 교체 예정)
    """

    # 환경변수에서 발신자 정보 불러오기 (Render에 등록한 값)
    config        = os.environ.get("EMAIL_CONFIG", "").split(":")
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
    region       : 지역명 (예: "서울")
    performances : KOPIS에서 받아온 공연 딕셔너리 리스트
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
def send_daily_email():
    """
    매일 cron-job.org가 이 주소를 호출하면
    지역별로 KOPIS 데이터를 조회해서 각 지점에 이메일을 발송합니다.
    """
    today = datetime.today().strftime("%Y%m%d")  # KOPIS 날짜 형식: 20250610

    # 1. CSV에서 지역별 수신자 목록 불러오기
    recipients = load_recipients("recipients.csv")

    # KOPIS 지역코드 매핑표
    region_code = {
        "서울": "11",
        "경기": "41",
        "인천": "28",
        "대전": "30",
        "충남": "44",
        "충북": "43",
        "경북": "47",
        "전북": "45",
        "부산": "26",
        "경남": "48",
        "세종": "36",
        "강원": "42",
    }

    results = []  # 발송 결과 기록용

    # 2. 지역별로 순서대로 처리
    for region, email_list in recipients.items():

        # 3. 해당 지역의 KOPIS 공연 데이터 조회
        code = region_code.get(region, "")
        params = {
            "service": API_KEY,
            "stdate": today,
            "eddate": today,
            "cpage": 1,
            "rows": 50,
            "signgucode": code,
            "prfstate": "02"  # 공연중인 것만
        }
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

        # 4. 이메일 본문 조립
        subject = f"[더휴식] {region} 공연 일정 안내 ({today})"
        body = build_email_body(region, performances)

        # 5. 해당 지역 수신자 전체에게 발송
        for email in email_list:
            try:
                send_email(email, subject, body)
                results.append({"email": email, "status": "success"})
            except Exception as e:
                results.append({"email": email, "status": "fail", "error": str(e)})

    return {"status": "done", "results": results}

# main.py 맨 밑에 추가
if __name__ == "__main__":
    import uvicorn
    import os
    # Render가 지정해주는 포트(PORT) 번호를 자동으로 인식하게 합니다.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
