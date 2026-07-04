#!/usr/bin/env python3

"""
CRT SEC Downloader
Version: 0.2
"""

import sys


def main():

    if len(sys.argv) != 2:
        print("Usage:")
        print('python scripts/download_sec.py "<SEC_URL>"')
        return

    sec_url = sys.argv[1]

    print("CRT SEC Downloader v0.2")
    print()
    print("SEC URL:")
    print(sec_url)


if __name__ == "__main__":
    main()#!/usr/bin/env python3

"""
CRT SEC Downloader
Version: 0.2
"""

import sys


def main():
    print("CRT SEC Downloader v0.2")


if __name__ == "__main__":
    main()
