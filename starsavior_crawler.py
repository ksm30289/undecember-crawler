import os
import json
import traceback
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
import time
import random

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ===== DCInside 설정 =====

BASE_URL = "https://gall.dcinside.com/mgallery/board/lists"
GALLERY_ID = "starsavior"

# 페이지 최대 탐색 수
DEFAULT_MAX_PAGES = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

# ===== Google Sheets 설정 =====

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1w-HZ_682JDv6L0Ajlc4IYiPRlXzC46Ku-gAU0rNUSQc"
SHEET_NAME = "커뮤니티 파싱"
RANGE_NAME = f"{SHEET_NAME}!A:B"

# ===== 로그 설정 =====
# Railway / 로컬 공통으로 현재 폴더 기준 저장
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG_PATH = os.path.join(BASE_DIR, "error_log.txt")
RUN_LOG_PATH = os.path.join(BASE_DIR, "run_log.txt")
CSV_LOG_PATH = os.path.join(BASE_DIR, "starsavior_post_count_log.csv")


def log_run(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(RUN_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def log_error(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n[{ts}] {msg}\n")
        f.write(traceback.format_exc())
        f.write("\n")


def get_google_service():
    """
    Railway Variables의 GOOGLE_CREDENTIALS(JSON 문자열)로 인증 생성
    """
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_raw:
        raise RuntimeError("환경변수 GOOGLE_CREDENTIALS가 설정되지 않았습니다.")

    creds_dict = json.loads(creds_raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


# ===== 날짜 파싱 =====

def parse_dc_date(raw: str, today: date) -> date | None:
    """
    DCInside 날짜 문자열을 date 객체로 변환.
    가능한 여러 포맷을 시도해서 최대한 유연하게 처리.
    """
    raw = raw.strip()

    # 1) "YYYY.MM.DD HH:MM:SS" / "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    # 2) "YYYY.MM.DD" / "YYYY-MM-DD"
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    # 3) "MM.DD" / "MM-DD"
    for fmt in ("%m.%d", "%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return date(today.year, dt.month, dt.day)
        except ValueError:
            pass

    # 4) "HH:MM" → 오늘 날짜로 간주
    try:
        datetime.strptime(raw, "%H:%M")
        return today
    except ValueError:
        pass

    return None


# ===== DCInside 크롤링 =====

def count_posts_on_date(
    target_date: date,
    max_pages: int = DEFAULT_MAX_PAGES,
    debug: bool = False
) -> int:
    """
    스타세이비어 마이너 갤에서 target_date에 작성된 게시글 개수를 센다.
    """
    page = 1
    total_count = 0
    today = datetime.now().date()

    while page <= max_pages:
        params = {"id": GALLERY_ID, "page": page}
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=10)

        if debug:
            print(f"[DEBUG] 요청 URL = {resp.url}, status = {resp.status_code}")

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.select("tr.ub-content.us-post")

        if not rows:
            all_tr = soup.select("tbody tr")
            cand = []
            for tr in all_tr:
                if tr.select_one(".gall_date"):
                    cand.append(tr)
            rows = cand

        if not rows:
            if debug:
                print(f"[DEBUG] page {page}: 게시글 행을 찾지 못했습니다. 중단.")
            break

        if debug:
            print(f"[DEBUG] page {page}: rows={len(rows)}개")

        for idx, row in enumerate(rows):
            cls = row.get("class", [])
            if any("notice" in c for c in cls):
                continue

            date_td = row.select_one(".gall_date")
            if not date_td:
                continue

            raw_date = date_td.get("title") or date_td.get_text(strip=True)
            post_date = parse_dc_date(raw_date, today)

            if post_date is None:
                if debug:
                    print(f"[DEBUG] 날짜 파싱 실패: raw_date='{raw_date}'")
                continue

            if debug and page == 1 and idx < 5:
                print(f"[DEBUG] raw_date='{raw_date}', post_date={post_date}")

            if post_date == target_date:
                total_count += 1

        time.sleep(random.uniform(0.6, 1.2))
        page += 1

    return total_count


# ===== Google Sheets 기록 =====

def append_to_google_sheet(target_date: date, count: int):
    """
    target_date와 count를 구글 시트에 1행 추가.
    """
    service = get_google_service()
    sheet = service.spreadsheets()

    values = [[target_date.strftime("%Y-%m-%d"), count]]
    body = {"values": values}

    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


# ===== 실행부 =====

if __name__ == "__main__":
    now = datetime.now()
    target_date = (now - timedelta(days=1)).date()
    debug_mode = False

    try:
        log_run(f"크롤링 시작: target_date={target_date}")

        count = count_posts_on_date(
            target_date=target_date,
            max_pages=DEFAULT_MAX_PAGES,
            debug=debug_mode
        )

        print(f"{target_date} 날짜에 작성된 게시글 수: {count}개")

        with open(CSV_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{target_date},{count}\n")

        log_run(f"크롤링 완료: target_date={target_date}, count={count}")

        log_run("구글 시트 기록 시작")
        append_to_google_sheet(target_date, count)
        log_run("구글 시트 기록 성공")
        print("구글 시트 기록 완료")

    except Exception as e:
        print("실행 중 오류 발생:", e)
        log_error(f"실행 실패: target_date={target_date}, error={e}")
        raise
