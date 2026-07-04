#!/usr/bin/env python3

import sys
import re
import time
import urllib.request
from pathlib import Path
from datetime import datetime


USER_AGENT = "CRT_Master/3.0 contact: qqc168@gmail.com"
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
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    last_error = None

    for attempt in range(1, RETRY + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except Exception as e:
            last_error = e
            print(f"Fetch failed attempt {attempt}/{RETRY}: {e}")
            time.sleep(2)

    raise last_error


def extract_date_from_text(text):
    pattern = r"\b(" + "|".join(MONTHS.keys()) + r")\.?\s+(\d{1,2}),\s+(20\d{2})\b"
    match = re.search(pattern, text)

    if not match:
        return "unknown_date"

    month_name = match.group(1).replace(".", "")
    day = match.group(2).zfill(2)
    year = match.group(3)

    month = MONTHS[month_name]

    return f"{year}_{month}_{day}"


def safe_stem(filename):
    stem = Path(filename).stem
    stem = stem.replace("-", "_")
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem)
    return stem.strip("_")


def build_filename(url, html):
    original_name = url.split("/")[-1]
    ext = Path(original_name).suffix or ".html"
    stem = safe_stem(original_name)

    filing_date = extract_date_from_text(html)

    return f"mstr_{filing_date}_{stem}{ext}"


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_sec.py "<SEC_URL>"')
        return

    sec_url = sys.argv[1]

    root = Path(__file__).resolve().parents[1]
    raw_dir = root / "raw" / "sec"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("CRT SEC Downloader v3.0")
    print()
    print("Downloading:")
    print(sec_url)

    data = fetch(sec_url)
    html = data.decode("utf-8", errors="ignore")

    filename = build_filename(sec_url, html)
    output_path = raw_dir / filename

    output_path.write_bytes(data)

    print()
    print("Download Success")
    print("Saved to:")
    print(output_path)
    print(f"Bytes: {len(data)}")


if __name__ == "__main__":
    main()