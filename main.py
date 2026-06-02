from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET

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

# main.py 맨 밑에 추가
if __name__ == "__main__":
    import uvicorn
    import os
    # Render가 지정해주는 포트(PORT) 번호를 자동으로 인식하게 합니다.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
