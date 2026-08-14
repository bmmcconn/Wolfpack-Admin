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
    list_terms() -> [{"code","label"}]    # scrapes the term dropdown (live)
    list_subjects(term) -> [{"code","name"}]
    flatten_sections(courses, term, pulled) -> flat dicts, one per section (CSV)
    summarize_by_mode(courses) -> per-course on-campus vs online Enr/Cap rollup

Each course dict:
    {subject, number, title, units, also_listed_as, enrolled, capacity,
     enrollment_published, sections:[...]}
Each section dict:
    {section, component, class_number, status, enrolled, capacity, waitlist,
     seats_available, mode, distance_ed, days, time, location, instructor,
     start_date, end_date, topic, notes, syllabus}
`waitlist` is the parenthetical count in the Avail. column; it has only ever been
observed as 0, so treat its exact semantics (waitlist vs reserved) as unverified.

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
honest reason status/enrolled/capacity/seats_available are all None -- distinct
from markup drift, which still warns.

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
usable REG 02.20.07 compliance check. ⚠️ Cross-listed sections are tracked
SEPARATELY: a syllabus posted under EM 538 does NOT mark ISE 538 compliant, so
check every prefix a course carries (see `also_listed_as`).

Failure posture: unknown subjects, unparseable results markup, and network
errors all raise ClassSearchError (never a silent empty list); sections whose
Avail. cell can't be parsed emit a warning and are excluded from course totals.

CLI (output is BY COURSE, Avail/Cap + Enrolled per section):
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
import html
import json
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


class ClassSearchError(RuntimeError):
    """Raised when the Class Search endpoint returns an error or bad response."""


# ---------------------------------------------------------------------------
# Term handling
# ---------------------------------------------------------------------------

def build_term_code(year, season):
    """(2026, 'fall') -> '2268'. Season: spring/summer1/summer2/fall (summer=summer1)."""
    key = str(season).strip().lower().replace(" ", "")
    if key not in SEASON_DIGITS:
        raise ValueError(
            f"unknown season {season!r}; use one of "
            f"{sorted(set(SEASON_DIGITS))}"
        )
    return f"2{int(year) % 100:02d}{SEASON_DIGITS[key]}"


def resolve_term(term):
    """Normalize a term to a 4-digit strm string.

    Accepts: 2268 / "2268" (validated and returned) or a friendly form in either
    order, e.g. "Fall 2026", "2026 Fall", "summer1 2026", "2026 Summer Term 2".

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
    ym = re.search(r"(19|20)\d{2}", low)
    if not ym:
        raise ValueError(f"cannot parse a year from term {term!r}")
    year = int(ym.group(0))
    if "spring" in low:
        season = "spring"
    elif "summer" in low:
        season = "summer2" if re.search(r"(summer\s*2|term\s*2|\bii\b)", low) else "summer1"
    elif "fall" in low or "autumn" in low:
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
            except OSError:
                pass
            msg = f"HTTP {e.code} from {url}" + (f": {snippet}" if snippet else "")
            if e.code not in (500, 502, 503, 504):
                raise ClassSearchError(msg) from e
            last = ClassSearchError(msg)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # NB: a read-timeout mid-body raises TimeoutError, NOT URLError.
            last = ClassSearchError(f"request to {url} failed: {e}")
    raise last


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _clean(fragment):
    """Strip tags + unescape entities + collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_daytime(cell):
    """Return (days, time) from a Day/Time cell. days e.g. 'M/W/F'; time may be ''."""
    days = []
    for cls, inner in re.findall(r'<li class="([^"]*)"[^>]*>(.*?)</li>', cell, re.S):
        if "meet" in cls.split():
            m = re.search(r'title="([^"]+)"', inner)
            name = (m.group(1).split(" - ")[0].strip() if m else _clean(inner))
            days.append(DAY_ABBR.get(name, name))
    tm = TIME_RE.search(_clean(cell))
    return "/".join(days), (tm.group(0).strip() if tm else "")


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
    days, time = _parse_daytime(cell("daytime", 4))
    location = _clean(cell("location", 5))
    instructor = _clean(cell("instructor", 6))
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
    notes_seen = []
    for dc in re.findall(r'data-content="([^"]*)"', tr):
        t = _clean(dc)
        if t and t not in notes_seen:
            notes_seen.append(t)
    notes = " | ".join(notes_seen)
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
        "syllabus": syllabus,
    }


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
        also = re.search(
            r"Also listed as:\s*"
            r"((?:[A-Z]{1,4}\s*\d{2,3}[A-Z]?)(?:\s*,\s*[A-Z]{1,4}\s*\d{2,3}[A-Z]?)*)",
            _clean(block),
        )
        also_listed = ", ".join(
            re.sub(r"\s+", " ", code)
            for code in re.findall(r"[A-Z]{1,4}\s*\d{2,3}[A-Z]?", also.group(1))
        ) if also else ""
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
        enr = sum(s["enrolled"] for s in sections if s["enrolled"] is not None)
        cap = sum(s["capacity"] for s in sections if s["capacity"] is not None)
        courses.append({
            "subject": head.group(1),
            "number": head.group(2),
            "title": html.unescape(head.group(3)).strip(),
            "units": units.group(1).strip() if units else "",
            "also_listed_as": also_listed,
            "enrolled": enr,
            "capacity": cap,
            "enrollment_published": enrollment_published,
            "sections": sections,
        })
    return courses


