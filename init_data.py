import requests
import xml.etree.ElementTree as ET
import csv
from datetime import datetime

# 🌟 1. 회원님의 KOPIS API 키를 넣어주세요
API_KEY = "1c235bf039644a5da499d3dfab103750"

# 🌟 2. 수집할 지역 코드 매핑 (KOPIS 기준)
REGION_CODES = {
            "서울": "11", "경기": "41", "인천": "28", "대전": "30",
            "충남": "44", "충북": "43", "경북": "47", "전북": "45",
            "부산": "26", "경남": "48", "세종": "36", "강원": "51"
}

today = datetime.today().strftime("%Y%m%d")
initial_data = []

print("🚀 KOPIS 초기 데이터 수집을 시작합니다...")

for code, region_name in REGION_CODES.items():
    print(f"👉 {region_name} 지역 데이터 가져오는 중...")
    url = "http://www.kopis.or.kr/openApi/restful/pblprfr"
    
    # API 파라미터 세팅
    params = {
        "service": API_KEY,
        "stdate": today,       # 오늘부터
        "eddate": "20261231",  # 넉넉하게 연말까지 진행되는 공연
        "cpage": 1,
        "rows": 999,           # 한 번에 최대한 많이
        "prfstate": "02",      # 02: 공연중 (예정된 공연도 원하면 '01' 추가 호출 필요)
        "signgucode": code
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        root = ET.fromstring(response.content)
        
        for db in root.findall("db"):
            prf_id = db.findtext("mt20id") or ""
            prf_name = db.findtext("prfnm") or ""
            prf_date = db.findtext("prfpdfrom") or ""
            
            # 발송일은 '초기 세팅'이므로 오늘 날짜로 일괄 기록해 둡니다.
            # (그래야 내일 이 시스템을 돌렸을 때 얘네들을 '이미 보낸 애들'로 인식합니다)
            sent_date = datetime.today().strftime("%Y-%m-%d")
            
            initial_data.append([prf_id, region_name, prf_name, prf_date, sent_date])
            
    except Exception as e:
        print(f"🚨 {region_name} 데이터 수집 실패: {e}")

# 🌟 3. 결과를 CSV 파일로 바탕화면(현재 폴더)에 저장
csv_filename = "kopis_initial_setup.csv"

# utf-8-sig로 저장해야 엑셀에서 한글이 안 깨집니다!
with open(csv_filename, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["공연ID", "지역", "공연명", "공연일", "발송일"]) # 우리가 짠 5개 뼈대
    writer.writerows(initial_data)

print(f"\n🎉 수집 완료! 총 {len(initial_data)}개의 데이터가 '{csv_filename}'에 저장되었습니다.")
