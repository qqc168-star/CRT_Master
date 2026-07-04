#!/usr/bin/env python3

import sys
import re
import time
import urllib.request
from pathlib import Path


USER_AGENT = "CRT_Master/3.1 contact: qqc168@gmail.com"
TIMEOUT = 30
RETRY = 3


MONTHS = {
    "January": "01", "Jan": "01",
    "February": "02", "Feb": "02",
    "March": "03", "Mar": "03",
    "April": "04", "Apr": "04",
    "May": "05",
    "June": "06", "Jun": "06",
    "July": "07", "Jul": "07",
    "August": "08", "Aug": "08",
    "September": "09", "Sep": "09",
    "October": "10", "Oct": "10",
    "November": "11", "Nov": "11",
    "December": "12", "Dec": "12",
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None

    for attempt in range(1, RETRY + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except Exception as e:
            last_error = e
            print(f"Fetch failed {attempt}/{RETRY}: {e}")
            time.sleep(2)

    raise last_error


def extract_date(text):
    pattern = r"\b(" + "|".join(MONTHS.keys()) + r")\.?\s+(\d{1,2}),\s+(20\d{2})\b"
    m = re.search(pattern, text)
    if not m:
        return "unknown_date"

    month = MONTHS[m.group(1).replace(".", "")]
    day = m.group(2).zfill(2)
    year = m.group(3)
    return f"{year}_{month}_{day}"


def extract_company(text):
    if re.search(r"\bStrategy\b", text, re.I):
        return "strategy"
    if re.search(r"\bMicroStrategy\b", text, re.I):
        return "microstrategy"
    if re.search(r"\bApple\b", text, re.I):
        return "apple"
    return "unknown_company"


def safe_stem(filename):
    stem = Path(filename).stem
    stem = stem.replace("-", "_")
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem)
    return stem.strip("_")


def build_filename(url, html):
    original = url.split("/")[-1]
    ext = Path(original).suffix or ".html"
    stem = safe_stem(original)

    company = extract_company(html)
    date = extract_date(html)

    return f"{company}_{date}_{stem}{ext}"


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_sec.py "<SEC_URL>"')
        return

    url = sys.argv[1]

    root = Path(__file__).resolve().parents[1]
    raw_dir = root / "raw" / "sec"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("CRT SEC Downloader v3.1")
    print()
    print("Downloading:")
    print(url)

    data = fetch(url)
    html = data.decode("utf-8", errors="ignore")

    filename = build_filename(url, html)
    output = raw_dir / filename
    output.write_bytes(data)

    print()
    print("Download Success")
    print("Saved to:")
    print(output)
    print(f"Bytes: {len(data)}")


if __name__ == "__main__":
    main()