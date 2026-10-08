#!/usr/bin/env python3
"""class_search.py — query NC State **Class Search** for term/section/enrollment data.

Part of Wolfpack-Admin - https://github.com/bmmcconn/Wolfpack-Admin (MIT License).
UNOFFICIAL: not an NC State product or service. Queries the same public Class
Search endpoint that go.ncsu.edu/class_search uses; please be considerate - the
tool sends one POST per query and retries only on 5xx server errors.

Class Search (go.ncsu.edu/class_search) is the TERM-SPECIFIC schedule tool: it
lists the actual sections offered in a given term with live enrollment counts,
meeting times, instructors, and mode. This is DISTINCT from the Course Catalog
(go.ncsu.edu/course_catalog → coursecat/directory.php), which is the term-agnostic
catalog of course descriptions and carries no sections or enrollment.

Under the hood the form at coursecat/index.php POSTs the search to
coursecat/search.php, which returns JSON: {"html": <results table>, "json": ...}.
This module fills in that form, parses the results table, and hands back
structured data (grouped by course, one record per section).

Enrollment semantics: the "Avail." column is SEATS AVAILABLE / CAPACITY (not
enrolled). e.g. "Open 33/60" = 33 seats open of 60 (so 27 enrolled); "Closed 0/5"
= 0 seats left (full). `enrolled` is derived (capacity - seats_available). Counts
are LIVE and move daily until the term settles.

Public API:
    search_classes(term, subject, ...) -> list[course dict]   # main entry point
    resolve_term(term) -> "2268"          # "Fall 2026" | "2026 fall" | 2268 -> strm
    build_term_code(year, season) -> "2268"
    default_term() -> "2271"              # the term Class Search opens on (live)
    list_terms() -> [{"code","label","default"}]   # scrapes the term dropdown (live)
    list_subjects(term) -> [{"code","name"}]
    flatten_sections(courses, term, pulled) -> flat dicts, one per section (CSV)
    summarize_by_mode(courses) -> per-course on-campus vs online Enr/Cap rollup

With no term, the CLI uses default_term(): the term the site's dropdown selects
(2027 Spring on 2026-10-07), NOT the first one listed -- the dropdown puts the
coming summer terms first (2027 Summer 2), which have almost no sections.

Each course dict:
    {subject, number, title, units, description, requisites, also_listed_as,
     enrolled, capacity, enrollment_published, sections:[...]}
Each section dict:
    {section, component, class_number, status, enrolled, capacity, waitlist,
     seats_available, mode, distance_ed, days, time, location, instructor,
     start_date, end_date, topic, notes, class_notes, class_requisites,
     seat_reserves, syllabus}
`waitlist` is the parenthetical count in the Avail. column; it has only ever been
observed as 0, so treat its exact semantics (waitlist vs reserved) as unverified.

`description` and `requisites` are the catalog text Class Search prints above a
course's sections (requisites "" when it prints none); both matched the Course
Catalog for all 61 ISE Fall 2026 courses (2026-10-07). `also_listed_as` lists
every cross-listing, "MA 505, OR 505". The site separates them with spaces, so
until 2026-10-07 only the first was kept.

A section that meets at different times on different days has one entry per
meeting in `days` and `time`, aligned and joined with "; ": ISE 554-001 Fall
2026 is "Tu/Th; M" and "7:30 PM - 8:45 PM; 6:00 PM - 8:45 PM" ("TBD" for a
meeting with none). `location` and `instructor` list each distinct entry once,
joined with "; " ("Doe,Jane A.; Roe,John"). Until 2026-10-07 these
cells ran together with spaces and every meeting time after the first was lost.

The Notes column holds up to three popovers, kept apart since 2026-10-07:
`class_notes`, `class_requisites` (EM 501-001 Spring 2027: "R: MEM Students
Only") and `seat_reserves`, a list of {"seats", "reserved_for"} ({"seats": 40,
"reserved_for": "R: MEM Students Only"}). Items within each are joined with
"; ". `notes` still holds all three, joined with " | ", for older readers.

`topic` is the results table's **Topic** column: the real subject of a
special-topics section (ISE 489/589, EM 589, ...), which the catalog `title`
never carries -- every such section is titled only "Special Topics in ...".
e.g. ISE 589-012 Spring 2026 has title "Special Topics In Industrial
Engineering" and topic "Optimization for Machine Learning". Empty string for
ordinary courses. **Searching titles alone will silently miss every
special-topics offering**, which for ISE/EM is where new courses appear before
they get a permanent number.

⚠️ COLUMN ORDER IS NOT FIXED ACROSS TERMS -- cells are read by HEADER NAME, never
by position. Current/future terms publish 10 columns; terms whose enrollment has
closed publish 9, dropping **Avail.** and shifting every later column left by
one. Parsing by position put the Begin/End date into `instructor` for past terms
(verified 2026-08-14 against Fall 2025 and Spring 2026). `enrollment_published`
(course level) is False when the term served no Avail. column, which is the
honest reason status/enrolled/capacity/seats_available are all None, and so are
the course's enrolled/capacity totals -- distinct from markup drift, which still
warns. Such a term can't answer open_only, so that raises.

`mode` vs `distance_ed` are DIFFERENT questions and both are kept. `mode`
("online"/"in-person") is how the section physically meets; `distance_ed` (bool)
is whether it is DE-coded. A synchronous DE section meets in a room AND is
DE-coded, so it is mode="in-person" with distance_ed=True. `--summary` splits on
`distance_ed`, which is the line that matters for enrollment reporting.

⚠️ Every server-side filter is ADVISORY -- Class Search returns extra rows for
--instructor, --open-only and --mode alike. search_classes() re-applies all three
against the parsed data; see the comments at the end of it for each case.

`syllabus` (bool) is TRUE when Class Search publishes a syllabus for that class
number. Class Search emits the syllabus.php link only for sections that have one
(verified 2026-07-30 against the alternative endpoint, which returns "No published
syllabus was found." for every section lacking the link). This makes the field a
usable REG 02.20.07 compliance check, but ONLY while a term is in session: Class
Search showed no syllabus links at all for ended terms (Spring 2026, 0 of 82 ISE
sections) or terms not yet started (Spring 2027, 0 of 290 CH sections), checked
2026-10-07. So when a response has no syllabus link and today falls outside its
sections' dates, `syllabus` is None (unknown), not False. ⚠️ Cross-listed
sections are tracked SEPARATELY: a syllabus posted under EM 538 does NOT mark
ISE 538 compliant, so check every prefix a course carries (see `also_listed_as`).

Failure posture: unknown subjects, unparseable results markup, bad subject-list
responses and network errors all raise ClassSearchError (never a silent empty
list); sections whose Avail. cell can't be parsed emit a warning and are
excluded from course totals.

CLI (output is BY COURSE, Avail/Cap + Enrolled per section):
    class_search.py EM                        # the term Class Search opens on
    class_search.py EM --term "Fall 2026"
    class_search.py EM --term 2268 --open-only
    class_search.py MAE --term 2268 --mode online
    class_search.py ISE --term 2268 --distance-ed             # all DE-coded sections
    class_search.py ISE --term 2268 --distance-ed --mode in-person   # synchronous DE
    class_search.py EM --term 2268 --json     # structured; includes pulled_at
    class_search.py EM --term 2268 --csv      # flat, one row per section
    class_search.py EM --term 2268 --summary  # per-course: on-campus vs online
    class_search.py --list-terms
    class_search.py --list-subjects --term 2268
PowerShell: quote inequality args (`--ineq "<="`) — bare < / > are redirection.

Stdlib only (no third-party dependencies). Read-only network GET/POST; writes nothing.
"""

