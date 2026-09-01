#!/usr/bin/env python3
"""Listet alle aktuellen Touren der DAV-Sektionen Friedrichshafen, Ravensburg und
Überlingen auf.

Friedrichshafen (dav-fn.de) rendert seine Tourenübersicht als Vue-SPA, bettet aber
auf der Übersichtsseite ein schema.org-JSON-LD ItemList mit allen Tour-Detail-URLs
ein. Jede Detailseite enthält wiederum vollständige JSON-LD-Daten (Titel, Datum,
Beschreibung). Diese beiden serverseitig gerenderten Quellen werden hier ausgelesen.

Ravensburg (dav-ravensburg.info) nutzt die TYPO3-Extension "we_tour", deren
Kalender-Listenansicht über den AJAX-Endpunkt /we_tour.ajax abgerufen werden kann.

Überlingen (dav-ueberlingen.de) ist ein WordPress-Blog mit eigenem "touren"-Post-Type;
die /touren-Archivseite rendert Datum, Titel und Tourart serverseitig in eine paginierte
Kartenliste, die hier abgegrast wird (die REST-API liefert zwar den Post-Type, aber
kein strukturiertes Tourdatum).

Die Friedrichshafener Übersichtsseite listet die komplette Saison (inkl. bereits
vergangener Termine); per Default filtert dieses Tool auf Termine ab heute
(siehe --include-past).
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
from typing import Any, Iterable, NamedTuple, TypedDict

import requests

USER_AGENT = "Mozilla/5.0 (compatible; dav-touren-tool/1.0)"
REQUEST_TIMEOUT = 20

FN_BASE_URL = "https://www.dav-fn.de"
FN_LIST_PATH = "/programm_neu_so26/gesamt"
FN_CATEGORY_BASE_PATH = "/programm_neu_so26/bergsportarten"
FN_CATEGORIES = {
    "wandern": "Wandern",
    "bergsteigen": "Bergsteigen",
    "klettern": "Klettern",
    "skibergsteigen": "Skibergsteigen",
    "mountainbiken": "Mountainbike",
}

RV_BASE_URL = "https://www.dav-ravensburg.info"
RV_AJAX_PATH = "/we_tour.ajax"

UE_BASE_URL = "https://www.dav-ueberlingen.de"
UE_LIST_PATH = "/touren"


_GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


_CATEGORY_ALIASES = {
    "familiengruppe": "Familie",
    "wanderung": "Wandern",
    "bergwanderung": "Wandern",
}


def _normalize_category(category: str) -> str:
    """Vereinheitlicht Tourart-Bezeichnungen über alle Sektionen hinweg.

    Jede Sektion pflegt ihre Tourarten unabhängig, wodurch dieselbe Tourart
    unter verschiedenen Namen auftaucht (z.B. "Familie"/"Familiengruppe",
    "Wandern"/"Wanderung"/"Bergwanderung"). Ohne diese Normalisierung tauchen
    solche Synonyme als getrennte Einträge im Tourart-Filter der Seite auf.
    """
    if not category:
        return category
    seen: set[str] = set()
    normalized: list[str] = []
    for part in re.split(r"[/,]", category):
        part = part.strip()
        if not part:
            continue
        canonical = _CATEGORY_ALIASES.get(part.lower(), part)
        if canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    return "/".join(normalized)


@dataclasses.dataclass
class Tour:
    section: str
    title: str
    date: str
    url: str
    time: str = ""
    status: str = ""
    category: str = ""
    difficulty: str = ""
    end_date: str = ""
    registration_deadline: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        self.category = _normalize_category(self.category)

    def sort_key(self) -> tuple[str, str]:
        # Fehlende/unparsbare Daten landen am Ende statt den Sortierlauf zu crashen.
        return (self.date or "9999-99-99", self.title)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# --------------------------------------------------------------------------- #
# DAV Friedrichshafen
# --------------------------------------------------------------------------- #

def _extract_ld_json_blocks(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            blocks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    return blocks


def fetch_fn_tour_urls(session: requests.Session) -> list[str]:
    resp = session.get(FN_BASE_URL + FN_LIST_PATH, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    urls: list[str] = []
    seen: set[str] = set()
    for block in _extract_ld_json_blocks(resp.text):
        if block.get("@type") != "ItemList":
            continue
        for item in block.get("itemListElement", []):
            url = item.get("url")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


_FN_MONTHS_PATTERN = "|".join(m.capitalize() for m in _GERMAN_MONTHS)
_FN_ANMELDUNG_RE = re.compile(
    r"Anmeldung(?:\s+per\s+\w+)?(?:\s+und\s+VB)?\s*(?:bis)?\s*:?\s*"
    rf"(\d{{1,2}})\.\s*(?:(\d{{1,2}})\.|({_FN_MONTHS_PATTERN}))"
)


def _parse_fn_registration_deadline(description: str, tour_date: str) -> str:
    """Best-effort-Erkennung der Anmeldefrist aus dem Freitext der Beschreibung.

    Die Beschreibungen sind von einzelnen Tourenleiter*innen verfasst und nicht
    einheitlich formatiert ("Anmeldung bis 11.10., 18 Uhr", "Anmeldung und VB:
    15. Oktober", "Anmeldung per Mail bis 15.11."). Liefert "" statt zu raten,
    wenn kein eindeutiges Datum erkannt wird.
    """
    if not tour_date:
        return ""
    match = _FN_ANMELDUNG_RE.search(description)
    if not match:
        return ""
    day = int(match.group(1))
    if match.group(2):
        month = int(match.group(2))
    else:
        month = _GERMAN_MONTHS.get((match.group(3) or "").lower(), 0)
    if not month:
        return ""
    try:
        tour_start = datetime.date.fromisoformat(tour_date)
        deadline = datetime.date(tour_start.year, month, day)
    except ValueError:
        return ""
    if deadline > tour_start:
        try:
            deadline = deadline.replace(year=deadline.year - 1)
        except ValueError:
            return ""
    return deadline.isoformat()


_FN_VORAUSSETZUNGEN_RE = re.compile(
    r"Voraussetzungen\s*</h2>\s*<div>\s*<p><a[^>]*>([^<]*)</a>", re.S
)
_FN_SAC_PREFIX_RE = re.compile(r"^SAC\s+\d+\s+\S+\s+(\S.*)$")


def _shorten_fn_difficulty(text: str) -> str:
    """Kürzt "SAC 23 Wanderung T4-" auf die reine Gradangabe "T4-".

    Die Voraussetzungen-Seite präfixt die Gradangabe mit der SAC-Kursnummer und
    der Tourart (z.B. "SAC 12 Klettern UIAA-V-"); nur der Grad selbst ist
    hier von Interesse.
    """
    match = _FN_SAC_PREFIX_RE.match(text)
    return match.group(1) if match else text


def _parse_fn_difficulty(html: str) -> str:
    """Liest die Schwierigkeitsangabe (z.B. "T2", "SAC 23 Wanderung T4-") aus dem
    "Voraussetzungen"-Abschnitt der Detailseite; nicht jede Tour hat eine.
    """
    match = _FN_VORAUSSETZUNGEN_RE.search(html)
    if not match:
        return ""
    return _shorten_fn_difficulty(unescape(match.group(1)).strip())


def fetch_fn_tour_detail(session: requests.Session, path: str, category: str = "") -> Tour | None:
    url = FN_BASE_URL + path
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        return None
    for block in _extract_ld_json_blocks(resp.text):
        if block.get("@type") in ("Course", "Event"):
            date = (block.get("startDate") or "").split(" ")[0]
            end_date = (block.get("endDate") or "").split(" ")[0]
            if end_date == date:
                end_date = ""
            description = unescape(block.get("description") or "").strip()
            return Tour(
                section="DAV Friedrichshafen",
                title=unescape(block.get("name") or "").strip(),
                date=date,
                url=url,
                category=category,
                difficulty=_parse_fn_difficulty(resp.text),
                end_date=end_date,
                registration_deadline=_parse_fn_registration_deadline(description, date),
                description=description,
            )
    return None


def _fetch_fn_category_urls(session: requests.Session, category_key: str) -> list[str]:
    resp = session.get(
        f"{FN_BASE_URL}{FN_CATEGORY_BASE_PATH}/{category_key}", timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    urls: list[str] = []
    for block in _extract_ld_json_blocks(resp.text):
        if block.get("@type") != "ItemList":
            continue
        for item in block.get("itemListElement", []):
            url = item.get("url")
            if url:
                urls.append(url)
    return urls


def fetch_fn_category_map(session: requests.Session) -> dict[str, str]:
    """Bildet Tour-URL -> Tourart ab, indem die Bergsportart-Unterseiten abgefragt werden.

    Die Übersichtsseite selbst kennt keine Tourart je Eintrag; jede
    Bergsportart-Seite listet aber nur ihre eigenen Touren als JSON-LD.
    """
    labels_by_url: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=len(FN_CATEGORIES)) as pool:
        futures = {
            pool.submit(_fetch_fn_category_urls, session, key): label
            for key, label in FN_CATEGORIES.items()
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                urls = future.result()
            except requests.RequestException:
                continue
            for url in urls:
                labels_by_url.setdefault(url, []).append(label)
    return {url: "/".join(labels) for url, labels in labels_by_url.items()}


def fetch_fn_tours(max_workers: int = 8) -> list[Tour]:
    session = _session()
    paths = fetch_fn_tour_urls(session)
    category_map = fetch_fn_category_map(session)
    tours: list[Tour] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_fn_tour_detail, session, path, category_map.get(path, "")): path
            for path in paths
        }
        for future in as_completed(futures):
            tour = future.result()
            if tour is not None:
                tours.append(tour)
    return tours


# --------------------------------------------------------------------------- #
# DAV Ravensburg
# --------------------------------------------------------------------------- #

class RavensburgRow(TypedDict):
    status: str
    title: str
    url: str
    time: str
    date: str


class _RavensburgTableParser(HTMLParser):
    """Parst die von /we_tour.ajax gelieferte HTML-Tabelle der Tourenliste."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[RavensburgRow] = []
        self._in_row = False
        self._col_index = -1
        self._cell_text: list[str] = []
        self._current_href = ""
        self._row: RavensburgRow = {"status": "", "title": "", "url": "", "time": "", "date": ""}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "tr" and (attrs_d.get("class") or "").startswith("tr-"):
            self._in_row = True
            self._row = {"status": "", "title": "", "url": "", "time": "", "date": ""}
            self._col_index = -1
        elif tag == "td" and self._in_row:
            self._col_index += 1
            self._cell_text = []
        elif tag == "a" and self._in_row and self._col_index == 2:
            self._current_href = attrs_d.get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_row:
            text = unescape("".join(self._cell_text)).strip()
            if self._col_index == 0:
                self._row["status"] = text
            elif self._col_index == 2:
                self._row["title"] = text
                self._row["url"] = self._current_href
            elif self._col_index == 3:
                self._row["time"] = text
            elif self._col_index == 4:
                self._row["date"] = text
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._row.get("title"):
                self._rows.append(self._row)

    def handle_data(self, data: str) -> None:
        if self._in_row and self._col_index >= 0:
            self._cell_text.append(data)

    @property
    def rows(self) -> list[RavensburgRow]:
        return self._rows


def _parse_rv_date(date_str: str) -> str:
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", date_str)
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


_RV_CATEGORY_RE = re.compile(r"Kategorie:</th>\s*<td[^>]*>(.*?)</td>", re.S)
_RV_BEWERTUNG_RE = re.compile(r"Bewertung:</th>\s*<td[^>]*>(.*?)</td>", re.S)
_RV_DATUM_RE = re.compile(r"Datum:</th>\s*<td[^>]*>(.*?)</td>", re.S)
_RV_ANMELDUNG_ENDE_RE = re.compile(r"Datum Ende Anmeldung:</th>\s*<td[^>]*>(.*?)</td>", re.S)
_RV_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


class RavensburgDetails(NamedTuple):
    category: str
    difficulty: str
    end_date: str
    registration_deadline: str


def fetch_rv_tour_details(session: requests.Session, url: str) -> RavensburgDetails:
    """Holt Tourart, Schwierigkeit, Mehrtages-Enddatum und Anmeldeschluss von der
    Detailseite.

    Die Kalender-Listenansicht liefert nur Titel/Datum/Status; die genannten
    Felder stehen ausschließlich in der Steckbrief-Tabelle jeder Tour-Detailseite.
    """
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        return RavensburgDetails("", "", "", "")
    text = resp.text

    category = ""
    match = _RV_CATEGORY_RE.search(text)
    if match:
        category = unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()

    difficulty = ""
    match = _RV_BEWERTUNG_RE.search(text)
    if match:
        difficulty = unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()

    end_date = ""
    match = _RV_DATUM_RE.search(text)
    if match:
        dates = _RV_DATE_RE.findall(re.sub(r"<[^>]+>", " ", match.group(1)))
        if len(dates) >= 2:
            first_day, first_month, first_year = dates[0]
            last_day, last_month, last_year = dates[-1]
            if (last_year, last_month, last_day) != (first_year, first_month, first_day):
                end_date = f"{last_year}-{last_month}-{last_day}"

    registration_deadline = ""
    match = _RV_ANMELDUNG_ENDE_RE.search(text)
    if match:
        date_match = _RV_DATE_RE.search(match.group(1))
        if date_match:
            day, month, year = date_match.groups()
            registration_deadline = f"{year}-{month}-{day}"

    return RavensburgDetails(category, difficulty, end_date, registration_deadline)


def _enrich_rv_details(session: requests.Session, tours: list[Tour], max_workers: int = 8) -> None:
    def worker(tour: Tour) -> None:
        try:
            details = fetch_rv_tour_details(session, tour.url)
        except requests.RequestException:
            return
        tour.category = _normalize_category(details.category)
        tour.difficulty = details.difficulty
        tour.end_date = details.end_date
        tour.registration_deadline = details.registration_deadline

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(worker, tour) for tour in tours if tour.url]
        for future in as_completed(futures):
            future.result()


