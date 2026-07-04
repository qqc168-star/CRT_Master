#!/usr/bin/env python3

import sys
import urllib.request


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_sec.py "<SEC_URL>"')
        return

    sec_url = sys.argv[1]

    print("CRT SEC Downloader v1.0")
    print()
    print("Downloading:")
    print(sec_url)
    print()

    request = urllib.request.Request(
        sec_url,
        headers={
            "User-Agent": "CRT_Master/1.0 contact: qqc168@gmail.com"
        },
    )

    with urllib.request.urlopen(request) as response:
        content = response.read()

    print("Download Success")
    print(f"Bytes: {len(content)}")


if __name__ == "__main__":
    main()