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
MIN_TOURS_PER_SECTION = 5
MIN_REFRESH_INTERVAL = datetime.timedelta(hours=2)


def _trim_description(text: str) -> str:
    text = text.replace("\xa0", " ")
    if len(text) <= MAX_DESCRIPTION_LENGTH:
        return text
    cut = text[:MAX_DESCRIPTION_LENGTH].rsplit(" ", 1)[0]
    return cut + "…"


def fetch_all_tours() -> list[dav_touren.Tour]:
    tours: list[dav_touren.Tour] = []
    for label, fetch in (
        ("Friedrichshafen", dav_touren.fetch_fn_tours),
        ("Ravensburg", dav_touren.fetch_rv_tours),
        ("Überlingen", dav_touren.fetch_ue_tours),
        ("Lindau", dav_touren.fetch_li_tours),
    ):
        section_tours = fetch()
        if len(section_tours) < MIN_TOURS_PER_SECTION:
            # Ein Abruffehler (z.B. eine leere oder unerwartete Antwort) kann in den
            # section-spezifischen Parsern zu einer leeren statt einer Exception
            # führen; ohne diese Prüfung würde eine einzelne fehlgeschlagene Sektion
            # sonst unbemerkt die bestehenden guten Daten überschreiben.
            raise RuntimeError(
                f"Nur {len(section_tours)} Touren von {label} erhalten - Abbruch "
                "statt unvollständige Daten zu veröffentlichen."
            )
        tours.extend(section_tours)

    today = datetime.date.today().isoformat()
    tours = [t for t in tours if not t.date or t.date >= today]
    tours.sort(key=dav_touren.Tour.sort_key)
    return tours


def _existing_generated_at(tours_path: Path) -> datetime.datetime | None:
    if not tours_path.exists():
        return None
    try:
        data = json.loads(tours_path.read_text(encoding="utf-8"))
        return datetime.datetime.strptime(data["generated_at"], "%d.%m.%Y %H:%M")
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Touren auch dann neu abrufen, wenn die bestehenden Daten jünger als "
        f"{MIN_REFRESH_INTERVAL} sind.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tours_path = output_dir / "tours.json"
    index_path = output_dir / "index.html"

    index_path.write_text(TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    last_generated = _existing_generated_at(tours_path)
    if not args.force and last_generated is not None:
        age = datetime.datetime.now() - last_generated
        if age < MIN_REFRESH_INTERVAL:
            print(
                f"Touren sind erst {age} alt (< {MIN_REFRESH_INTERVAL}), kein "
                "erneuter Abruf. --force erzwingt einen Refresh."
            )
            return 0

    tours = fetch_all_tours()
    payload = build_payload(tours)
    tours_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"{len(tours)} Touren -> {tours_path} (Template -> {index_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