def _filter_sections(courses, keep):
    """Keep only sections satisfying `keep`; drop emptied courses; fix totals.

    Every server-side filter this module exposes has turned out to be advisory --
    Class Search returns extra rows and leaves the caller to sort it out (see the
    callers for the specific cases). So each one is re-applied here against the
    parsed data.

    Course-level enrolled/capacity are RECOMPUTED, never carried over: they were
    summed across the UNFILTERED section list when the course was built, so
    keeping them would trade a wrong section count for a wrong headcount.
    """
    kept = []
    for c in courses:
        secs = [s for s in c["sections"] if keep(s)]
        if not secs:
            continue
        c["sections"] = secs
        c["enrolled"] = sum(s["enrolled"] for s in secs if s["enrolled"] is not None)
        c["capacity"] = sum(s["capacity"] for s in secs if s["capacity"] is not None)
        kept.append(c)
    return kept


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    subject = str(subject).strip().upper()
    if not re.fullmatch(r"[A-Z]{1,4}", subject):
        raise ValueError(f"subject must be 1-4 letters, got {subject!r}")

    career_code = ""
    if career:
        key = str(career).strip().lower()
        if key not in CAREER_CODES:
            raise ValueError(
                f"unknown career {career!r}; use one of {sorted(set(CAREER_CODES))}")
        career_code = CAREER_CODES[key]

    params = {
        "term": strm,
        "subject": subject,
        "course-career": career_code,
        "course-inequality": course_inequality,
        "course-number": str(course_number) if course_number else "",
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
        known = {s["code"] for s in list_subjects(strm, timeout=timeout)}
        if known and subject not in known:
            raise ClassSearchError(
                f"subject {subject!r} is not offered in {term_label(strm)} "
                f"({strm}) — unknown or mistyped subject")
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


def list_terms(timeout=30):
    """Scrape the term dropdown -> [{'code','label'}], newest first."""
    body = _http(INDEX_URL, timeout=timeout)
    sel = re.search(r'<select[^>]*id="strm"[^>]*>(.*?)</select>', body, re.S)
    if not sel:
        return []
    return [
        {"code": v, "label": html.unescape(t).strip()}
        for v, t in re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>', sel.group(1))
    ]


def list_subjects(term, timeout=30):
    """Return [{'code','name'}] of subjects offered in a term (via subjects.php)."""
    strm = resolve_term(term)
    raw = _http(SUBJECTS_URL, data={"strm": strm}, timeout=timeout)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    subs = payload.get("subj_js")
    try:
        items = json.loads(subs) if isinstance(subs, str) else (subs or [])
    except json.JSONDecodeError:
        return []
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
]


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
                   "also_listed_as": c["also_listed_as"]}
            row.update({k: s[k] for k in CSV_FIELDS if k in s})
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
        {subject, number, title, also_listed_as,
         campus_enrolled, campus_capacity, online_enrolled, online_capacity}
    A side's Enr/Cap is None when the course has NO such section (so the CLI can
    print "—"), versus 0/N when a section exists but is empty. Sections with an
    unparseable Avail. cell are skipped, matching the course-total convention in
    _parse_results().

    Caveat for cross-listed courses: a shared online section is reported under
    every subject code it carries (see `also_listed_as`), so summing the same
    course across subjects double-counts it — the per-subject rollup does not.
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
            "campus_enrolled": cam[0] if cam[2] else None,
            "campus_capacity": cam[1] if cam[2] else None,
            "online_enrolled": onl[0] if onl[2] else None,
            "online_capacity": onl[1] if onl[2] else None,
        })
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_courses(courses, strm):
    lines = [f"NC State Class Search — {term_label(strm)} ({strm})",
             f"Pulled {date.today().isoformat()}  ·  Avail = seats available / "
             f"capacity; Enr = enrolled (capacity - available)",
             "SYL = published syllabus in Class Search; NO-SYL = none published", ""]
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
            when = " ".join(x for x in (s["days"], s["time"]) if x) or "TBD"
            mode = "Online" if s["mode"] == "online" else "In-person"
            instr = s["instructor"] or "—"
            syl = "SYL" if s["syllabus"] else "NO-SYL"
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
    # Same reason as the per-course rollup: a 0/0 total for a term that publishes
    # no Avail. column would read as "nobody enrolled".
    totals = (f"TOTAL Avail {tot_a}/{tot_c} · Enrolled {tot_e}" if tot_c
              else "enrollment not published for this term")
    lines.append(f"{len(courses)} courses · {tot_s} sections · {totals} · "
                 f"Syllabi {tot_syl}/{tot_s}")
    return "\n".join(lines)