import argparse
import csv
import errno
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import date, datetime

BASE = "https://webappprd.acs.ncsu.edu/php/coursecat"
SEARCH_URL = f"{BASE}/search.php"
INDEX_URL = f"{BASE}/index.php"
SUBJECTS_URL = f"{BASE}/subjects.php"
USER_AGENT = "Mozilla/5.0 (class_search.py; NC State internal schedule query)"

# NC State term (strm) code = "2" + two-digit year + season digit.
SEASON_DIGITS = {
    "spring": "1", "summer1": "6", "summer": "6", "summer2": "7", "fall": "8",
}
SEASON_LABELS = {"1": "Spring", "6": "Summer 1", "7": "Summer 2", "8": "Fall"}

DAY_ABBR = {
    "Sunday": "Su", "Monday": "M", "Tuesday": "Tu", "Wednesday": "W",
    "Thursday": "Th", "Friday": "F", "Saturday": "Sa",
}
CAREER_CODES = {
    "undergraduate": "UGRD", "ugrd": "UGRD", "graduate": "GRAD", "grad": "GRAD",
    "veterinary": "VETM", "vetm": "VETM", "agricultural": "AGI", "agi": "AGI",
}
TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[AP]M\s*-\s*\d{1,2}:\d{2}\s*[AP]M")
AVAIL_RE = re.compile(
    r"(Open|Closed|Waitlist|Reserved)\s*(\d+)\s*/\s*(\d+)(?:\s*\((\d+)\))?"
)
# Class Search renders a syllabus icon linking to syllabus.php?strm=..&class_nbr=N
# ONLY for sections that have a published syllabus. Verified 2026-07-30: for a
# section with no link, syllabus.php returns a 32-byte page reading "No published
# syllabus was found." The link therefore IS the compliance signal.
SYLLABUS_RE = re.compile(r"syllabus\.php\?[^\"']*?class_nbr=(\d+)")
# Multi-line cells (several meetings, rooms or instructors) separate their entries
# with <br />.
BR_RE = re.compile(r"<br\s*/?>", re.I)
COURSE_CODE_RE = re.compile(r"[A-Z]{1,5}\s*\d{2,3}[A-Z]?")
# "40 seats - R: MEM Students Only" / "1 seat - Restriction: MAE Seniors Only"
RESERVE_RE = re.compile(r"(\d+)\s+seats?\s*-\s*(.*)", re.S)


class ClassSearchError(RuntimeError):
    """Raised when the Class Search endpoint returns an error or bad response."""


# ---------------------------------------------------------------------------
# Term handling
# ---------------------------------------------------------------------------

def build_term_code(year, season):
    """(2026, 'fall') -> '2268'. Season: spring/summer1/summer2/fall (summer=summer1).

    The code keeps only two digits of the year, so years run 2000-2099 ("Fall
    1999" came back as 2998, i.e. Fall 2099, until 2026-10-07).
    """
    key = str(season).strip().lower().replace(" ", "")
    if key not in SEASON_DIGITS:
        raise ValueError(
            f"unknown season {season!r}; use one of "
            f"{sorted(set(SEASON_DIGITS))}"
        )
    year = int(year)
    if not 2000 <= year <= 2099:
        raise ValueError(f"year {year} is out of range: term codes cover 2000-2099")
    return f"2{year % 100:02d}{SEASON_DIGITS[key]}"


def resolve_term(term):
    """Normalize a term to a 4-digit strm string.

    Accepts: 2268 / "2268" (validated and returned) or a friendly form in either
    order, e.g. "Fall 2026", "2026 Fall", "summer1 2026", "2026 Summer Term 2".
    A plain "Summer 2026" is Summer 1.

    A bare calendar year ("2026") is REJECTED rather than misread as a strm code
    (strm 2026 would be Summer 1 *2002*) — pass a season or the real code.
    """
    s = str(term).strip()
    if re.fullmatch(r"\d{4}", s):
        if 2000 <= int(s) <= 2099:
            raise ValueError(
                f"term {s!r} looks like a bare calendar year, which is ambiguous "
                f"with a strm code (strm {s} = {term_label(s)}). Pass a season "
                f"('Fall {s}') or the strm code (Fall 2026 = 2268)."
            )
        if s[0] == "2" and s[3] in SEASON_LABELS:
            return s
        raise ValueError(
            f"{s!r} is not a valid strm term code (format: 2 + two-digit year + "
            "season digit, Spring=1/Summer1=6/Summer2=7/Fall=8; Fall 2026 = 2268)"
        )
    low = s.lower()
    ym = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", low)
    if not ym:
        raise ValueError(f"cannot parse a year from term {term!r}")
    year = int(ym.group(0))
    # Read the season with the year cut out: "summer 2026" matched "summer 2"
    # and became Summer 2 until 2026-10-07.
    rest = f"{low[:ym.start()]} {low[ym.end():]}"
    if "spring" in rest:
        season = "spring"
    elif "summer" in rest:
        # "summer 2", "summer2", "summer term 2", "summer session 2", "summer ii",
        # "second summer"; anything else is Summer 1.
        second = re.search(r"(?<!\d)2(?!\d)|\bii\b|\bsecond\b", rest)
        season = "summer2" if second else "summer1"
    elif "fall" in rest or "autumn" in rest:
        season = "fall"
    else:
        raise ValueError(
            f"cannot parse a season from term {term!r} "
            "(expected spring/summer/fall)"
        )
    return build_term_code(year, season)


