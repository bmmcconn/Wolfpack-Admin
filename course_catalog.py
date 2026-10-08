#!/usr/bin/env python3
"""course_catalog.py — query the NC State **Course Catalog** for course descriptions,
requisites and typical offering terms.

Part of Wolfpack-Admin - https://github.com/bmmcconn/Wolfpack-Admin (MIT License).
UNOFFICIAL: not an NC State product or service. Queries the same public Course
Catalog endpoint that go.ncsu.edu/course_catalog uses; please be considerate - a
search sends one or two POSTs (a lookup across subjects sends one per subject, at
most 4 at once) and retries only on network errors and 5xx server errors.

The Course Catalog (go.ncsu.edu/course_catalog → coursecat/directory.php) is the
registrar's TERM-AGNOSTIC directory of courses: title, credit hours, description,
requisite text, "Offered in ..." and GEP attributes, cross-listings, and the terms
in which the course currently has sections on the schedule. This is DISTINCT from
Class Search (go.ncsu.edu/class_search; see class_search.py), which lists one
term's sections with live enrollment, for the courses offered that term. Class
Search's results also show each course's description and requisite text (the same
as this directory's for all 61 ISE Fall 2026 courses, 2026-10-07; class_search.py
keeps them), and its section notes can add section-specific requisites
and seat reserves (e.g. ISE 495-002 "Prerequisites: ISE 361 and ISE 362 and
ST 372").

Under the hood the directory page POSTs to coursecat/directory_search.php, which
returns JSON: {"html": <link list>, "courses": {"NE-504": {...}, ...},
"json": {"inputs": ...}}. This module sends that request and normalizes the
`courses` map into a list of course dicts. The three search types match the page:
by subject, by keyword, or by General Education Program (GEP) category.

Public API:
    search_catalog(subject=None, *, keyword=None, gep=None, match_any=False,
                   career=None, number=None, inequality="=") -> list[course dict]
    get_courses(["NE 504", "MAE 308"]) -> (found course dicts,
                                           not found: [{"code", "reason"}])
    parse_course_code("NE 504") -> ("NE", "504")
    list_subjects() -> [{"code","name"}]     # every subject in the catalog
    list_geps() -> [{"code","name"}]         # GEP categories for gep=
    flatten_courses(courses, pulled, not_found) -> flat dicts, one per row (CSV)

Each course dict:
    {subject, number, title, units, units_min, units_max, requisites, description,
     typically_offered, gep, attributes, scheduled_terms:[{code,label}],
     also_listed_as, same_course_as, department, dept_link, course_id, offer_number}

`requisites` is the registrar's requisite TEXT for that offering, verbatim ("" when
none). It is free text, not a parsed rule: "Prerequisite: NE 401 or NE 520",
"P: MA 341", "Restriction: Instructor approval required" all occur.

⚠️ THE TWO NC STATE CATALOGS CAN DISAGREE ON REQUISITES. The University Catalog
(catalog.ncsu.edu/course-descriptions/<prefix>/) prints a dual-listed course under
each of its numbers with ONE shared text: the primary offering's (`offer_number`
1). That is usually the 400-level offering, but not always -- its ISE 425 entry
shows ISE 525's graduate prerequisites ("ISE/OR 505 ... ISE 560"), while this
directory gives ISE 425 its own ("P: ISE 361 and ISE 362"). The other offering's
own text exists only here. For NE on 2026-10-07 the substantive differences were
all graduate halves of dual pairs (NE 501, 510, 532, 570, 590): NE 501 here is
"Prerequisites: NE 520, MA 401, and CSC 112", the University Catalog's "MA 401 and
C- or better in NE 301". Say which source you quote. For a graduate student the
graduate offering's text here is the more specific guide, and the department can
waive either. The directory can also list courses the University Catalog doesn't
have yet (ISE 418/518, MAE 414/514/523 on 2026-10-07).

`typically_offered` collects the "Offered in ...", "YEAR: ..." and "TERM: ..."
attributes (e.g. "Offered in Fall Only; YEAR: Offered Alternate Years"); a TERM:
attribute can contradict the plain one, and both are shown when it does. `gep`
collects the "GEP: ..." ones; `attributes` keeps all of them raw. `scheduled_terms`
lists the terms in which the course currently has sections on the schedule (the
page's "future course meetings"); [] means none are scheduled now, not that the
course is dead. Use class_search.py for the sections themselves.

`also_listed_as` is the registrar's cross-listing, e.g. NE 577 -> "MAE 577".
`same_course_as` lists the OTHER numbers of the same course that the registrar
doesn't cross-list: offerings sharing this course's `course_id`, minus those in
`also_listed_as`. That is how a 400/500 DUAL listing shows up (NE 401 and NE 501
are course 016171, offerings 1 and 2). It is computed from the results fetched, so
a subject search finds it -- with a career filter this module also fetches the
unfiltered subject, because the server's career filter drops the other half --
but a keyword or GEP search can miss it.

Keyword search (checked 2026-10-07): the default looks for the keyword as ONE
PHRASE, in order -- a case-insensitive substring -- in course DESCRIPTIONS ONLY.
Titles are not searched ("reactor" misses NE 502 Reactor Engineering), "reactor
safety" finds nothing although ten descriptions contain both words, and "reactor"
also matches "bioreactor". The registrar's page calls this mode "All of these
words"; it isn't. match_any=True (--any) finds descriptions containing ANY of the
words, again ignoring titles. The server HTML-escapes the value, so & < > " can
never match; in --any mode it refuses any character other than letters, digits
and spaces. Both are rejected here before sending.

Server-side filters: `career` is applied by the server (verified 2026-10-07: NE
returns 108 courses for all careers, 71 for GRAD). The page also sends a
`course-number`, but it is NOT a server filter (108 either way; the page only uses
it to pop open one course), so `number`/`inequality` are applied here, after
being checked before any request. Subject codes must be UPPERCASE ("em" returns
nothing); this module uppercases them.

Failure posture: an unknown subject or GEP (both come back from the server as a
silent empty result), a blank search, the server's bare `{}` refusal, a non-JSON
or error response, a link list with no parseable courses, and network errors
(including the connection the server drops ~30 s into a search that is too
broad) all raise CourseCatalogError, never a silent empty list. A search that
matches nothing returns [], which is a real answer. In get_courses() an unknown
subject doesn't stop the batch: its codes come back in not_found.

Speed: the server's think time dominates (~0.33 s a request plus ~2.7 ms a course;
measured 2026-10-07), so lookups across several subjects fetch them concurrently,
at most MAX_PARALLEL at once, over one shared SSL context. A three-subject lookup
went from 2.6 s to 1.1 s.

CLI:
    course_catalog.py NE 504                         # one course (quotes optional)
    course_catalog.py NE 501 504 MAE 308 MA401       # several, any subjects
    course_catalog.py "NE 504, MAE 308"              # a pasted list works too
    course_catalog.py NE --number 500,502,504        # one subject, listed numbers
    course_catalog.py NE --career graduate --number 500-599 --brief
    course_catalog.py NE --number 520 --ineq "<="
    course_catalog.py --keyword "nuclear reactor" --career graduate   # a phrase
    course_catalog.py --keyword "reactor safety" --any
    course_catalog.py --gep HUM --brief
    course_catalog.py NE 504 --descr                 # add the description
    course_catalog.py NE --json   |   NE --csv      # structured / flat
    course_catalog.py --list-subjects   |   --list-geps
PowerShell: quote inequality args (`--ineq "<="`): bare < / > are redirection. A
range (`--number 500-599`) needs no quotes.

Stdlib only (no third-party dependencies). Read-only network POSTs; writes nothing.
"""

