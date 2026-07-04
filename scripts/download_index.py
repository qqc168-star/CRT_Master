#!/usr/bin/env python3

import json
import sys
import urllib.request
from pathlib import Path

USER_AGENT = "CRT_Master/2.0"


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def sec_to_index(sec_url):
    return sec_url.rsplit("/", 1)[0] + "/index.json"


def main():

    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_index.py "<SEC_URL>"')
        return

    sec_url = sys.argv[1]
    index_url = sec_to_index(sec_url)

    print("CRT Index Downloader v2.0")
    print()
    print("SEC URL:")
    print(sec_url)
    print()
    print("Index URL:")
    print(index_url)
    print()

    data = fetch(index_url)

    root = Path(__file__).resolve().parents[1]
    outdir = root / "raw" / "index"
    outdir.mkdir(parents=True, exist_ok=True)

    outfile = outdir / "index.json"
    outfile.write_bytes(data)

    obj = json.loads(data.decode())

    print("Download Success")
    print(outfile)
    print()
    print("Files")

    for item in obj["directory"]["item"]:
        print(item["name"])


if __name__ == "__main__":
    main()