def term_label(strm):
    """'2268' -> '2026 Fall' (best-effort; non-4-digit input passes through)."""
    strm = str(strm)
    if not re.fullmatch(r"\d{4}", strm):
        return strm
    year = 2000 + int(strm[1:3])
    season = SEASON_LABELS.get(strm[3], f"Season {strm[3]}")
    return f"{year} {season}"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http(url, data=None, timeout=30, retries=2):
    """GET (data=None) or POST (data=dict) and return the decoded body text.

    Transient failures (connect/read timeouts, connection errors, HTTP 5xx) are
    retried up to `retries` times with a short backoff (0.5s, 1.5s). Other HTTP
    errors raise immediately, with the response body (truncated) for diagnosis.
    """
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    last = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(0.5 * (3 ** (attempt - 1)))
        req = urllib.request.Request(url, data=body,
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            snippet = ""
            try:
                snippet = _clean(e.read(2000).decode("utf-8", "replace"))[:200]
            except (OSError, http.client.HTTPException):
                pass
            msg = f"HTTP {e.code} from {url}" + (f": {snippet}" if snippet else "")
            if e.code not in (500, 502, 503, 504):
                raise ClassSearchError(msg) from e
            last = ClassSearchError(msg)
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as e:
            # NB: a read-timeout mid-body raises TimeoutError, NOT URLError, and
            # http.client's own errors are not OSErrors: a connection dropped
            # mid-body (IncompleteRead) escaped as a traceback until 2026-10-07.
            last = ClassSearchError(f"request to {url} failed: {e}")
    raise last


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _clean(fragment):
    """Strip tags + unescape entities + collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _entries(cell):
    """A multi-line cell's distinct non-empty entries, in order."""
    return list(dict.fromkeys(t for t in (_clean(p) for p in BR_RE.split(cell)) if t))


def _parse_daytime(cell):
    """Return (days, time) for ONE meeting. days e.g. 'M/W/F'; time may be ''."""
    days = []
    for cls, inner in re.findall(r'<li class="([^"]*)"[^>]*>(.*?)</li>', cell, re.S):
        if "meet" in cls.split():
            m = re.search(r'title="([^"]+)"', inner)
            name = (m.group(1).split(" - ")[0].strip() if m else _clean(inner))
            days.append(DAY_ABBR.get(name, name))
    tm = TIME_RE.search(_clean(cell))
    return "/".join(days), (tm.group(0).strip() if tm else "")


def _parse_meetings(cell):
    """Return (days, time) from a Day/Time cell, one "; "-joined entry per meeting.

    A section that meets at different times on different days lists each meeting
    on its own line: ISE 554-001 Fall 2026 is Tu/Th 7:30-8:45 PM <br /> M
    6:00-8:45 PM -> ("Tu/Th; M", "7:30 PM - 8:45 PM; 6:00 PM - 8:45 PM"). The two
    strings stay aligned, so a meeting with no days or time reads "TBD".
    """
    meetings = [_parse_daytime(part) for part in BR_RE.split(cell)]
    if len(meetings) == 1:
        return meetings[0]
    return ("; ".join(d or "TBD" for d, _ in meetings),
            "; ".join(t or "TBD" for _, t in meetings))


def _popovers(tr):
    """[(kind, [item, ...])] for each popover in a row's Notes cell, in page order.

    kind comes from the popover's id: "notes" (Class Notes), "reqs" (Class
    Requisites) or "reserve" (Class Seat Reserves). The text sits in
    data-content, one item per <p> (requisites, reserves) or <br /> (notes).
    """
    out = []
    for m in re.finditer(r'<a\b[^<]*?data-toggle="popover"', tr):
        end = tr.find("</a>", m.end())
        tag = tr[m.start():end if end >= 0 else len(tr)]
        content = re.search(r'data-content="([^"]*)"', tag)
        if not content:
            continue
        kind = re.search(r'\bid="([a-z]+)-', tag)
        items = [_clean(p) for p in re.split(r"<p\b[^>]*>|<br\s*/?>", content.group(1))]
        out.append((kind.group(1) if kind else "", [t for t in items if t]))
    return out


# Results-table header label -> canonical section-dict key. Cells are located by
# matching these against the <th> row, because the column SET varies by term (see
# the module docstring: past terms omit "Avail." and shift everything after it).
# Keys are whitespace-STRIPPED and lowercased, because the <th> labels are split
# by responsive spans -- "Sec<span class='hidden-xs'>tion</span>" cleans to
# "Sec tion", not "Section". Matching on the spaced form silently matches nothing,
# which falls back to positional parsing and looks like it worked on current terms.
HEADER_KEYS = {
    "section": "section",
    "component": "component",
    "class#": "class_number",
    "avail": "avail",
    "day/time": "daytime",
    "location": "location",
    "instructor": "instructor",
    "begin/enddates": "dates",
    "topic": "topic",
    "notes": "notes",
}


def _parse_header(block):
    """Map canonical column key -> td index, from the results table's <th> row.

    Returns {} when no header row is present, which makes every lookup in
    _parse_section() fall back to its positional default.
    """
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        ths = re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S)
        if not ths:
            continue
        cols = {}
        for i, raw in enumerate(ths):
            name = re.sub(r"\s+", "", _clean(raw)).lower().rstrip(".")
            key = HEADER_KEYS.get(name)
            if key and key not in cols:
                cols[key] = i
        if "section" in cols:
            return cols
    return {}