def _fmt_summary(courses, strm):
    """Per-course table: on-campus vs online Enr/Cap (the 'by mode' rollup)."""
    rows = summarize_by_mode(courses)

    def ec(e, c):
        return f"{e}/{c}" if e is not None else "—"

    codes = [f"{r['subject']} {r['number']}" for r in rows]
    titles = [r["title"] for r in rows]
    campus = [ec(r["campus_enrolled"], r["campus_capacity"]) for r in rows]
    online = [ec(r["online_enrolled"], r["online_capacity"]) for r in rows]
    xlist = [r["also_listed_as"] or "—" for r in rows]

    ce = sum(r["campus_enrolled"] or 0 for r in rows)
    cc = sum(r["campus_capacity"] or 0 for r in rows)
    oe = sum(r["online_enrolled"] or 0 for r in rows)
    oc = sum(r["online_capacity"] or 0 for r in rows)
    campus_tot, online_tot = f"{ce}/{cc}", f"{oe}/{oc}"

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
                    "default = newest term offered")
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

    try:
        if args.list_terms:
            for t in list_terms(timeout=args.timeout):
                print(f"{t['code']}  {t['label']}")
            return 0

        strm = resolve_term(args.term) if args.term else None
        if strm is None:
            terms = list_terms(timeout=args.timeout)
            if not terms:
                print("error: could not determine a default term; pass --term",
                      file=sys.stderr)
                return 1
            strm = terms[0]["code"]

        if args.list_subjects:
            for s in list_subjects(strm, timeout=args.timeout):
                print(f"{s['code']:<5} {s['name']}")
            return 0

        if not args.subject:
            ap.error("subject is required (e.g. EM) unless using --list-terms")

        courses = search_classes(
            strm, args.subject, course_number=args.number, course_inequality=args.ineq,
            career=args.career, instructor=args.instructor, mode=args.mode,
            distance_ed=args.distance_ed,
            open_only=args.open_only, timeout=args.timeout,
        )
    except (ClassSearchError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