import argparse
import csv
import html
import http.client
import json
import re
import ssl
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

BASE = "https://webappprd.acs.ncsu.edu/php/coursecat"
SEARCH_URL = f"{BASE}/directory_search.php"
SUBJECTS_URL = f"{BASE}/subjects.php"
USER_AGENT = "Mozilla/5.0 (course_catalog.py; NC State internal catalog query)"
# Most requests in flight at once. It's a university production server, and it
# slowed each request by only ~15-20% with three in flight (2026-10-07).
MAX_PARALLEL = 4

# Copied from class_search.py (each tool here is one stdlib-only file, so they
# copy shared code rather than import it), so keep the two in sync.
CAREER_CODES = {
    "undergraduate": "UGRD", "ugrd": "UGRD", "graduate": "GRAD", "grad": "GRAD",
    "veterinary": "VETM", "vetm": "VETM", "agricultural": "AGI", "agi": "AGI",
}
CAREER_LABELS = {"UGRD": "Undergraduate", "GRAD": "Graduate",
                 "VETM": "Veterinary Medicine", "AGI": "Agricultural Institute"}
# "NE 504", "NE504", "NE-504", "ne 504", "NE 295A". Subjects run to FIVE letters:
# USDEI (U.S. Diversity Equity and Inclusion) is in the subject list, though the
# server returns no courses for it and the University Catalog has no USDEI page
# (2026-10-07). [0-9], not \d, so Unicode digits don't pass for course numbers.
COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]{1,5})\s*-?\s*([0-9]{3}[A-Za-z]?)\s*$")
SUBJECT_RE = re.compile(r"^[A-Za-z]{1,5}$")
NUMBER_RE = re.compile(r"^[0-9]{3}[A-Za-z]?$")
NUMBER_SPEC_RE = re.compile(r"^([0-9]{3}[A-Za-z]?)(?:-([0-9]{3}[A-Za-z]?))?$")
OFFERED_PREFIXES = ("Offered", "YEAR:", "TERM:")