def _parse_section(tr, cols=None):
    """Parse one <tr> section row into a dict, or None if it isn't a data row.

    `cols` maps canonical key -> td index (see _parse_header). Positional
    fallbacks apply only when a column is absent from the header map, and they
    assume the 10-column layout that includes Avail.
    """
    tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
    if len(tds) < 4:
        return None
    cols = cols or {}

    def cell(key, default_idx):
        """Raw td for a column, by header position when known, else positional."""
        idx = cols.get(key, default_idx)
        return tds[idx] if idx is not None and idx < len(tds) else ""

    # An absent Avail. column is a property of the TERM, not a parse failure --
    # `avail_served` distinguishes the two so only real drift warns upstream.
    avail_served = "avail" in cols or not cols
    status = enrolled = capacity = waitlist = seats = None
    m = AVAIL_RE.search(_clean(cell("avail", 3))) if avail_served else None
    if m:
        status = m.group(1)
        # NC State's "Avail." column is SEATS AVAILABLE / CAPACITY, not enrolled
        # (verified: every Closed section reads 0/N, i.e. 0 seats left = full).
        seats, capacity = int(m.group(2)), int(m.group(3))
        waitlist = int(m.group(4)) if m.group(4) is not None else None
        enrolled = capacity - seats
    days, time = _parse_meetings(cell("daytime", 4))
    # One <br />-separated entry per meeting (rooms) or per instructor; a
    # co-taught section ran together as "Doe,Jane A. Roe,John", and
    # names can't be split back apart (they contain spaces).
    location = "; ".join(_entries(cell("location", 5)))
    instructor = "; ".join(_entries(cell("instructor", 6)))
    # The Topic column carries the real subject of a special-topics section; the
    # catalog title only ever says "Special Topics in ...". No positional default:
    # guessing an index would invent topics on terms that don't serve the column.
    topic = _clean(cell("topic", None)) if "topic" in cols else ""
    dates = _clean(cell("dates", 7))
    start_date = end_date = ""
    dm = re.match(r"(\S+)\s*-\s*(\S+)", dates)
    if dm:
        start_date, end_date = dm.group(1), dm.group(2)
    # Requisites / seat-reserve / class-note text lives in popover data-content
    # attributes (the surrounding markup is malformed, so strip-and-join is noisy).
    pops = _popovers(tr)
    notes_seen = []
    for _, items in pops:
        t = "; ".join(dict.fromkeys(items))
        if t and t not in notes_seen:
            notes_seen.append(t)
    notes = " | ".join(notes_seen)

    def items_of(kind):
        return [i for k, items in pops if k == kind for i in items]

    seat_reserves = []
    for item in items_of("reserve"):
        rm = RESERVE_RE.fullmatch(item)
        seat_reserves.append({"seats": int(rm.group(1)), "reserved_for": rm.group(2).strip()}
                             if rm else {"seats": None, "reserved_for": item})
    # `mode` is PHYSICAL delivery and comes from the LOCATION cell only
    # ("Distance Education - Online"); matching the whole row would
    # false-positive on popover data-content text.
    mode = "online" if "Distance Education" in cell("location", 5) else "in-person"
    # `distance_ed` is how the section is CODED, which is a different question --
    # a DE section can meet in a room (synchronous DE broadcast to remote
    # students), e.g. ISE 408-601 Fall 2026: room 4134 Fitts-Woolard, M/W 1:30,
    # and DE-coded. Neither signal alone is complete: two ISE sections carry the
    # notes marker without the location one, and a CSC section the reverse
    # (verified 2026-08-11). Keep both fields -- collapsing them loses real
    # information either way.
    distance_ed = (mode == "online"
                   or "DISTANCE EDUCATION COURSE" in notes.upper())
    class_number = _clean(cell("class_number", 2))
    # Match the link's OWN class_nbr against this row's, so a mis-split row can't
    # borrow its neighbour's syllabus link (the surrounding markup is malformed).
    syllabus = any(m.group(1) == class_number for m in SYLLABUS_RE.finditer(tr))
    return {
        "section": _clean(cell("section", 0)),
        "component": _clean(cell("component", 1)),
        "class_number": class_number,
        "status": status,
        "enrolled": enrolled,
        "capacity": capacity,
        "waitlist": waitlist,
        "seats_available": seats,
        "mode": mode,
        "distance_ed": distance_ed,
        "days": days,
        "time": time,
        "location": location,
        "instructor": instructor,
        "start_date": start_date,
        "end_date": end_date,
        "topic": topic,
        "notes": notes,
        "class_notes": "; ".join(dict.fromkeys(items_of("notes"))),
        "class_requisites": "; ".join(dict.fromkeys(items_of("reqs"))),
        "seat_reserves": seat_reserves,
        "syllabus": syllabus,
    }


def _course_text(block):
    """(description, requisites, also_listed_as) from a course block's header.

    Between the <h1> and the sections table Class Search prints <p>description</p>,
    then optionally <p>requisite text</p>, then optionally an unclosed
    <p>Also listed as: MA 505 OR 505 -- codes separated by SPACES. The old regex
    expected commas and kept only the first code (17 of 64 cross-listed courses
    sampled 2026-10-07, e.g. ISE 505 lost OR 505).
    """
    m = re.search(r"</h1>(.*?)<table", block, re.S)
    paras = re.split(r"<p\b[^>]*>", m.group(1))[1:] if m else []
    description, requisites, also = "", [], []
    for i, para in enumerate(paras):
        text = _clean(para)
        if text.startswith("Also listed as:"):
            also += [re.sub(r"\s+", " ", code)
                     for code in COURSE_CODE_RE.findall(text.split(":", 1)[1])]
        elif i == 0:
            description = text
        elif text:
            requisites.append(text)
    return description, "; ".join(requisites), ", ".join(dict.fromkeys(also))


def _in_session(sections, today=None):
    """True if today falls between these sections' earliest start and latest end."""
    spans = []
    for s in sections:
        try:
            spans.append((datetime.strptime(s["start_date"], "%m/%d/%y").date(),
                          datetime.strptime(s["end_date"], "%m/%d/%y").date()))
        except ValueError:
            continue
    today = today or date.today()
    return bool(spans) and (min(a for a, _ in spans) <= today
                            <= max(b for _, b in spans))


