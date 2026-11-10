"""Download the pinned CardDemo COBOL sources this project analyses, or verify them against upstream/MANIFEST.json.

Source: github.com/aws-samples/aws-mainframe-modernization-carddemo at a fixed commit (Apache-2.0). Run
`python3 tools/fetch_data.py` to download again, `--verify` to check the checksums.
"""

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "upstream"
REPO = "aws-samples/aws-mainframe-modernization-carddemo"
COMMIT = "59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    manifest = json.loads((DATA / "MANIFEST.json").read_text())
    bad = [f["path"] for f in manifest["files"] if sha256(DATA / "carddemo" / f["path"]) != f["sha256"]]
    listed = {f["path"] for f in manifest["files"]}
    extra = [str(p.relative_to(DATA / "carddemo")) for p in (DATA / "carddemo").rglob("*") if p.is_file()]
    extra = [p for p in extra if p not in listed]
    if bad or extra:
        raise SystemExit(f"changed: {bad}; not in the manifest: {extra}")
    print(f"{len(listed)} files match upstream/MANIFEST.json")


def fetch():
    manifest = json.loads((DATA / "MANIFEST.json").read_text())
    for f in manifest["files"]:
        with urllib.request.urlopen(RAW + f["path"], timeout=60) as response:
            (DATA / "carddemo" / f["path"]).write_bytes(response.read())
        time.sleep(0.5)
    verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    (verify if parser.parse_args().verify else fetch)()
