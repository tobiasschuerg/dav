#!/usr/bin/env python3
"""Schreibt die aktuellen Touren aus dav_touren.py als tours.json neben eine
Kopie von site/template.html.

Wird von .github/workflows/deploy.yml wöchentlich ausgeführt; das Ergebnis
landet in docs/ und wird von dort per GitHub Pages ausgeliefert. index.html
lädt tours.json zur Laufzeit per fetch(), damit Datenänderungen (fast täglich)
und Layoutänderungen (selten) getrennte, gut lesbare Diffs ergeben.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
from pathlib import Path

import dav_touren

TEMPLATE_PATH = Path(__file__).parent / "site" / "template.html"
MAX_DESCRIPTION_LENGTH = 220


def _trim_description(text: str) -> str:
    text = text.replace("\xa0", " ")
    if len(text) <= MAX_DESCRIPTION_LENGTH:
        return text
    cut = text[:MAX_DESCRIPTION_LENGTH].rsplit(" ", 1)[0]
    return cut + "…"


def fetch_all_tours() -> list[dav_touren.Tour]:
    tours: list[dav_touren.Tour] = []
    tours.extend(dav_touren.fetch_fn_tours())
    tours.extend(dav_touren.fetch_rv_tours())
    tours.extend(dav_touren.fetch_ue_tours())

    today = datetime.date.today().isoformat()
    tours = [t for t in tours if not t.date or t.date >= today]
    tours.sort(key=dav_touren.Tour.sort_key)
    return tours


def build_payload(tours: list[dav_touren.Tour]) -> dict:
    payload = []
    for tour in tours:
        data = dataclasses.asdict(tour)
        data["description"] = _trim_description(data["description"])
        payload.append(data)

    generated_at = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    return {"generated_at": generated_at, "tours": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="docs",
        help="Zielverzeichnis für index.html und tours.json. Standard: docs",
    )
    args = parser.parse_args(argv)

    tours = fetch_all_tours()
    payload = build_payload(tours)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tours_path = output_dir / "tours.json"
    tours_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    index_path = output_dir / "index.html"
    index_path.write_text(TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"{len(tours)} Touren -> {tours_path} (Template -> {index_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