def _parse_results(html_str):
    """Parse the search.php results HTML into a list of course dicts."""
    courses = []
    blocks = re.split(r'<section class="course"', html_str)[1:]
    for block in blocks:
        head = re.search(
            r"<h1>\s*([A-Z]{1,4})\s*(\d{2,3}[A-Z]?)\s*<small>([^<]*)</small>",
            block,
        )
        if not head:
            continue
        units = re.search(r'<span class="units[^"]*">\s*Units?:?\s*([0-9.\- ]+)', block)
        description, requisites, also_listed = _course_text(block)
        cols = _parse_header(block)
        sections = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
            if "<td" not in tr:
                continue
            sec = _parse_section(tr, cols)
            if sec:
                sections.append(sec)
        # No Avail. column at all = this term has closed enrollment and the site
        # simply doesn't publish the numbers. That is not markup drift, so it must
        # not warn -- warning on it trained the reader to ignore a real signal.
        enrollment_published = "avail" in cols or not cols
        bad_avail = sum(1 for s in sections if s["enrolled"] is None)
        if bad_avail and enrollment_published:
            warnings.warn(
                f"{head.group(1)} {head.group(2)}: {bad_avail} section(s) had an "
                "unparseable Avail. cell — course Enr/Cap totals exclude them "
                "(Class Search markup may have changed)")
        # None, not 0: a term that publishes no enrollment isn't an empty course.
        enr = cap = None
        if enrollment_published:
            enr = sum(s["enrolled"] for s in sections if s["enrolled"] is not None)
            cap = sum(s["capacity"] for s in sections if s["capacity"] is not None)
        courses.append({
            "subject": head.group(1),
            "number": head.group(2),
            "title": html.unescape(head.group(3)).strip(),
            "units": units.group(1).strip() if units else "",
            "description": description,
            "requisites": requisites,
            "also_listed_as": also_listed,
            "enrolled": enr,
            "capacity": cap,
            "enrollment_published": enrollment_published,
            "sections": sections,
        })
    # Class Search shows syllabus links only while a term is in session (see the
    # module docstring). No link anywhere outside the term's dates means "not
    # shown", not "missing", so don't let NO-SYL claim a compliance gap. Inside
    # them, no link is a real NO-SYL even when every section lacks one.
    every = [s for c in courses for s in c["sections"]]
    if every and not SYLLABUS_RE.search(html_str) and not _in_session(every):
        for s in every:
            s["syllabus"] = None
    return courses


def _filter_sections(courses, keep):
    """Keep only sections satisfying `keep`; drop emptied courses; fix totals.

    Every server-side filter this module exposes has turned out to be advisory --
    Class Search returns extra rows and leaves the caller to sort it out (see the
    callers for the specific cases). So each one is re-applied here against the
    parsed data.

    Course-level enrolled/capacity are RECOMPUTED, never carried over: they were
    summed across the UNFILTERED section list when the course was built, so
    keeping them would trade a wrong section count for a wrong headcount. They
    stay None for a term that publishes no enrollment.
    """
    kept = []
    for c in courses:
        secs = [s for s in c["sections"] if keep(s)]
        if not secs:
            continue
        c["sections"] = secs
        if c["enrollment_published"]:
            c["enrolled"] = sum(s["enrolled"] for s in secs if s["enrolled"] is not None)
            c["capacity"] = sum(s["capacity"] for s in secs if s["capacity"] is not None)
        kept.append(c)
    return kept


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _check_query(subject, course_number=None, course_inequality="=", career=None):
    """Validate a query before any request -> (subject, number, career_code)."""
    subject = str(subject).strip().upper()
    if not re.fullmatch(r"[A-Z]{1,4}", subject):
        raise ValueError(f"subject must be 1-4 letters, got {subject!r}")
    # The site's own form takes 3 digits and an optional letter (catalog.js);
    # anything else came back "No results" and printed as 0 courses, exit 0.
    number = "" if course_number is None else str(course_number).strip().upper()
    if number and not re.fullmatch(r"[0-9]{3}[A-Z]?", number):
        raise ValueError(
            f"course number must be 3 digits, optionally with a letter (534, 295A), "
            f"got {course_number!r}")
    if course_inequality not in ("=", "<=", ">="):
        raise ValueError(f"inequality must be '=', '<=' or '>=', got {course_inequality!r}")
    career_code = ""
    if career:
        key = str(career).strip().lower()
        if key not in CAREER_CODES:
            raise ValueError(
                f"unknown career {career!r}; use one of {sorted(set(CAREER_CODES))}")
        career_code = CAREER_CODES[key]
    return subject, number, career_code


def search_classes(term, subject, *, course_number=None, course_inequality="=",
                   career=None, session=None, start_time=None, end_time=None,
                   instructor=None, open_only=False, mode=None, distance_ed=None,
                   timeout=30):
    """Query Class Search and return a list of course dicts (see module docstring).

    term    : strm ("2268") or friendly ("Fall 2026").
    subject : subject prefix, e.g. "EM", "MAE", "ISE" (required by the site).
    mode    : None (all) | "online"/"distance" | "in-person"/"campus".
              PHYSICAL delivery. Orthogonal to distance_ed -- combine them to get
              synchronous DE (distance_ed=True, mode="in-person").
    distance_ed : None (all) | True (DE-coded only) | False (on-campus-coded only).
    open_only : True -> only sections with seats available.
    course_number + course_inequality ("=", "<=", ">=") : filter by catalog number.
    """
    strm = resolve_term(term)
    subject, number, career_code = _check_query(
        subject, course_number, course_inequality, career)

    params = {
        "term": strm,
        "subject": subject,
        "course-career": career_code,
        "course-inequality": course_inequality,
        "course-number": number,
        "session": session or "",
        "start-time": start_time or "",
        "start-time-inequality": ">=",
        "end-time": end_time or "",
        "end-time-inequality": "<=",
        "instructor-name": instructor or "",
        "current_strm": strm,
    }
    if open_only:
        params["open-classes"] = "1"
    if mode:
        # Validate here, but deliberately DON'T send "distance-only" to the
        # server. That parameter selects DE-CODED sections, so it cannot express
        # `mode` (physical delivery) now that the two are known to differ -- and
        # sending it would make mode/distance_ed uncombinable: asking for
        # DE-coded sections that meet in a room (distance_ed=True, mode
        # in-person) would set distance-only=0 and have the server drop exactly
        # the rows wanted. Both filters are applied below against parsed data.
        if str(mode).lower() not in ("online", "distance", "distance-only", "de",
                                     "in-person", "campus", "campus-only"):
            raise ValueError(
                f"mode must be 'online' or 'in-person' (Class Search has no "
                f"hybrid filter), got {mode!r}")

    raw = _http(SEARCH_URL, data=params, timeout=timeout)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClassSearchError(f"non-JSON response from search.php: {e}") from e
    if not isinstance(payload, dict):
        raise ClassSearchError(
            f"unexpected response shape from search.php: {type(payload).__name__}")
    if payload.get("error"):
        raise ClassSearchError(_clean(str(payload["error"])) or "search returned an error")

    html_str = payload.get("html") or ""
    if not isinstance(html_str, str):
        html_str = str(html_str)
    courses = _parse_results(html_str)
    # Fail loudly rather than return plausible-but-empty data: markup drift and
    # typo'd subjects both used to come back as a clean "0 courses".
    if not courses:
        if "<td" in html_str:
            raise ClassSearchError(
                "results HTML has table rows but no course could be parsed — "
                "Class Search markup may have changed; update _parse_results()")
        # A failed subject list raises in list_subjects(); it used to come back
        # empty here and skip the check, returning a silent 0 courses.
        known = {s["code"] for s in list_subjects(strm, timeout=timeout)}
        if subject not in known:
            if not known:
                raise ClassSearchError(
                    f"Class Search lists no subjects for {term_label(strm)} ({strm}) "
                    "— that term isn't on the schedule (see --list-terms)")
            raise ClassSearchError(
                f"no {subject} sections in {term_label(strm)} ({strm}) — wrong "
                "term, or mistyped subject")
    if open_only and courses and not any(c["enrollment_published"] for c in courses):
        # The server ignores open-classes here (ISE Spring 2026 returned all 46
        # courses), and with no seat counts every section would be dropped.
        raise ClassSearchError(
            f"can't tell which sections have open seats: Class Search doesn't "
            f"publish seat counts for {term_label(strm)} ({strm}) once a term ends")
    # --- Re-apply every filter the server treats as advisory (all verified
    # --- 2026-08-11 against Fall 2026; each returns extra rows server-side).
    if instructor:
        # instructor-name is applied only to sections that HAVE an instructor of
        # record; every unassigned ("Staff"/TBA) section comes back regardless.
        # ISE: `--instructor Mayorga` returned 1 real hit and 18 Staff sections.
        needle = instructor.strip().lower()
        courses = _filter_sections(
            courses, lambda s: needle in (s["instructor"] or "").lower())
    if open_only:
        # "open-classes" means NOT CLOSED, which includes Waitlist sections with
        # zero seats left. This module documents open_only as "has seats", so
        # honour that: ISE dropped 16 zero-seat Waitlist sections.
        courses = _filter_sections(courses, lambda s: (s["seats_available"] or 0) > 0)
    if mode:
        # "distance-only" selects DE-CODED sections, which is not the same as
        # "meets online" -- a DE section can meet in a room. Filter on the
        # physical `mode` so the rows match the flag the caller asked for; use
        # the `distance_ed` field (or --summary) for the DE/on-campus split.
        want = "online" if str(mode).lower() in (
            "online", "distance", "distance-only", "de") else "in-person"
        courses = _filter_sections(courses, lambda s: s["mode"] == want)
    if distance_ed is not None:
        want_de = bool(distance_ed)
        courses = _filter_sections(courses, lambda s: s["distance_ed"] == want_de)
    return courses


