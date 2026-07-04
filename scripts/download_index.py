#!/usr/bin/env python3

import json
import urllib.request
from pathlib import Path

USER_AGENT = "CRT_Master/1.0"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526237907/index.json"


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    print("CRT Index Downloader v1.0")
    print()

    print("Downloading:")
    print(INDEX_URL)

    data = fetch(INDEX_URL)

    root = Path(__file__).resolve().parents[1]
    outdir = root / "raw" / "index"
    outdir.mkdir(parents=True, exist_ok=True)

    outfile = outdir / "index.json"
    outfile.write_bytes(data)

    obj = json.loads(data.decode())

    print()
    print("Download Success")
    print("Saved to:")
    print(outfile)
    print(f"Bytes: {len(data)}")
    print()

    print("Directory:")
    print(obj["directory"]["name"])
    print()

    print("Files:")
    for item in obj["directory"]["item"]:
        print("-", item["name"])


if __name__ == "__main__":
    main()