class CourseCatalogError(RuntimeError):
    """Raised when the Course Catalog endpoint returns an error or bad response."""


class UnknownCodeError(CourseCatalogError):
    """An unknown subject or GEP code. get_courses() reports these in not_found
    instead of stopping the whole batch."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_OPENER = None
_OPENER_LOCK = threading.Lock()


def _opener():
    """One urllib opener, with ONE SSL context, shared by every request.

    A context costs ~15 ms to build, and threads that each build their own wait on
    one another (55 ms vs 24 ms to the first request with three threads, measured
    2026-10-07).
    """
    global _OPENER
    with _OPENER_LOCK:
        if _OPENER is None:
            _OPENER = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        return _OPENER


def _http(url, data, timeout=30, retries=2):
    """POST `data` (dict) and return the decoded body text.

    Adapted from class_search.py's _http, which this file copies rather than
    imports (see CAREER_CODES). This copy adds the shared SSL context, and
    doesn't retry a dropped connection (below); class_search.py retries one like
    any other transient error.

    Transient failures (connect/read timeouts, connection errors, HTTP 5xx) are
    retried up to `retries` times with a short backoff (0.5s, 1.5s). Other HTTP
    errors raise immediately, with the response body (truncated) for diagnosis.
    """
    body = urllib.parse.urlencode(data).encode()
    last = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(0.5 * (3 ** (attempt - 1)))
        req = urllib.request.Request(url, data=body,
                                     headers={"User-Agent": USER_AGENT})
        try:
            with _opener().open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            snippet = ""
            try:
                snippet = _clean(e.read(2000).decode("utf-8", "replace"))[:200]
            except OSError:
                pass
            msg = f"HTTP {e.code} from {url}" + (f": {snippet}" if snippet else "")
            if e.code not in (500, 502, 503, 504):
                raise CourseCatalogError(msg) from e
            last = CourseCatalogError(msg)
        except http.client.IncompleteRead as e:
            # The server answers 200 with chunked headers, then drops the connection
            # ~30 s into a search that is too broad (a blank or very common
            # keyword; 2026-10-07). Not retried: a retry re-runs the same 30 s query.
            raise CourseCatalogError(
                f"{url} closed the connection after {len(e.partial)} bytes -- it "
                "does this about 30 s into a search that is too broad (e.g. a very "
                "common word); narrow the search") from e
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as e:
            # NB: a read-timeout mid-body raises TimeoutError, NOT URLError, and
            # http.client's own errors are not OSErrors.
            last = CourseCatalogError(f"request to {url} failed: {e!r}")
    raise last


def _parallel(fn, items):
    """fn(item) for each item, at most MAX_PARALLEL at once; results in input order.

    Exceptions propagate as from a plain loop: the first failure in input order.
    """
    items = list(items)
    if len(items) < 2:
        return [fn(x) for x in items]
    from concurrent.futures import ThreadPoolExecutor  # ~5 ms; only when needed
    _opener()  # build the shared SSL context before the threads race to build it
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(items))) as ex:
        return list(ex.map(fn, items))


def _post_json(url, data, timeout):
    raw = _http(url, data, timeout=timeout)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CourseCatalogError(f"non-JSON response from {url}: {e}") from e
    if not isinstance(payload, dict):
        raise CourseCatalogError(
            f"unexpected response shape from {url}: {type(payload).__name__}")
    if payload.get("error"):
        raise CourseCatalogError(_clean(str(payload["error"])) or "search returned an error")
    return payload


_SUBJECTS = None
_SUBJECTS_LOCK = threading.Lock()


def _subjects_payload(timeout):
    """subjects.php, fetched once per process.

    It feeds list_subjects(), list_geps() and the unknown-subject check, which can
    run in several threads at once; the lock makes the others wait and reuse it.
    """
    global _SUBJECTS
    with _SUBJECTS_LOCK:
        if _SUBJECTS is None:
            _SUBJECTS = _post_json(SUBJECTS_URL, {"strm": "all"}, timeout)
        return _SUBJECTS


def _clean(fragment):
    """Strip tags + unescape entities + collapse whitespace. For HTML only."""
    text = re.sub(r"<[^>]+>", " ", str(fragment))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _text(value):
    """A plain-text field, whitespace collapsed ("" for None).

    NOT _clean(): titles, requisites and descriptions are plain text (the page
    inserts them with jQuery .text()), and stripping "tags" deletes real text --
    ECE 533's "[<=48V] and high voltage [>10kV]" came out as "[ 10kV]".
    """
    return "" if value is None else re.sub(r"\s+", " ", str(value)).strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _code(course):
    return f"{course['subject']} {course['number']}"


def _units(lo, hi):
    lo, hi = _text(lo), _text(hi)
    return lo if lo == hi else f"{lo}-{hi}"


def _cross_listings(raw):
    """cross_crse is [] when empty, else {"cross-list-1": {subject, catalog_nbr}}.

    (A PHP empty array serializes as [] and a non-empty one as an object, which is
    why the page tests `.length` -- both shapes are normal.) catalog_nbr carries a
    leading space (" 577").
    """
    if not isinstance(raw, dict):
        return ""
    codes = []
    for item in raw.values():
        if isinstance(item, dict) and _text(item.get("subject")):
            code = f"{_text(item.get('subject'))} {_text(item.get('catalog_nbr'))}"
            if code not in codes:
                codes.append(code)
    return ", ".join(codes)


def _scheduled_terms(raw):
    """["2268|2026 Fall Term", ...] -> [{"code": "2268", "label": "2026 Fall Term"}].

    Sorted by term code, which is chronological (2 + year + season digit; see
    class_search.py). The server's own order isn't: it put "2027 Summer Term 1"
    before "2027 Spring Term" (MA 401, 2026-10-07).
    """
    out = []
    for item in raw or []:
        code, _, label = str(item).partition("|")
        out.append({"code": code.strip(), "label": label.strip() or code.strip()})
    return sorted(out, key=lambda t: t["code"])


def _parse_course(rec):
    # attrs are HTML (the page inserts them with .html()); the rest is plain text.
    attrs = [_clean(a) for a in rec.get("attrs") or [] if _clean(a)]
    return {
        "subject": _text(rec.get("subject")),
        "number": _text(rec.get("catalog_number")),
        "title": _text(rec.get("course_title")),
        "units": _units(rec.get("units_min"), rec.get("units_max")),
        "units_min": _text(rec.get("units_min")),
        "units_max": _text(rec.get("units_max")),
        "requisites": _text(rec.get("reqs")),
        "description": _text(rec.get("descr")),
        "typically_offered": "; ".join(a for a in attrs if a.startswith(OFFERED_PREFIXES)),
        "gep": "; ".join(a[len("GEP:"):].strip() for a in attrs if a.startswith("GEP:")),
        "attributes": attrs,
        "scheduled_terms": _scheduled_terms(rec.get("semesters")),
        "also_listed_as": _cross_listings(rec.get("cross_crse")),
        "same_course_as": "",
        "department": _text(rec.get("descr_formal")),
        "dept_link": _text(rec.get("dept_link")),
        "course_id": _text(rec.get("course_id")),
        "offer_number": _text(rec.get("offer_number")),
    }


def _parse_results(payload):
    """Turn a directory_search.php payload into a list of course dicts."""
    if "json" not in payload:
        # A real "no results" still echoes the inputs: {"html": "", "json": {...}}.
        # A bare {} is the server refusing the search (it does this for
        # punctuation in an --any keyword), so it must not read as "0 courses".
        raise CourseCatalogError(
            "the Course Catalog returned an empty reply ({}) -- it refused the "
            "search rather than finding nothing")
    raw = payload.get("courses")
    html_str = payload.get("html") or ""
    if not raw:
        # No `courses` key is how the server says "no results". A link list
        # WITHOUT the map would mean the response format has changed.
        if "course-link" in str(html_str):
            raise CourseCatalogError(
                "results list has course links but no course data -- the Course "
                "Catalog response format may have changed; update _parse_results()")
        return []
    records = raw.values() if isinstance(raw, dict) else raw
    courses = [_parse_course(r) for r in records if isinstance(r, dict)]
    if not courses:
        raise CourseCatalogError("course data present but no course could be parsed")
    # Offerings that share a course_id are one course listed under several numbers:
    # a cross-listing, which the registrar names in also_listed_as, or a 400/500
    # dual listing, which it doesn't. Record the ones it doesn't name.
    by_id = {}
    for c in courses:
        if c["course_id"]:
            by_id.setdefault(c["course_id"], []).append(_code(c))
    for c in courses:
        listed = {x.strip() for x in c["also_listed_as"].split(",") if x.strip()}
        c["same_course_as"] = ", ".join(
            x for x in by_id.get(c["course_id"], []) if x != _code(c) and x not in listed)
    return courses


def _number_key(number):
    m = re.match(r"[0-9]+", number or "")
    return int(m.group(0)) if m else -1


def _number_test(number, inequality):
    """Build the course-number test the server won't apply (None = no filter).

    Checked BEFORE any request, so bad input fails fast instead of quietly matching
    nothing (or everything). With "=", `number` is one or more numbers or ranges,
    separated by commas or spaces, or a list: "504", "500,504", "500-599", "295A".
    "<=" / ">=" take a single number and compare its digits.
    """
    if inequality not in ("=", "<=", ">="):
        raise ValueError(f"inequality must be '=', '<=' or '>=', got {inequality!r}")
    if number is None:
        return None
    raw = list(number) if isinstance(number, (list, tuple)) else \
        re.split(r"[,;\s]+", str(number))
    parts = [str(t).strip() for t in raw if str(t).strip()]
    if not parts:
        return None
    spans = []
    for t in parts:
        m = NUMBER_SPEC_RE.match(t.upper())
        if not m:
            raise ValueError(
                "course number must be 3 digits with an optional letter (504, 295A) "
                f"or a range (500-599), got {t!r}")
        lo, hi = m.group(1), m.group(2)
        if hi and _number_key(lo) > _number_key(hi):
            raise ValueError(f"range {t!r} runs backwards")
        spans.append((lo, hi))
    if inequality != "=":
        if len(spans) != 1 or spans[0][1]:
            raise ValueError(f"inequality {inequality!r} takes one number; use '=' for "
                             "a list or a range")
        limit = _number_key(spans[0][0])
        if inequality == "<=":
            return lambda n: 0 <= _number_key(n) <= limit
        return lambda n: _number_key(n) >= limit
    exact = {lo for lo, hi in spans if not hi}
    ranges = [(_number_key(lo), _number_key(hi)) for lo, hi in spans if hi]
    return lambda n: (n.upper() in exact
                      or any(a <= _number_key(n) <= b for a, b in ranges))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_subjects(timeout=30):
    """Return [{'code','name'}] for every subject in the catalog (subjects.php)."""
    subs = _subjects_payload(timeout).get("subj_js")
    try:
        items = json.loads(subs) if isinstance(subs, str) else (subs or [])
    except json.JSONDecodeError:
        items = []
    out = []
    for s in items:
        m = re.match(r"\s*([A-Z]{1,5})\s*-\s*(.*)", str(s))
        if m:
            out.append({"code": m.group(1), "name": m.group(2).strip()})
    if not out:
        raise CourseCatalogError("could not read the subject list from subjects.php")
    return out


def list_geps(timeout=30):
    """Return [{'code','name'}] for the GEP categories the gep= search accepts."""
    out = [{"code": v, "name": html.unescape(t).strip()}
           for v, t in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]*)</option>',
                                  str(_subjects_payload(timeout).get("gep") or ""))]
    if not out:
        raise CourseCatalogError("could not read the GEP list from subjects.php")
    return out


def search_catalog(subject=None, *, keyword=None, gep=None, match_any=False,
                   career=None, number=None, inequality="=", timeout=30):
    """Search the Course Catalog and return a list of course dicts.

    Exactly one of:
      subject : subject prefix, e.g. "NE", "MAE" (any case).
      keyword : a PHRASE to find in course descriptions (case-insensitive
                substring; titles are not searched), or with match_any=True,
                descriptions containing ANY of its words. See the module docstring.
      gep     : GEP category code, e.g. "HUM" (see list_geps()).
    career  : None (all) | "undergraduate" | "graduate" | "veterinary" | "agricultural".
    number + inequality ("=", "<=", ">="): course-number filter, applied here (the
              server ignores it) and checked before any request. With "=", number
              may be a list or a range ("500,504", "500-599").
    """
    given = {k: v for k, v in (("subject", subject), ("keyword", keyword),
                                ("gep", gep)) if v is not None}
    if len(given) != 1:
        raise ValueError("give exactly one of subject, keyword or gep")
    (kind, raw_value), = given.items()
    value = re.sub(r"\s+", " ", str(raw_value)).strip()
    if not value:
        # A blank search makes the server scan everything and drop the connection
        # after ~30 s; the registrar's own page refuses it too.
        raise ValueError(f"{kind} is blank")
    test = _number_test(number, inequality)

    career_code = ""
    if career:
        key = str(career).strip().lower()
        if key not in CAREER_CODES:
            raise ValueError(
                f"unknown career {career!r}; use one of {sorted(set(CAREER_CODES))}")
        career_code = CAREER_CODES[key]

    if kind == "subject":
        value = value.upper()
        if not SUBJECT_RE.fullmatch(value):
            raise ValueError(f"subject must be 1-5 letters, got {raw_value!r}")
        params = {"type": "subject", "search_val": value}
    elif kind == "keyword":
        if match_any:
            if re.search(r"[^A-Za-z0-9 ]", value):
                raise ValueError(
                    "an --any keyword search takes letters, digits and spaces only; "
                    f"the Course Catalog refuses anything else (got {value!r})")
        elif re.search(r'[&<>"]', value):
            raise ValueError(
                "the Course Catalog can't search for & < > or \" (it escapes them, "
                f"so they never match); leave them out (got {value!r})")
        params = {"type": "keyword", "search_val": value,
                  "keyword-type": "keyword_any" if match_any else "keyword_all"}
    else:
        value = value.upper()
        params = {"type": "gep", "search_val": value}
    params["career"] = career_code

    if kind == "subject" and career_code:
        # The server's career filter also drops the other half of a dual listing
        # (GRAD loses NE 401, so NE 501's sibling vanishes). Fetch the unfiltered
        # subject alongside, and take the siblings from it.
        payloads = _parallel(lambda p: _post_json(SEARCH_URL, p, timeout),
                             [params, dict(params, career="")])
        courses, everything = _parse_results(payloads[0]), _parse_results(payloads[1])
        siblings = {_code(c): c["same_course_as"] for c in everything}
        for c in courses:
            c["same_course_as"] = siblings.get(_code(c), c["same_course_as"])
    else:
        courses = everything = _parse_results(_post_json(SEARCH_URL, params, timeout))

    # An unknown subject or GEP comes back as a clean "no results", which reads
    # exactly like a real empty answer -- so check the code before believing it.
    if not everything and kind == "subject":
        if value not in {s["code"] for s in list_subjects(timeout=timeout)}:
            raise UnknownCodeError(
                f"subject {value!r} is not in the Course Catalog -- unknown or mistyped")
    if not everything and kind == "gep":
        if value not in {g["code"] for g in list_geps(timeout=timeout)}:
            raise UnknownCodeError(
                f"GEP {value!r} is not a GEP category; see --list-geps")
    return [c for c in courses if test(c["number"])] if test else courses


def parse_course_code(code):
    """'NE 504' / 'ne504' / 'NE-504' -> ('NE', '504'); None if it isn't a code."""
    m = COURSE_CODE_RE.match(str(code))
    return (m.group(1).upper(), m.group(2).upper()) if m else None


