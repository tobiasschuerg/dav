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
# Maximale Anzahl einzeln aufgeführter Touren je Gruppe in der Änderungs-
# zusammenfassung; der Rest wird nur gezählt, damit Commit-Messages lesbar bleiben.
MAX_SUMMARY_ITEMS = 40


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


def _read_existing(tours_path: Path) -> dict | None:
    if not tours_path.exists():
        return None
    try:
        return json.loads(tours_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _existing_generated_at(existing: dict | None) -> datetime.datetime | None:
    if existing is None:
        return None
    try:
        return datetime.datetime.strptime(existing["generated_at"], "%d.%m.%Y %H:%M")
    except (KeyError, TypeError, ValueError):
        return None


def dump_payload(payload: dict) -> str:
    """Serialisiert die Daten mit genau einer Tour pro Zeile.

    So ergibt im Git-Diff jede neue/entfernte Tour genau eine +/- Zeile und jede
    geänderte Tour genau ein Zeilenpaar, statt dass git die vielen identischen
    Zeilen eingerückter Objekte (z.B. ``"group": ""``) falsch zuordnet. Das
    Ergebnis bleibt gewöhnliches JSON.
    """
    lines = [
        "{",
        f'  "generated_at": {json.dumps(payload["generated_at"], ensure_ascii=False)},',
        '  "tours": [',
    ]
    tours = payload["tours"]
    for i, tour in enumerate(tours):
        sep = "," if i < len(tours) - 1 else ""
        lines.append(
            "    " + json.dumps(tour, ensure_ascii=False, separators=(",", ":")) + sep
        )
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def _tour_key(tour: dict) -> str:
    return tour.get("url") or f'{tour.get("section")}|{tour.get("date")}|{tour.get("title")}'


def _tour_label(tour: dict) -> str:
    section = (tour.get("section") or "").removeprefix("DAV ")
    return f'{tour.get("date") or "?":10}  {section}: {tour.get("title")}'


def _limited(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_SUMMARY_ITEMS:
        return lines
    rest = len(lines) - MAX_SUMMARY_ITEMS
    return lines[:MAX_SUMMARY_ITEMS] + [f"  … und {rest} weitere"]


def summarize_changes(old_tours: list[dict], new_tours: list[dict], today: str) -> str:
    """Kurze, menschenlesbare Zusammenfassung der Datenänderungen (für die
    Commit-Message des CI-Laufs). Touren werden über ihre URL zugeordnet."""
    old = {_tour_key(t): t for t in old_tours}
    new = {_tour_key(t): t for t in new_tours}

    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    past = [t for t in removed if t.get("date") and t["date"] < today]
    dropped = [t for t in removed if not (t.get("date") and t["date"] < today)]

    changed: list[str] = []
    for key, tour in new.items():
        before = old.get(key)
        if before is None or before == tour:
            continue
        diffs = []
        for field in tour:
            a, b = before.get(field, ""), tour.get(field, "")
            if a == b:
                continue
            if field == "description":
                diffs.append("Beschreibung geändert")
            else:
                diffs.append(f"{field}: {json.dumps(a, ensure_ascii=False)} → "
                             f"{json.dumps(b, ensure_ascii=False)}")
        changed.append(f"  ~ {_tour_label(tour)}\n      " + "; ".join(diffs))

    def section(title: str, lines: list[str]) -> str:
        return title + "\n" + "\n".join(_limited(lines))

    parts = [
        f"+{len(added)} neu, −{len(dropped)} entfernt, ~{len(changed)} geändert, "
        f"{len(past)} vergangen"
    ]
    if added:
        parts.append(section("Neu:", [
            f"  + {_tour_label(t)}" for t in sorted(added, key=_tour_label)]))
    if dropped:
        parts.append(section("Entfernt:", [
            f"  - {_tour_label(t)}" for t in sorted(dropped, key=_tour_label)]))
    if changed:
        parts.append(section("Geändert:", changed))
    return "\n\n".join(parts) + "\n"


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
    parser.add_argument(
        "--summary-file",
        help="Schreibt eine Zusammenfassung der Änderungen (neu/entfernt/geändert) "
        "gegenüber der bisherigen tours.json in diese Datei, z.B. für die "
        "Commit-Message.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tours_path = output_dir / "tours.json"
    index_path = output_dir / "index.html"
    # 404.html ist eine identische Kopie von index.html: GitHub Pages liefert sie für
    # jeden nicht existierenden Pfad aus (z.B. /friedrichshafen), sodass die per
    # history.pushState gesetzten, sektionsspezifischen URLs auch bei direktem
    # Aufruf/Reload funktionieren, statt einer echten 404-Seite.
    not_found_path = output_dir / "404.html"

    template_html = TEMPLATE_PATH.read_text(encoding="utf-8")
    index_path.write_text(template_html, encoding="utf-8")
    not_found_path.write_text(template_html, encoding="utf-8")

    existing = _read_existing(tours_path)
    last_generated = _existing_generated_at(existing)
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