def _parse_terms(body):
    """index.php's term dropdown -> [{'code','label','default'}], in page order."""
    sel = re.search(r'<select[^>]*id="strm"[^>]*>(.*?)</select>', body, re.S)
    terms = []
    for attrs, label in re.findall(r"<option([^>]*)>([^<]+)</option>",
                                   sel.group(1) if sel else ""):
        code = re.search(r'value="(\d+)"', attrs)
        if code:
            terms.append({"code": code.group(1), "label": html.unescape(label).strip(),
                          "default": "selected" in attrs})
    return terms


def list_terms(timeout=30):
    """Scrape the term dropdown -> [{'code','label','default'}], newest first.

    `default` marks the term Class Search opens on (see default_term()).
    """
    terms = _parse_terms(_http(INDEX_URL, timeout=timeout))
    if not terms:
        raise ClassSearchError(
            "no term list on index.php — Class Search markup may have changed")
    return terms


def default_term(timeout=30):
    """The strm Class Search opens on: the dropdown's selected term.

    Not the newest: the dropdown lists the coming summer terms first. On
    2026-10-07 it opened on 2027 Spring (2271) with 2027 Summer 2 (2277) on top,
    and taking the top entry sent bare queries to a term with almost no sections.
    Falls back to the page's hidden current_strm, which matched.
    """
    body = _http(INDEX_URL, timeout=timeout)
    for t in _parse_terms(body):
        if t["default"]:
            return t["code"]
    m = re.search(r'id="current_strm"[^>]*value="(\d{4})"', body)
    if m:
        return m.group(1)
    raise ClassSearchError("could not find Class Search's default term; pass --term")


def list_subjects(term, timeout=30):
    """Return [{'code','name'}] of subjects offered in a term (via subjects.php).

    An empty list means the site lists none for that term (true of a term not yet
    on the schedule); a malformed response raises ClassSearchError.
    """
    strm = resolve_term(term)
    raw = _http(SUBJECTS_URL, data={"strm": strm}, timeout=timeout)
    try:
        subs = json.loads(raw)["subj_js"]
        items = json.loads(subs) if isinstance(subs, str) else subs
        if not isinstance(items, list):
            raise TypeError(f"subj_js is a {type(items).__name__}")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ClassSearchError(
            f"unexpected subjects.php response for {strm} ({e}): {raw[:120]!r}") from e
    out = []
    for it in items:
        s = it if isinstance(it, str) else (it.get("name") or it.get("value") or "")
        m = re.match(r"\s*([A-Z]{1,4})\s*-\s*(.*)", s)
        out.append({"code": m.group(1), "name": m.group(2).strip()} if m
                   else {"code": s.strip(), "name": ""})
    return out


CSV_FIELDS = [
    "pulled", "term", "subject", "number", "title", "units", "also_listed_as",
    "section", "component", "class_number", "topic", "status", "enrolled", "capacity",
    "waitlist", "seats_available", "mode", "distance_ed", "days", "time", "location",
    "instructor", "start_date", "end_date", "notes", "syllabus",
    # Added 2026-10-07, at the end so older pulls still line up by position.
    # `requisites` is the course's; the `class_` columns are the section's.
    # (`description` is in --json only: it would repeat on every section row.)
    "requisites", "class_notes", "class_requisites", "seat_reserves",
]


def _reserves_text(reserves):
    """[{"seats": 40, "reserved_for": "R: MEM Students Only"}] -> the site's text,
    "40 seats - R: MEM Students Only", items joined with "; "."""
    return "; ".join(
        r["reserved_for"] if r["seats"] is None else
        f"{r['seats']} seat{'' if r['seats'] == 1 else 's'} - {r['reserved_for']}"
        for r in reserves)


def flatten_sections(courses, term="", pulled=""):
    """Flatten course dicts into one flat dict per section (course cols repeated).

    Column order = CSV_FIELDS. `term` and `pulled` (ISO date) stamp every row so
    CSVs saved from different pulls can be concatenated and diffed over time.
    """
    rows = []
    for c in courses:
        for s in c["sections"]:
            row = {"pulled": pulled, "term": str(term),
                   "subject": c["subject"], "number": c["number"],
                   "title": c["title"], "units": c["units"],
                   "also_listed_as": c["also_listed_as"],
                   "requisites": c.get("requisites", "")}
            row.update({k: s[k] for k in CSV_FIELDS if k in s})
            row["seat_reserves"] = _reserves_text(s.get("seat_reserves") or [])
            rows.append(row)
    return rows


