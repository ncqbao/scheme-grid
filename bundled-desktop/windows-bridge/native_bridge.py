"""Private stdin/stdout bridge for the bundled Scheme Grid Windows application.

No server, system Python, external browser, ChemScript runner, or third-party
Python package is required. The caller supplies the bundled Python interpreter.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys

# Python's embeddable distribution uses an isolated ._pth. Import this one
# adjacent, shipped module explicitly; never rely on PATH or site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import preservation

MAX_REQUEST = 40 * 1024 * 1024


def fingerprint(source: str) -> str:
    preservation.parse_cdxml(source)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def capture() -> dict:
    result = preservation.capture_active_document()
    if not isinstance(result, dict) or not result.get("ok"):
        raise ValueError("ChemDraw did not provide its active drawing.")
    result["sourceFingerprint"] = fingerprint(result.get("sourceCDXML"))
    return result


def read_request(stream) -> dict:
    raw = stream.read(MAX_REQUEST + 1)
    if not raw or len(raw) > MAX_REQUEST:
        raise ValueError("The drawing request is empty or too large.")
    try:
        request = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Scheme Grid did not provide a valid drawing request.") from exc
    if not isinstance(request, dict):
        raise ValueError("Expected a drawing request.")
    return request


def open_cleaned(request: dict, result_dir: Path) -> dict:
    source = request.get("sourceCDXML")
    result = request.get("cdxml")
    source_name = request.get("sourceName")
    expected = request.get("sourceFingerprint")
    if not isinstance(source_name, str) or not source_name:
        raise ValueError("The original drawing name is missing. Read ChemDraw again.")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, fingerprint(source)):
        raise ValueError("The original drawing snapshot is invalid. Read ChemDraw again.")
    mode = request.get("mode", "reaction")
    if mode == "reaction":
        preservation.verify_reaction_cleanup(
            source, result, selected_ids=request.get("selectedIds"),
            scope=request.get("scope"), numbering=request.get("numbering"),
        )
    elif mode == "grid":
        preservation.verify_preservation(source, result)
    else:
        raise ValueError("This drawing operation is not supported.")

    # Check a fresh full snapshot before writing copies or opening a new drawing.
    # A name alone is insufficient: two unsaved documents may share that name.
    current = capture()
    if current.get("sourceName") != source_name or not hmac.compare_digest(current["sourceFingerprint"], expected):
        raise ValueError("The active ChemDraw drawing changed. Read it again before opening the cleaned copy.")

    result_dir = Path(result_dir).resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stem = "scheme-" + stamp + "-" + secrets.token_hex(4)
    original = result_dir / (stem + "-original.cdxml")
    cleaned = result_dir / (stem + "-cleaned.cdxml")
    # Exclusive creation keeps every existing file intact, including on retry.
    with original.open("x", encoding="utf-8", newline="") as handle:
        handle.write(source)
    with cleaned.open("x", encoding="utf-8", newline="") as handle:
        handle.write(result)
    try:
        preservation.open_result_in_chemdraw(cleaned, expected_name=source_name)
    except ValueError as exc:
        raise ValueError(f"The cleaned copy was saved at {cleaned}, but ChemDraw could not open it. Open that CDXML file yourself. {exc}") from exc
    return {
        "ok": True,
        "path": str(cleaned),
        "originalPath": str(original),
        "message": "Your cleaned copy is open in ChemDraw. Your original is unchanged.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "open"))
    parser.add_argument("--result-dir", type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    try:
        if os.name != "nt":
            raise ValueError("The active ChemDraw connection is available on Windows. Open a CDXML file instead.")
        if args.operation == "capture":
            result = capture()
        else:
            if args.result_dir is None:
                raise ValueError("A private Results folder was not supplied by Scheme Grid.")
            result = open_cleaned(read_request(sys.stdin.buffer), args.result_dir)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
