#!/usr/bin/env python3

import sys
import urllib.request
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_sec.py "<SEC_URL>"')
        return

    sec_url = sys.argv[1]

    print("CRT SEC Downloader v1.1")
    print()
    print("Downloading:")
    print(sec_url)

    root = Path(__file__).resolve().parents[1]
    output_dir = root / "raw" / "sec"
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = sec_url.split("/")[-1]
    target = output_dir / filename

    request = urllib.request.Request(
        sec_url,
        headers={
            "User-Agent": "CRT_Master/1.0 contact: qqc168@gmail.com"
        },
    )

    with urllib.request.urlopen(request) as response:
        content = response.read()

    target.write_bytes(content)

    print()
    print("Download Success")
    print(f"Saved to: {target}")
    print(f"Bytes: {len(content)}")


if __name__ == "__main__":
    main()