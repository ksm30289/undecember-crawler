import os
import json
import requests
from bs4 import BeautifulSoup
from collections import Counter
import re
import time
import random
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# =========================
# 설정
# =========================

# DCInside (마이너 갤)
BASE_URL = "https://gall.dcinside.com/mgallery/board/lists"
GALLERY_ID = "starsavior"

# 몇 페이지까지 볼지
START_PAGE = 1
END_PAGE = 10  # 10~20 사이로 자유롭게 조절

# 페이지 사이 딜레이(초) - 안전 운전
SLEEP_MIN = 0.6
SLEEP_MAX = 1.2

# 제외할 단어(토큰이 정확히 일치할 때 제외)
EXCLUDED_WORDS = {
    "오늘", "지금", "이번", "관련", "정보", "갤러리", "스타", "게임",
    "공지", "공지사항", "필독", "전체", "규정", "세이비어", "그래도",
    "버전", "업데이트", "업뎃", "진짜", "그냥", "근데", "주딱", "게임은",
    "스샷", "스크린샷", "사진", "이미지", "모음", "아니", "이거", "재밌음",
    "문의", "질문", "제보", "스세", "스타세이비어", "12", "25"
}

# Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1w-HZ_682JDv6L0Ajlc4IYiPRlXzC46Ku-gAU0rNUSQc"
SHEET_NAME = "KeywordLog"
RANGE_NAME = f"{SHEET_NAME}!A:I"

# User-Agent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


# =========================
# Google 인증
# =========================

def get_google_service():
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_raw:
        raise RuntimeError("환경변수 GOOGLE_CREDENTIALS가 설정되지 않았습니다.")

    creds_dict = json.loads(creds_raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


# =========================
# 크롤링: 페이지 범위 제목 수집
# =========================

def fetch_page_titles(page: int, session: requests.Session, debug: bool = False):
    params = {"id": GALLERY_ID, "page": page}
    resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=10)

    if debug:
        print(f"[DEBUG] page={page} url={resp.url} status={resp.status_code}")

    return resp


def parse_titles_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")

    rows = soup.select("tr.ub-content.us-post")

    if not rows:
        all_tr = soup.select("tbody tr")
        rows = [tr for tr in all_tr if tr.select_one(".gall_tit a")]

    titles = []
    for row in rows:
        cls = row.get("class", [])
        if any("notice" in c for c in cls):
            continue

        a = row.select_one(".gall_tit a")
        if not a:
            continue

        titles.append(a.get_text(strip=True))

    return titles


def get_titles_from_pages(start_page: int, end_page: int, debug: bool = False):
    """
    start_page~end_page까지 제목을 모아서 반환.
    403/429 나오면 즉시 중단하고 지금까지 모은 것만 반환 + 상태코드도 같이 반환.
    """
    all_titles = []
    status = "OK"

    with requests.Session() as session:
        for page in range(start_page, end_page + 1):
            try:
                resp = fetch_page_titles(page, session, debug=debug)

                if resp.status_code in (403, 429):
                    status = f"STOP_{resp.status_code}"
                    if debug:
                        print(f"[DEBUG] 차단/레이트리밋 신호 감지: {resp.status_code} → 즉시 중단")
                    break

                resp.raise_for_status()

                titles = parse_titles_from_html(resp.text)
                all_titles.extend(titles)

                time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

            except requests.exceptions.RequestException as e:
                status = f"ERROR_{type(e).__name__}"
                if debug:
                    print(f"[DEBUG] 요청 오류로 중단: {e}")
                break

    return all_titles, status


# =========================
# 키워드 TOP3
# =========================

def extract_top_keywords(titles, top_n: int = 3):
    words = []

    for t in titles:
        cleaned = re.sub(r"[^가-힣a-zA-Z0-9 ]", " ", t)
        for w in cleaned.split():
            w = w.strip()
            if not w:
                continue
            if len(w) <= 1:
                continue
            if w in EXCLUDED_WORDS:
                continue
            words.append(w)

    counter = Counter(words)
    return counter.most_common(top_n)


# =========================
# Google Sheets 기록 (누적 append)
# =========================

def append_to_sheet(run_time: datetime, page_from: int, page_to: int, top_words, status: str):
    """
    시트에 한 행 추가:
    A 실행시각
    B 페이지범위(예: 1-20)
    C 단어1 D 카운트1
    E 단어2 F 카운트2
    G 단어3 H 카운트3
    I 상태(OK / STOP_403 / STOP_429 / ERROR_xxx)
    """
    normalized = list(top_words) + [("", 0)] * (3 - len(top_words))
    (w1, c1), (w2, c2), (w3, c3) = normalized[:3]

    service = get_google_service()
    sheet = service.spreadsheets()

    values = [[
        run_time.strftime("%Y-%m-%d %H:%M:%S"),
        f"{page_from}-{page_to}",
        w1, c1,
        w2, c2,
        w3, c3,
        status,
    ]]
    body = {"values": values}

    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


# =========================
# 실행
# =========================

if __name__ == "__main__":
    debug_mode = False

    now = datetime.now()
    titles, status = get_titles_from_pages(START_PAGE, END_PAGE, debug=debug_mode)

    top3 = extract_top_keywords(titles, top_n=3)

    print(f"페이지 {START_PAGE}~{END_PAGE} 제목 수집 개수: {len(titles)}")
    print("=== 키워드 TOP3 ===")
    for i, (w, c) in enumerate(top3, start=1):
        print(f"{i}. {w} ({c}회)")
    print("상태:", status)

    try:
        append_to_sheet(now, START_PAGE, END_PAGE, top3, status)
        print("구글 시트 기록 완료")
    except Exception as e:
        print("구글 시트 기록 실패:", e)
        raise