def get_courses(codes, timeout=30):
    """Look up specific courses, e.g. ["NE 504", "MAE 308"].

    Returns (courses, not_found): the courses in the order asked (duplicates
    merged), and [{"code", "reason"}] for the rest. The reason is "not in the
    Course Catalog" (no longer offered, or a mistyped number) or "unknown subject
    XYZ"; an unknown subject doesn't stop the batch. One request per distinct
    subject, run concurrently.
    """
    parsed = []
    for code in codes:
        pc = parse_course_code(code)
        if not pc:
            raise ValueError(f"not a course code: {code!r} (expected e.g. 'NE 504')")
        parsed.append(pc)
    subjects = list(dict.fromkeys(s for s, _ in parsed))

    def fetch(subj):
        try:
            return {c["number"].upper(): c for c in search_catalog(subj, timeout=timeout)}
        except UnknownCodeError:
            return None

    by_subject = dict(zip(subjects, _parallel(fetch, subjects)))
    found, not_found, seen = [], [], set()
    for subj, num in parsed:
        code = f"{subj} {num}"
        if code in seen:
            continue
        seen.add(code)
        table = by_subject[subj]
        if table is None:
            not_found.append({"code": code, "reason": f"unknown subject {subj}"})
        elif num in table:
            found.append(table[num])
        else:
            not_found.append({"code": code, "reason": "not in the Course Catalog"})
    return found, not_found


