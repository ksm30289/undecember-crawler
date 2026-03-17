import os
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 설정
GALLERY_ID = 'undecember'
KEYWORDS = [
    '버그', '불가', '스킬', '패치', '오류', '에러', '문제', '속보', '장난', '꿀통',
    '중복', '복사', '암흑', '섭섭', '병신', '안돼', '안되', '보상', '드랍', '접속',
    '불법', '망함', '역대급', '드롭', '제발', '●', '최적화', '건의', '개선', '너프',
    '버프', '운영', '다크', '닼디', '언디2', '언디셈버2'
]
TARGET_DATE = (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
SPREADSHEET_ID = '1F2Smu5Z3JbQ5s693meQhHybMhB5vGRLTWKW81uGKgdY'
SHEET_SUFFIX = "(DC)"
SHEET_NAME = f"{TARGET_DATE} {SHEET_SUFFIX}"

# 인증
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
service = build('sheets', 'v4', credentials=CREDS)


def get_titles_by_date_with_keywords(target_date, keywords):
    page = 1
    collected = []
    MAX_PAGES = 1

    while page <= MAX_PAGES:
        print(f"🔄 {page}페이지 요청 중...")
        url = f'https://gall.dcinside.com/mgallery/board/lists/?id={GALLERY_ID}&page={page}'
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tr.ub-content')

        print(f"📋 게시글 {len(rows)}개 발견")

        if not rows:
            break

        for row in rows:
            title_tag = row.select_one('a[href*="/mgallery/board/view"]')
            date_tag = row.select_one('td.gall_date')

            if not title_tag or not date_tag or not date_tag.get('title'):
                continue

            title = title_tag.text.strip()
            date_str = date_tag['title'][:10]
            link = 'https://gall.dcinside.com' + title_tag['href']

            if date_str != target_date:
                continue

            # 본문 파싱
            detail_res = requests.get(link, headers={'User-Agent': 'Mozilla/5.0'})
            detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
            content_tag = detail_soup.select_one('div.write_div')

            if not content_tag:
                print(f"⚠️ 본문 없음: {link}")
                continue

            body = content_tag.get_text(separator=' ', strip=True)
            matched = [kw for kw in keywords if kw in body]
            summary = body[:100].replace('\n', ' ').strip()

            if matched:
                print(f"✅ 키워드 포함됨: {title}")
                collected.append([date_str, title, link, ', '.join(matched), summary])

            time.sleep(0.5)

        page += 1

    return collected


# 시트 없으면 생성
def ensure_sheet_exists(service, spreadsheet_id, sheet_name):
    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing_sheets = [s['properties']['title'] for s in sheet_metadata.get('sheets', [])]

    if sheet_name in existing_sheets:
        print(f"✅ 시트 '{sheet_name}' 이미 존재")
        return

    requests_body = {
        'requests': [
            {'addSheet': {'properties': {'title': sheet_name}}}
        ]
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=requests_body
    ).execute()
    print(f"📄 시트 '{sheet_name}' 생성 완료")


# 구글 시트 업로드
def upload_to_google_sheets(data, spreadsheet_id, sheet_name):
    if not data:
        print("🔍 조건에 맞는 게시글이 없습니다.")
        return

    ensure_sheet_exists(service, spreadsheet_id, sheet_name)

    sheet = service.spreadsheets()
    range_name = f"{sheet_name}!A1"
    body = {
        'values': [['날짜', '제목', '링크', '감지된 키워드', '본문 요약']] + data
    }

    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption='RAW',
        body=body
    ).execute()

    print(f"✅ Google Sheets 업로드 완료 ({len(data)}건)")


# 실행
if __name__ == "__main__":
    print("🎯 대상 날짜:", TARGET_DATE)
    posts = get_titles_by_date_with_keywords(TARGET_DATE, KEYWORDS)
    upload_to_google_sheets(posts, SPREADSHEET_ID, SHEET_NAME)