def fetch_rv_tours(archive: bool = False) -> list[Tour]:
    session = _session()
    resp = session.post(
        RV_BASE_URL + RV_AJAX_PATH,
        data={
            "tx_wetour_pi1[controller]": "Calendar",
            "tx_wetour_pi1[action]": "list",
            "tx_wetour_pi1[from]": "0",
            "tx_wetour_pi1[to]": "9999",
            "tx_wetour_pi1[category]": "",
            "tx_wetour_pi1[tourleader]": "",
            "tx_wetour_pi1[courses]": "",
            "tx_wetour_pi1[tours]": "",
            "tx_wetour_pi1[archive]": "1" if archive else "0",
            "type": "1358841824",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    parser = _RavensburgTableParser()
    parser.feed(resp.text)

    tours = []
    for row in parser.rows:
        url = row["url"]
        if url and not url.startswith("http"):
            url = RV_BASE_URL + url
        tours.append(
            Tour(
                section="DAV Ravensburg",
                title=row["title"],
                date=_parse_rv_date(row["date"]),
                time=row["time"],
                status=row["status"],
                url=url,
            )
        )
    _enrich_rv_details(session, tours)
    return tours


# --------------------------------------------------------------------------- #
# DAV Überlingen
# --------------------------------------------------------------------------- #

_UE_CARD_RE = re.compile(
    r'tour-day">(.*?)</span>.*?<h2>([^<]*)</h2><span class="tour-data">\s*(.*?)\s*</span>.*?'
    r'<a href="([^"]*?)\s*"><button class="btn btn-tourlist">',
    re.S,
)
_UE_DAY_MONTH_RE = re.compile(r"(\d{2})\.(\d{2})\.")
_UE_PAGE_LINK_RE = re.compile(r"touren/page/(\d+)/")


def _fetch_ue_page(session: requests.Session, page: int) -> str:
    url = f"{UE_BASE_URL}{UE_LIST_PATH}" if page == 1 else f"{UE_BASE_URL}{UE_LIST_PATH}/page/{page}/"
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _resolve_ue_date(day: int, month: int, reference: datetime.date) -> str:
    # Die Seite zeigt nur "TT.MM." ohne Jahr; ein TT.MM. das vor dem Referenzdatum
    # läge, gehört stattdessen zum Folgejahr (gilt für Start- wie Enddatum, indem
    # das jeweils vorherige Datum als Referenz übergeben wird).
    try:
        candidate = datetime.date(reference.year, month, day)
    except ValueError:
        return ""
    if candidate < reference:
        try:
            candidate = datetime.date(reference.year + 1, month, day)
        except ValueError:
            return ""
    return candidate.isoformat()


def fetch_ue_tours(max_workers: int = 8) -> list[Tour]:
    session = _session()
    first_html = _fetch_ue_page(session, 1)
    total_pages = max((int(m) for m in _UE_PAGE_LINK_RE.findall(first_html)), default=1)

    htmls = [first_html]
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=min(total_pages - 1, max_workers)) as pool:
            futures = {
                pool.submit(_fetch_ue_page, session, page): page
                for page in range(2, total_pages + 1)
            }
            pages: dict[int, str] = {}
            for future in as_completed(futures):
                pages[futures[future]] = future.result()
            htmls.extend(pages[page] for page in sorted(pages))

    today = datetime.date.today()
    tours: list[Tour] = []
    for html in htmls:
        for day_raw, title, category_field, link in _UE_CARD_RE.findall(html):
            day_text = re.sub(r"<[^>]+>", " ", day_raw)
            day_matches = _UE_DAY_MONTH_RE.findall(day_text)
            date_str = ""
            end_date_str = ""
            if day_matches:
                date_str = _resolve_ue_date(
                    int(day_matches[0][0]), int(day_matches[0][1]), today
                )
                if len(day_matches) > 1 and date_str:
                    start = datetime.date.fromisoformat(date_str)
                    end_date_str = _resolve_ue_date(
                        int(day_matches[-1][0]), int(day_matches[-1][1]), start
                    )
                    if end_date_str == date_str:
                        end_date_str = ""
            parts = [p.strip() for p in category_field.split("|")]
            category = parts[1] if len(parts) > 1 else ""
            # Nach Tourart folgt optional die Schwierigkeit als "T"-Skala (z.B. "T3"
            # oder "T1, T2"), gefolgt von der Konditionsskala ("K..."), die wir ignorieren.
            difficulty = next(
                (p for p in parts[2:] if re.match(r"^T\d", p)), ""
            )
            tours.append(
                Tour(
                    section="DAV Überlingen",
                    title=unescape(title).strip(),
                    date=date_str,
                    url=link.strip(),
                    category=category,
                    difficulty=difficulty,
                    end_date=end_date_str,
                )
            )
    return tours


# --------------------------------------------------------------------------- #
# Ausgabe
# --------------------------------------------------------------------------- #

def _days_span(tour: Tour) -> int:
    """Anzahl der Tage einer Mehrtagestour, oder 0 für eintägige/undatierte Touren."""
    if not tour.date or not tour.end_date or tour.end_date <= tour.date:
        return 0
    try:
        start = datetime.date.fromisoformat(tour.date)
        end = datetime.date.fromisoformat(tour.end_date)
    except ValueError:
        return 0
    return (end - start).days + 1


def _print_text(tours: Iterable[Tour]) -> None:
    tours = list(tours)
    if not tours:
        print("Keine Touren gefunden.")
        return
    width = max(len(t.title) for t in tours)
    today = datetime.date.today().isoformat()
    current_section = None
    for tour in tours:
        if tour.section != current_section:
            current_section = tour.section
            print(f"\n== {current_section} ==")
        category_part = f" ({tour.category})" if tour.category else ""
        difficulty_part = f" [{tour.difficulty}]" if tour.difficulty else ""
        days = _days_span(tour)
        days_part = f" [{days} Tage]" if days else ""
        deadline_part = (
            "  (Anmeldefrist abgelaufen)"
            if tour.registration_deadline and tour.registration_deadline < today
            else ""
        )
        extra = f"  [{tour.status}]" if tour.status else ""
        time_part = f" {tour.time}" if tour.time else ""
        print(
            f"{tour.date or '?':<10}{time_part:<7} {tour.title:<{width}}{category_part}{difficulty_part}{days_part}  "
            f"{tour.url}{extra}{deadline_part}"
        )


def _write_csv(tours: Iterable[Tour], path: str) -> None:
    fields = [
        "section",
        "date",
        "end_date",
        "time",
        "title",
        "category",
        "difficulty",
        "status",
        "registration_deadline",
        "url",
        "description",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for tour in tours:
            writer.writerow(dataclasses.asdict(tour))


def _write_json(tours: Iterable[Tour], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([dataclasses.asdict(t) for t in tours], f, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--section",
        choices=["fn", "rv", "ue", "all"],
        default="all",
        help="Nur eine Sektion abfragen (fn=Friedrichshafen, rv=Ravensburg, "
        "ue=Überlingen). Standard: all",
    )
    parser.add_argument(
        "--format",
        choices=["text", "csv", "json"],
        default="text",
        help="Ausgabeformat. Standard: text",
    )
    parser.add_argument(
        "--output",
        help="Datei für csv/json-Ausgabe. Ohne Angabe wird nach stdout geschrieben (text) "
        "bzw. ein Dateiname erzwungen (csv/json).",
    )
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="Ravensburg: auch vergangene (archivierte) Touren einbeziehen.",
    )
    parser.add_argument(
        "--include-past",
        action="store_true",
        help="Friedrichshafen listet die komplette Saison; ohne diese Option werden "
        "bereits vergangene Termine herausgefiltert.",
    )
    args = parser.parse_args(argv)

    tours: list[Tour] = []
    errors: list[str] = []

    if args.section in ("fn", "all"):
        try:
            tours.extend(fetch_fn_tours())
        except requests.RequestException as exc:
            errors.append(f"DAV Friedrichshafen konnte nicht geladen werden: {exc}")

    if args.section in ("rv", "all"):
        try:
            tours.extend(fetch_rv_tours(archive=args.include_archive))
        except requests.RequestException as exc:
            errors.append(f"DAV Ravensburg konnte nicht geladen werden: {exc}")

    if args.section in ("ue", "all"):
        try:
            tours.extend(fetch_ue_tours())
        except requests.RequestException as exc:
            errors.append(f"DAV Überlingen konnte nicht geladen werden: {exc}")

    if not args.include_past:
        today = datetime.date.today().isoformat()
        tours = [t for t in tours if not t.date or t.date >= today]

    tours.sort(key=Tour.sort_key)

    if args.format == "text":
        _print_text(tours)
    elif args.format == "csv":
        _write_csv(tours, args.output or "touren.csv")
        print(f"{len(tours)} Touren geschrieben nach {args.output or 'touren.csv'}")
    elif args.format == "json":
        _write_json(tours, args.output or "touren.json")
        print(f"{len(tours)} Touren geschrieben nach {args.output or 'touren.json'}")

    for error in errors:
        print(f"Warnung: {error}", file=sys.stderr)

    return 1 if errors and not tours else 0


if __name__ == "__main__":
    raise SystemExit(main())