CSV_FIELDS = [
    "pulled", "subject", "number", "status", "title", "units", "requisites",
    "typically_offered", "gep", "scheduled_terms", "also_listed_as",
    "same_course_as", "department", "course_id", "offer_number", "description",
]


def flatten_courses(courses, pulled="", not_found=()):
    """One flat dict per row, column order = CSV_FIELDS (lists joined by '; ').

    `status` is "found" for a course, or the not_found reason for a code the
    catalog doesn't have, so a saved CSV keeps that answer too.
    """
    rows = []
    for c in courses:
        row = {k: c.get(k, "") for k in CSV_FIELDS}
        row["pulled"] = pulled
        row["status"] = "found"
        row["scheduled_terms"] = "; ".join(t["label"] for t in c["scheduled_terms"])
        rows.append(row)
    for item in not_found:
        subj, _, num = item["code"].partition(" ")
        row = dict.fromkeys(CSV_FIELDS, "")
        row.update(pulled=pulled, subject=subj, number=num, status=item["reason"])
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_query(args):
    """Read the positional arguments as course codes and/or a subject to browse.

    Tokens split on spaces, commas, semicolons and hyphens, so all of these work:
    NE 504 · "NE 504" · NE504 · NE-504 · "NE 504, MAE 308" · NE 501 504 MAE 308.
    A subject's numbers follow it; a subject with no number after it is one to
    browse. Returns (codes like "NE 504", subjects to browse).
    """
    codes, browse = [], []
    subject, numbered = None, True
    for tok in (t for a in args for t in re.split(r"[\s,;\-]+", a) if t):
        glued = re.fullmatch(r"([A-Za-z]{1,5})([0-9]{3}[A-Za-z]?)", tok)
        if glued:                                   # NE504
            if not numbered:
                browse.append(subject)
            subject, numbered = glued.group(1).upper(), True
            codes.append(f"{subject} {glued.group(2).upper()}")
        elif SUBJECT_RE.fullmatch(tok):             # NE
            if not numbered:
                browse.append(subject)
            subject, numbered = tok.upper(), False
        elif NUMBER_RE.fullmatch(tok):              # 504, after a subject
            if subject is None:
                raise ValueError(f"course number {tok} has no subject before it "
                                 "(e.g. NE 504)")
            codes.append(f"{subject} {tok.upper()}")
            numbered = True
        else:
            raise ValueError(f"can't read {tok!r} as a subject or a course code")
    if not numbered:
        browse.append(subject)
    return codes, browse