def summarize_by_mode(courses):
    """Roll each course's sections up into on-campus vs distance-ed Enr/Cap totals.

    Splits on `distance_ed` (how the section is CODED), not `mode` (how it
    physically meets) -- for enrollment reporting the DE/on-campus line is the
    one that matters, and a DE section that meets in a room belongs on the DE
    side of it. The `online_*` keys are named for that column's meaning to a
    reader, not for the `mode` field.

    Returns one dict per course:
        {subject, number, title, also_listed_as, enrollment_published,
         campus_enrolled, campus_capacity, online_enrolled, online_capacity}
    A side's Enr/Cap is None when the course has NO such section (so the CLI can
    print "—"), versus 0/N when a section exists but is empty; both sides are
    None when the term publishes no enrollment (enrollment_published False).
    Sections with an unparseable Avail. cell are skipped, matching the
    course-total convention in _parse_results().

    Caveat for cross-listed courses: each listing is a SEPARATE class, with its
    own class number, capacity and enrollment, so a per-subject rollup counts
    only the students enrolled under that prefix. The course's real size is the
    sum across every code in `also_listed_as`: EM 534 showed 37 in Fall 2026 and
    ISE 534 4 more, so the class was 41. (This docstring said the opposite, that
    summing across subjects double-counts, until 2026-10-07.)
    """
    rows = []
    for c in courses:
        agg = {"online": [0, 0, False], "in-person": [0, 0, False]}
        for s in c["sections"]:
            if s["enrolled"] is None:
                continue
            bucket = agg["online"] if s["distance_ed"] else agg["in-person"]
            bucket[0] += s["enrolled"]
            bucket[1] += s["capacity"]
            bucket[2] = True
        cam, onl = agg["in-person"], agg["online"]
        rows.append({
            "subject": c["subject"], "number": c["number"], "title": c["title"],
            "also_listed_as": c["also_listed_as"],
            "enrollment_published": c.get("enrollment_published", True),
            "campus_enrolled": cam[0] if cam[2] else None,
            "campus_capacity": cam[1] if cam[2] else None,
            "online_enrolled": onl[0] if onl[2] else None,
            "online_capacity": onl[1] if onl[2] else None,
        })
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _when(s):
    """'Tu/Th 7:30 PM - 8:45 PM; M 6:00 PM - 8:45 PM' from the aligned days/time."""
    days, times = s["days"].split("; "), s["time"].split("; ")
    if len(days) != len(times):
        return " ".join(x for x in (s["days"], s["time"]) if x) or "TBD"
    return "; ".join(" ".join(x for x in (d, t) if x and x != "TBD") or "TBD"
                     for d, t in zip(days, times))


def _fmt_courses(courses, strm):
    syl_shown = any(s["syllabus"] is not None for c in courses for s in c["sections"])
    lines = [f"NC State Class Search — {term_label(strm)} ({strm})",
             f"Pulled {date.today().isoformat()}  ·  Avail = seats available / "
             f"capacity; Enr = enrolled (capacity - available)",
             "SYL = published syllabus in Class Search; NO-SYL = none published"
             if syl_shown or not courses else
             "Syllabi: Class Search shows none for this term (only while one is in session)",
             ""]
    tot_a = tot_c = tot_e = tot_s = tot_syl = 0
    for c in courses:
        alt = f"  (= {c['also_listed_as']})" if c["also_listed_as"] else ""
        u = f" · {c['units']} cr" if c["units"] else ""
        # Printing "Avail 0/0 · Enr 0" for a term that publishes no enrollment
        # reads as an empty course rather than as absent data.
        if c.get("enrollment_published", True):
            roll = f"[Avail {c['capacity'] - c['enrolled']}/{c['capacity']} · Enr {c['enrolled']}]"
        else:
            roll = "[enrollment not published for this term]"
        lines.append(f"{c['subject']} {c['number']}  {c['title']}{u}   {roll}{alt}")
        for s in c["sections"]:
            tot_s += 1
            if s["seats_available"] is not None:
                tot_a += s["seats_available"]
                tot_c += s["capacity"]
                tot_e += s["enrolled"]
            avail = (f"{s['seats_available']}/{s['capacity']}"
                     if s["seats_available"] is not None else "n/a")
            enr = str(s["enrolled"]) if s["enrolled"] is not None else "n/a"
            wl = f" +{s['waitlist']}wl" if s["waitlist"] else ""
            when = _when(s)
            mode = "Online" if s["mode"] == "online" else "In-person"
            instr = s["instructor"] or "—"
            syl = {True: "SYL", False: "NO-SYL"}.get(s["syllabus"], "")
            tot_syl += 1 if s["syllabus"] else 0
            lines.append(
                f"    {s['section']:>3} {s['component']:<4} #{s['class_number']:<6}"
                f" Avail {avail:>7}{wl:<6} Enr {enr:>3}  {(s['status'] or ''):<8} "
                f"{mode:<9} {when:<22} {syl:<6} {instr}"
            )
            # The real subject of a special-topics section. Its own line because it
            # is the only place the actual course content appears.
            if s.get("topic"):
                lines.append(f"{'':>9}topic: {s['topic']}")
        lines.append("")
    if not courses:
        lines.append("0 courses · no sections match")
        return "\n".join(lines)
    # Same reason as the per-course rollup: a 0/0 total for a term that publishes
    # no Avail. column would read as "nobody enrolled". Decided by the flag, not
    # by tot_c, which is also 0 when nothing matched in a term that does publish.
    totals = (f"TOTAL Avail {tot_a}/{tot_c} · Enrolled {tot_e}"
              if any(c.get("enrollment_published", True) for c in courses)
              else "enrollment not published for this term")
    syllabi = (f"Syllabi {tot_syl}/{tot_s}" if syl_shown
               else "syllabi not shown for this term")
    lines.append(f"{len(courses)} courses · {tot_s} sections · {totals} · {syllabi}")
    return "\n".join(lines)


def _fmt_summary(courses, strm):
    """Per-course table: on-campus vs online Enr/Cap (the 'by mode' rollup)."""
    rows = summarize_by_mode(courses)
    published = any(r["enrollment_published"] for r in rows)

    def ec(r, side):
        # "n/a" = the term publishes no enrollment; "—" = no section on that side.
        if not r["enrollment_published"]:
            return "n/a"
        e, c = r[f"{side}_enrolled"], r[f"{side}_capacity"]
        return f"{e}/{c}" if e is not None else "—"

    codes = [f"{r['subject']} {r['number']}" for r in rows]
    titles = [r["title"] for r in rows]
    campus = [ec(r, "campus") for r in rows]
    online = [ec(r, "online") for r in rows]
    xlist = [r["also_listed_as"] or "—" for r in rows]

    ce = sum(r["campus_enrolled"] or 0 for r in rows)
    cc = sum(r["campus_capacity"] or 0 for r in rows)
    oe = sum(r["online_enrolled"] or 0 for r in rows)
    oc = sum(r["online_capacity"] or 0 for r in rows)
    campus_tot, online_tot = (f"{ce}/{cc}", f"{oe}/{oc}") if published else ("", "")

    wc = max([len("Course")] + [len(x) for x in codes])
    wt = max([len("Title")] + [len(x) for x in titles])
    wca = max([len("On-campus"), len(campus_tot)] + [len(x) for x in campus])
    wo = max([len("Online"), len(online_tot)] + [len(x) for x in online])
    wx = max([len("Cross-listed")] + [len(x) for x in xlist])

    def row(code, title, cap, onl, xl):
        return (f"{code:<{wc}}  {title:<{wt}}  {cap:>{wca}}  "
                f"{onl:>{wo}}  {xl:<{wx}}").rstrip()

    out = [f"NC State Class Search — {term_label(strm)} ({strm})",
           f"Enrolled / Capacity by mode (seats filled, not seats open) · "
           f"Pulled {date.today().isoformat()}", "",
           row("Course", "Title", "On-campus", "Online", "Cross-listed"),
           row("-" * wc, "-" * wt, "-" * wca, "-" * wo, "-" * wx)]
    for i, _ in enumerate(rows):
        out.append(row(codes[i], titles[i], campus[i], online[i], xlist[i]))
    # A 0/0 total for a closed term read as "nobody enrolled" (see _fmt_courses).
    if not rows:
        out += ["", "0 courses · no sections match"]
    elif not published:
        out += ["", f"{len(rows)} courses · enrollment not published for this term"]
    else:
        out.append(row("", "TOTAL", campus_tot, online_tot, ""))
        out += ["", f"{len(rows)} courses · grand total {ce + oe}/{cc + oc}"]
    return "\n".join(out)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(
        description="Query NC State Class Search for section + enrollment data "
                    "(output grouped by course, Enr/Cap per section).")
    ap.add_argument("subject", nargs="?", help="subject prefix, e.g. EM, MAE, ISE")
    ap.add_argument("--term", help="strm (2268) or friendly ('Fall 2026'); "
                    "default = the term Class Search opens on (see --list-terms)")
    ap.add_argument("--number", help="course number filter (with --ineq)")
    ap.add_argument("--ineq", default="=", choices=["=", "<=", ">="],
                    help="course-number comparison (default '=')")
    ap.add_argument("--career", help="undergraduate | graduate | veterinary | agricultural")
    ap.add_argument("--instructor", help="instructor last name")
    ap.add_argument("--mode", choices=["online", "in-person"],
                    help="filter by how the section physically meets")
    # Paired store_true/store_false with default=None gives a tri-state (unset /
    # DE-only / on-campus-only). argparse.BooleanOptionalAction would be tidier
    # but is 3.9+, and this module supports 3.8.
    ap.add_argument("--distance-ed", dest="distance_ed", action="store_true",
                    default=None, help="only DE-coded sections (incl. those that "
                                       "meet in a room)")
    ap.add_argument("--no-distance-ed", dest="distance_ed", action="store_false",
                    help="only on-campus-coded sections")
    ap.add_argument("--open-only", action="store_true", help="only sections with open seats")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="structured JSON output")
    fmt.add_argument("--csv", action="store_true",
                     help="flat CSV, one row per section (spreadsheet-ready)")
    fmt.add_argument("--summary", action="store_true",
                     help="per-course table: on-campus vs online Enr/Cap")
    ap.add_argument("--list-terms", action="store_true", help="print valid terms and exit")
    ap.add_argument("--list-subjects", action="store_true",
                    help="print subjects offered in --term and exit")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args(argv)
    # Checked before any request (a missing subject used to cost one first).
    if not (args.subject or args.list_terms or args.list_subjects):
        ap.error("subject is required (e.g. EM) unless using --list-terms or "
                 "--list-subjects")

    listing = None
    try:
        if args.list_terms:
            listing = [f"{t['code']}  {t['label']}" + ("  (default)" if t["default"] else "")
                       for t in list_terms(timeout=args.timeout)]
        else:
            if not args.list_subjects:
                _check_query(args.subject, args.number, args.ineq, args.career)
            if args.term:
                strm = resolve_term(args.term)
            else:
                strm = default_term(timeout=args.timeout)
                print(f"note: no --term; using {term_label(strm)} ({strm}), the term "
                      "Class Search opens on", file=sys.stderr)
            if args.list_subjects:
                listing = [f"{s['code']:<5} {s['name']}"
                           for s in list_subjects(strm, timeout=args.timeout)]
            else:
                courses = search_classes(
                    strm, args.subject, course_number=args.number,
                    course_inequality=args.ineq, career=args.career,
                    instructor=args.instructor, mode=args.mode,
                    distance_ed=args.distance_ed,
                    open_only=args.open_only, timeout=args.timeout,
                )
    except (ClassSearchError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        if listing is not None:
            if listing:
                print("\n".join(listing))
        elif args.json:
            print(json.dumps({"term": strm, "term_label": term_label(strm),
                              "subject": args.subject.upper(),
                              "pulled_at": datetime.now().isoformat(timespec="seconds"),
                              "courses": courses}, indent=2))
        elif args.csv:
            w = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(flatten_sections(courses, term=strm,
                                         pulled=date.today().isoformat()))
        elif args.summary:
            print(_fmt_summary(courses, strm))
        else:
            print(_fmt_courses(courses, strm))
        sys.stdout.flush()
    except OSError as e:
        # The reader stopped early (`| head -1`, `| Select-Object -First 5`).
        # A closed pipe is BrokenPipeError on POSIX but EINVAL on Windows. Point
        # stdout at devnull so the exit-time flush doesn't raise again.
        if not (isinstance(e, BrokenPipeError) or e.errno in (errno.EPIPE, errno.EINVAL)):
            raise
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