def _wrap(label, text, width=100):
    prefix = f"    {label:<15}: "
    return textwrap.fill(text, width=width, initial_indent=prefix,
                         subsequent_indent=" " * len(prefix))


def _other_numbers(course):
    """Every other number the course is listed under (cross- and dual-listings)."""
    out = []
    for field in (course["also_listed_as"], course["same_course_as"]):
        for x in field.split(","):
            x = x.strip()
            if x and x not in out:
                out.append(x)
    return ", ".join(out)


def _fmt_not_found(item):
    if item["reason"].startswith("unknown subject"):
        return (f"{item['code']}  -- UNKNOWN SUBJECT {item['code'].split()[0]} "
                "(mistyped?)")
    return f"{item['code']}  -- NOT IN THE COURSE CATALOG (no longer offered, or mistyped)"


def _fmt_courses(courses, heading, not_found=(), descr=False, brief=False):
    lines = [heading,
             f"Pulled {date.today().isoformat()}  ·  source: registrar Course Catalog "
             f"(go.ncsu.edu/course_catalog)", ""]
    for c in courses:
        code = _code(c)
        if brief:
            others = _other_numbers(c)
            parts = [f"{code:<9} {c['title']} ({c['units']} cr)"
                     + (f" (= {others})" if others else ""),
                     c["requisites"] or "no requisites listed"]
            if c["typically_offered"]:
                parts.append(c["typically_offered"])
            terms = c["scheduled_terms"]
            if terms:
                more = f" +{len(terms) - 1}" if len(terms) > 1 else ""
                parts.append(f"scheduled: {terms[0]['label']}{more}")
            else:
                parts.append("not scheduled")
            lines.append(" | ".join(parts))
            if descr and c["description"]:
                lines.append(textwrap.fill(c["description"], width=100,
                                           initial_indent=" " * 10,
                                           subsequent_indent=" " * 10))
            continue
        lines.append(f"{code}  {c['title']} · {c['units']} cr")
        lines.append(_wrap("Requisites", c["requisites"] or "none listed"))
        lines.append(_wrap("Offered", c["typically_offered"] or "not stated"))
        sched = ", ".join(t["label"] for t in c["scheduled_terms"])
        lines.append(_wrap("Scheduled", sched or "no sections currently scheduled"))
        if c["also_listed_as"]:
            lines.append(_wrap("Also listed as", c["also_listed_as"]))
        if c["same_course_as"]:
            lines.append(_wrap("Same course as", c["same_course_as"]))
        if c["gep"]:
            lines.append(_wrap("GEP", c["gep"]))
        if descr and c["description"]:
            lines.append(_wrap("Description", c["description"]))
        lines.append("")
    if brief:
        lines.append("")
    for item in not_found:
        lines.append(_fmt_not_found(item))
    if not_found:
        lines.append("")
    lines.append(f"{len(courses)} course(s)" +
                 (f" · {len(not_found)} not found" if not_found else ""))
    return "\n".join(lines)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(
        description="Query the NC State Course Catalog (go.ncsu.edu/course_catalog) "
                    "for titles, credit hours, requisites, typical terms and "
                    "descriptions.")
    ap.add_argument("query", nargs="*",
                    help="a subject to browse (NE), or course codes: NE 504, NE504, "
                         "NE-504, 'NE 501 504 MAE 308'")
    ap.add_argument("--keyword",
                    help="find a PHRASE in course descriptions (exact, case-insensitive; "
                         "titles aren't searched)")
    ap.add_argument("--any", action="store_true",
                    help="with --keyword: find descriptions containing ANY of the words")
    ap.add_argument("--gep", help="GEP category code, e.g. HUM (see --list-geps)")
    ap.add_argument("--career", help="undergraduate | graduate | veterinary | agricultural")
    ap.add_argument("--number",
                    help="course numbers to keep: 504, a list 500,504, or a range "
                         "500-599 (with a subject, keyword or GEP search)")
    ap.add_argument("--ineq", default="=", choices=["=", "<=", ">="],
                    help="course-number comparison (default '=')")
    ap.add_argument("--descr", action="store_true",
                    help="include course descriptions (also with --brief)")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--brief", action="store_true", help="one line per course")
    fmt.add_argument("--json", action="store_true", help="structured JSON output")
    fmt.add_argument("--csv", action="store_true", help="flat CSV, one row per course")
    ap.add_argument("--list-subjects", action="store_true",
                    help="print every subject code and exit")
    ap.add_argument("--list-geps", action="store_true",
                    help="print the GEP category codes and exit")
    ap.add_argument("--timeout", type=int, default=30,
                    help="seconds to wait for each request (default 30)")
    args = ap.parse_args(argv)
    if args.timeout <= 0:
        ap.error("--timeout must be a positive number of seconds")

    not_found = []
    try:
        if args.list_subjects:
            for s in list_subjects(timeout=args.timeout):
                print(f"{s['code']:<5} {s['name']}")
            return 0
        if args.list_geps:
            for g in list_geps(timeout=args.timeout):
                print(f"{g['code']:<10} {g['name']}")
            return 0

        try:
            codes, subjects = _parse_query(args.query)
        except ValueError as e:
            ap.error(str(e))
        modes = sum(bool(x) for x in (codes or subjects, args.keyword is not None,
                                       args.gep is not None))
        if modes != 1:
            ap.error("give one of: a subject, course code(s), --keyword or --gep")
        if codes and subjects:
            ap.error(f"{', '.join(subjects)} has no course number after it; give one "
                     "subject alone to browse it, or course codes")
        if len(subjects) > 1:
            ap.error("give one subject at a time to browse (or course codes, "
                     "e.g. NE 504)")
        if codes and (args.number or args.career):
            ap.error("--number and --career apply to a subject, keyword or GEP "
                     "search, not to course codes")
        if args.any and args.keyword is None:
            ap.error("--any goes with --keyword")

        career = CAREER_LABELS.get(
            CAREER_CODES.get((args.career or "").strip().lower(), ""), "")
        if codes:
            courses, not_found = get_courses(codes, timeout=args.timeout)
            search = {"type": "courses", "value": codes}
            heading = "NC State Course Catalog — " + ", ".join(codes)
        else:
            courses = search_catalog(
                subjects[0] if subjects else None, keyword=args.keyword, gep=args.gep,
                match_any=args.any, career=args.career, number=args.number,
                inequality=args.ineq, timeout=args.timeout)
            kind = "subject" if subjects else "keyword" if args.keyword is not None \
                else "gep"
            if kind == "keyword":
                value = re.sub(r"\s+", " ", args.keyword).strip()
                bits = [f"keyword {value!r}", "any word" if args.any else "phrase"]
            else:
                value = (subjects[0] if subjects else args.gep).strip().upper()
                bits = [f"{kind} {value}"]
            search = {"type": kind, "value": value, "career": career,
                      "number": args.number or "", "inequality": args.ineq}
            if career:
                bits.append(career)
            if args.number:
                bits.append(f"number {args.ineq} {args.number}")
            heading = "NC State Course Catalog — " + " · ".join(bits)
    except (CourseCatalogError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"search": search,
                          "pulled_at": datetime.now().isoformat(timespec="seconds"),
                          "courses": courses, "not_found": not_found}, indent=2))
    elif args.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(flatten_courses(courses, pulled=date.today().isoformat(),
                                    not_found=not_found))
    else:
        print(_fmt_courses(courses, heading, not_found, descr=args.descr,
                           brief=args.brief))
    return 0


if __name__ == "__main__":
    sys.exit(main())
