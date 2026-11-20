#!/usr/bin/env python3
"""postgrad_outcomes.py -- pull NC State Post-Graduate Employment (PGEM) outcomes for one or
more academic programs and print them as a clean table.

Part of Wolfpack-Admin - https://github.com/bmmcconn/Wolfpack-Admin (MIT License).
UNOFFICIAL: not an NC State product or service. Queries the same public PGEM
endpoints the site itself uses; please be considerate - a pull sends one POST per
program plus up to two small GETs, and retries only on network errors and 5xx
server errors.

Source: https://apps.oirp.ncsu.edu/pgem/index.cfm  (NC State University Data and
Analytics; Future Plans Survey / Survey of Recent Graduates). Public, no login.

All output is aggregate institutional data published by the university -- no
student-level records. Employer and job-title rows are respondent-entered,
uncleaned, and already public on the source site.

Usage:
  python postgrad_outcomes.py -p "Engineering Management"              # one program
  python postgrad_outcomes.py -p "Engineering Management" -p "Industrial Engineering-MR"
  python postgrad_outcomes.py -p 14SCEMMR                              # by plan code
  python postgrad_outcomes.py --college 14 --all                       # every plan in a college
  python postgrad_outcomes.py -p "Engineering Management" --detail     # + employers/job titles
  python postgrad_outcomes.py -p 14SCEMMR --titles                     # job titles only
  python postgrad_outcomes.py -p 14SCEMMR --titles --csv > titles.csv   # ...exportable
  python postgrad_outcomes.py --college 14 --all --titles              # titles, whole college
  python postgrad_outcomes.py --list                                   # list plan codes + names
  python postgrad_outcomes.py --list --college 14                      # ...for one college
  python postgrad_outcomes.py --level Doctoral -p "Operations Research"
  python postgrad_outcomes.py -p "Engineering Management" --csv > mem.csv
  python postgrad_outcomes.py -p "Engineering Management" --json

Options:
  -p, --program SPEC    Repeatable. Either an exact plan code (e.g. 14SCEMMR) or a
                        case-insensitive substring of the plan name. A substring
                        that matches several plans pulls ALL of them (the site has
                        genuine duplicate names under different codes) and says so.
  --level LEVEL         Seniors (bachelor's) | Masters | Doctoral.  Default: Masters
  --college ID          Two-char college ID; see --list-colleges. Used with --all,
                        and to narrow --list.
  --all                 Pull every plan in --college (requires --college)
  --detail              Also print employers/job titles and further-education rows
  --titles              Output ONLY the employer/job-title rows, one per respondent,
                        in long format (plan code, program, company, job title).
                        Unlike --detail this survives --csv/--json, so it is the
                        way to get job titles into a spreadsheet. Skips the
                        further-education request entirely.
  --with-college        Add the college-wide total as a comparison row
  --csv | --json        Machine-readable output instead of the table
  --list                List available plan codes and names for --level, then exit
  --list-colleges       List college IDs, then exit
  --timeout SECONDS     Seconds to wait for each reply (default 10; failures retry
                        twice, and a run stops after 2 plans in a row fail on
                        network errors)

Notes on the source, learned by inspecting the page (2026-08-10):
  * The summary filter is a POST form with fields studentView / collegeID /
    acadPlanID. Only studentView also responds to a query string -- putting
    collegeID or acadPlanID in the URL is silently ignored and you get the
    unfiltered view. That silent-ignore is why this tool always POSTs.
  * The two detail tables are separate GET JSON endpoints
    (action=ajaxOptions.employment / .furthered) and take collegeView, NOT
    collegeID. Same value, different parameter name.
  * The employment endpoint returns exactly two fields, COMPANY and JOBTITLE.
    There is no location, industry, or degree-relatedness field to be had --
    verified against the live endpoint 2026-08-11, so --titles is the complete
    job-title picture the site publishes, not a subset of it.
  * Unlike the summary GET, the employment endpoint DOES honor acadPlanID
    (14SCEMMR -> 19 rows, 14CEMR -> 8, blank -> 281 college-wide). Checked
    explicitly, because a silently-ignored filter here would hand back
    college-wide job titles wearing a single program's name.
  * Respondent counts line up with the summary's "Full Time Job" column
    (MEM: 19 and 19), which is a cheap sanity check on any pull.
  * A plan code begins with its college ID (14SCEMMR -> college 14), so the
    college is derived rather than asked for.
  * Salary cells read "*Data Unavailable" when the reporting count is too small
    to publish; those come back as None / empty rather than 0.

Failure posture (2026-11-20; each of these was tested by injecting the fault):
  * Columns are read by HEADER NAME, never by position. Values used to be read
    by position, so a column the site inserted would shift every later value
    without a word: with one inserted before "Avg. Starting Salary", MEM's
    average read "$7" and its median was really its mean. Now an inserted column
    is ignored (and named in a note), and a missing or renamed one is an error.
  * A plan that fails (network error, timeout, changed layout) no longer just
    vanishes from the output with exit code 0. The run finishes the other plans,
    then lists the failures and exits 1; --json carries them as entries with an
    "error" and no data, and the table names them under it.
  * The employer / further-education endpoints answer "[]" for a plan with no
    rows. An error page, non-JSON reply or network failure there used to come
    back as [], which printed "(no employment responses reported)". It now
    fails the plan instead.
  * Output is UTF-8: job titles are respondent-entered, and one character
    outside Windows' default code page ("≥") crashed a run whose output went to
    a file or a pipe.
  * Each reply gets DEFAULT_TIMEOUT (10 s; was 45 s with no retries, so one
    hiccup dropped a plan). Timeouts, connection errors and 5xx replies are
    retried twice; a host name that doesn't resolve isn't. A run stops after
    MAX_NETWORK_FAILURES (2) plans in a row fail on network errors, and lists
    the plans it didn't try, instead of spending ~32 s on each one left.

Output is aggregate institutional data -- no student-level records -- and is
safe to share. Job titles and program names in --detail are respondent-entered
and uncleaned, per the site's own note.
"""

import argparse
import csv
import html
import http.client
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://apps.oirp.ncsu.edu/pgem/index.cfm"
SUMMARY = BASE + "?action=main.summary"
UA = "Mozilla/5.0 (compatible; ncsu-pgem-cli/1.0)"
# Seconds to wait for each reply. Real requests answer in well under a second
# (2026-11-20: 0.1 to 0.4 s), so this was 45 s, with no retries, until then.
DEFAULT_TIMEOUT = 10
# Consecutive plans failing on network errors before a run stops trying: a
# server that has stopped answering would otherwise cost ~32 s per plan left.
MAX_NETWORK_FAILURES = 2
# --csv output starts with a UTF-8 byte-order mark. Output is UTF-8 (see "Failure
# posture"), and Excel opens a CSV without the mark in the Windows code page:
# "Engineer – HIG HBM" (a real COE job title) showed as "Engineer â€“ HIG HBM".
# Read the CSV in Python with encoding="utf-8-sig".
CSV_BOM = "﻿"

LEVELS = ("Seniors", "Masters", "Doctoral")

# The columns this tool reports, in output order. Each is found in the results
# table by its header (HEADER_KEYS), not by position: see "Failure posture".
COLUMNS = ["Graduates", "Respondents", "Response Rate", "Grad/Prof School",
           "Full Time Job", "Reporting Salary", "Avg Salary", "Median Salary"]

# Each column's <th> as the parser reads it (it joins a header's lines with no
# space: "Accepted<br>Full Time Job" -> "AcceptedFull Time Job"), lowercased with
# everything but letters and digits dropped. The Graduates header names the
# survey window ("December 2025 and May 2026 Graduates"), so it is matched on
# its ending instead.
HEADER_KEYS = {
    "Respondents": "surveyrespondents",
    "Response Rate": "responserate",
    "Grad/Prof School": "attendinggradprofschool",
    "Full Time Job": "acceptedfulltimejob",
    "Reporting Salary": "reportingsalary",
    "Avg Salary": "avgstartingsalary",
    "Median Salary": "medianstartingsalary",
}


class PgemError(RuntimeError):
    """The PGEM site answered with something this tool can't trust."""


class PgemNetworkError(PgemError):
    """The site didn't answer, even after retries."""


# --------------------------------------------------------------- http helpers
def _open(url, data=None, timeout=DEFAULT_TIMEOUT, retries=2):
    """GET (data=None) or POST and return the body text.

    Timeouts, connection errors and HTTP 5xx are retried `retries` times (after
    0.5 s, then 1.5 s); they then raise PgemNetworkError. A host name that
    doesn't resolve isn't retried (a retry can't fix it), and any other HTTP
    error raises PgemError at once.
    """
    last = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(0.5 * (3 ** (attempt - 1)))
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (500, 502, 503, 504):
                raise PgemError("HTTP %s from %s" % (e.code, url)) from e
            last = PgemNetworkError("HTTP %s from %s" % (e.code, url))
        except (OSError, http.client.HTTPException) as e:   # URLError, timeouts
            last = PgemNetworkError("request to %s failed: %s" % (url, e))
            if isinstance(getattr(e, "reason", None), socket.gaierror):
                raise last from e
    raise PgemNetworkError("%s (after %d tries, %d s each)" % (last, retries + 1, timeout))


def fetch_summary(level, college_id="99", plan_id="", timeout=DEFAULT_TIMEOUT):
    """POST the filter form and return the page HTML."""
    body = urllib.parse.urlencode({
        "studentView": level,
        "collegeID": college_id,
        "acadPlanID": plan_id,
        "btnFilter2": "Update Results",
    }).encode()
    return _open(SUMMARY, data=body, timeout=timeout)


def fetch_detail(kind, level, college_view, plan_id, timeout=DEFAULT_TIMEOUT):
    """GET one of the JSON detail endpoints -> list of row dicts.
    kind = employment | furthered.

    A plan with no rows comes back as "[]". Anything else that isn't a JSON list
    (an error page, a network failure) raises PgemError rather than reading as
    "none reported" (see "Failure posture").
    """
    q = urllib.parse.urlencode({
        "action": "ajaxOptions." + kind,
        "collegeView": college_view,
        "studentView": level,
        "acadPlanID": plan_id,
        "deptID": "",
    })
    body = _open(BASE + "?" + q, timeout=timeout)       # raises on network failure
    try:
        rows = json.loads(body or "[]")
    except ValueError as e:
        raise PgemError("the %s endpoint returned something other than JSON: %r"
                        % (kind, re.sub(r"\s+", " ", body)[:80])) from e
    if not isinstance(rows, list):
        raise PgemError("the %s endpoint returned a JSON %s, not a list"
                        % (kind, type(rows).__name__))
    return rows


# ------------------------------------------------------------------ html bits
class _Tables(HTMLParser):
    """Collect tables as {id: [[cell, ...], ...]}. Stdlib only, no bs4."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack, self._cur, self._row, self._cell = {}, [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._stack.append(self._cur)
            self._cur = {"id": a.get("id") or a.get("name") or "table%d" % len(self.tables),
                         "rows": []}
        elif tag == "tr" and self._cur is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, d):
        if self._cell is not None:
            self._cell.append(d)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._cur["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._cur is not None:
            self.tables.setdefault(self._cur["id"], self._cur["rows"])
            self._cur = self._stack.pop() if self._stack else None


def parse_tables(page):
    p = _Tables()
    p.feed(page)
    return p.tables


def parse_options(page, select_name):
    """Return [(value, label), ...] for a <select>."""
    m = re.search(r'<select[^>]*name="%s".*?</select>' % re.escape(select_name),
                  page, re.S | re.I)
    if not m:
        return []
    out = []
    for value, label in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
                                   m.group(0), re.S | re.I):
        label = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", label))).strip()
        if label and not label.lower().startswith(("choose ", "all ")):
            out.append((value, label))
    return out


def column_index(header):
    """The results table's header row -> ({COLUMN: cell index}, [extra labels]).

    Matches by name (HEADER_KEYS), so a column the site inserts can't shift the
    values; it comes back in the extra labels. A column that's missing or
    renamed raises PgemError rather than leaving a gap.
    """
    norm = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in header]
    idx = {}
    for i, h in enumerate(norm[1:], 1):
        if h.endswith("graduates"):
            idx["Graduates"] = i
            break
    for col, key in HEADER_KEYS.items():
        if key in norm:
            idx[col] = norm.index(key)
    missing = [c for c in COLUMNS if c not in idx]
    if missing:
        raise PgemError("the PGEM results table has no %s column (its header: %s); the "
                        "site's layout changed, so update HEADER_KEYS in postgrad_outcomes.py"
                        % (" / ".join(missing), " | ".join(header)))
    used = set(idx.values()) | {0}
    return idx, [header[i] for i in range(len(header)) if i not in used]


def clean_number(s):
    """'$109,306' -> 109306 ; '50.0%' -> '50.0%' ; '*Data Unavailable' -> None."""
    s = (s or "").strip()
    if not s or s.startswith("*"):
        return None
    if s.endswith("%"):
        return s
    t = s.replace("$", "").replace(",", "")
    try:
        return int(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return s


# ------------------------------------------------------------------ core pull
def load_catalog(level, timeout=DEFAULT_TIMEOUT):
    """{plan_code: plan_name} for a level, plus {college_id: college_name}."""
    page = fetch_summary(level, timeout=timeout)
    plans = dict(parse_options(page, "acadPlanID"))
    colleges = dict(parse_options(page, "collegeID"))
    return plans, colleges


def college_of(plan_code):
    return plan_code[:2] if len(plan_code) > 2 else "99"


def resolve(specs, plans):
    """Map user specs -> [(code, name), ...]. Substring matches keep every hit."""
    picked, notes = [], []
    for spec in specs:
        if spec in plans:                                  # exact code
            picked.append((spec, plans[spec]))
            continue
        hits = [(c, n) for c, n in plans.items() if spec.lower() in n.lower()]
        if not hits:
            notes.append("no match for %r" % spec)
            continue
        if len(hits) > 1:
            notes.append("%r matched %d plans: %s"
                         % (spec, len(hits), ", ".join("%s (%s)" % (n, c) for c, n in hits)))
        picked.extend(hits)
    seen, out = set(), []
    for c, n in picked:
        if c not in seen:
            seen.add(c)
            out.append((c, n))
    return out, notes


def pull(code, name, level, want_detail=False, timeout=DEFAULT_TIMEOUT):
    """One plan -> a result dict.

    want_detail: falsy = summary only; True (or "both") = employers + further
    education; "employment" = employers only, which saves one HTTP request per
    plan when all you want is job titles. The string form is additive on purpose
    -- build_outcomes_workbook.py passes this argument positionally as a bool.
    """
    col = college_of(code)
    tables = parse_tables(fetch_summary(level, col, code, timeout=timeout))
    rows = tables.get("filteredPlanTable") or []
    header = next((r for r in rows if r and r[0].lower().startswith("academic plan")), None)
    if rows and header is None:
        raise PgemError("the results table has no 'Academic Plan' header row; the site's "
                        "layout changed")
    idx, extra = column_index(header) if header else ({}, [])
    width = max(idx.values(), default=0) + 1
    plan_row = college_row = None
    for r in rows:
        if r is header or len(r) < width:
            continue
        if r[0].lower().startswith(("college of", "institute", "poole", "wilson")):
            college_row = r
        else:
            plan_row = r

    def pack(r):
        return None if not r else {c: clean_number(r[idx[c]]) for c in COLUMNS}

    res = {"code": code, "name": name, "level": level, "college_id": col,
           "data": pack(plan_row), "college_total": pack(college_row),
           "college_label": college_row[0] if college_row else None}
    if extra:
        res["new_columns"] = extra
    if plan_row is None:
        res["error"] = "no row returned (plan may have no graduates in this window)"
    if want_detail:
        # `or ""` not `.get(k, "")`: the endpoint returns JSON nulls for blank
        # fields, so the key exists and .get's default never fires -- leaving
        # None in the tuples, which blows up any later sort against a str.
        def s(d, k):
            return (d.get(k) or "").strip()
        res["employment"] = [(s(d, "COMPANY"), s(d, "JOBTITLE"))
                             for d in fetch_detail("employment", level, col, code, timeout)]
        if want_detail != "employment":
            res["furthered"] = [(s(d, "INSTITUTION"), s(d, "ACADPROG"),
                                 s(d, "DEGREE"), s(d, "DEGREE_DETAIL"))
                                for d in fetch_detail("furthered", level, col, code, timeout)]
    return res


def employment_rows(results):
    """Flatten pulled results into long-format job-title rows.

    One row per employed respondent: (plan code, program, company, job title).
    Long format on purpose -- it is the shape that survives CSV/Excel and that
    concatenates cleanly across programs.
    """
    rows = []
    for r in results:
        for company, title in r.get("employment", []):
            rows.append((r["code"], r["name"], company, title))
    return sorted(rows, key=lambda t: (t[1], t[2].lower(), t[3].lower()))


# -------------------------------------------------------------------- display
# Only these two are dollars. "Reporting Salary" also contains the word "Salary"
# but is a COUNT of respondents who reported one -- formatting it as currency
# turns "18 people" into "$18".
MONEY = ("Avg Salary", "Median Salary")


def fmt(col, v):
    if v is None:
        return "n/a"
    if col in MONEY and isinstance(v, (int, float)):
        return "${:,.0f}".format(v)
    return "{:,}".format(v) if isinstance(v, int) else str(v)


def render_table(results, with_college=False):
    head = ["Program"] + COLUMNS
    body = []
    for r in results:
        if r.get("data"):
            body.append([r["name"]] + [fmt(c, r["data"][c]) for c in COLUMNS])
        else:
            body.append([r["name"]] + ["n/a"] * len(COLUMNS))
        if with_college and r.get("college_total"):
            body.append(["  " + (r["college_label"] or "College total")]
                        + [fmt(c, r["college_total"][c]) for c in COLUMNS])
    w = [max(len(head[i]), max((len(b[i]) for b in body), default=0))
         for i in range(len(head))]
    line = "-+-".join("-" * x for x in w)
    out = [" | ".join(h.ljust(w[i]) if i == 0 else h.rjust(w[i]) for i, h in enumerate(head)),
           line]
    for b in body:
        out.append(" | ".join(c.ljust(w[i]) if i == 0 else c.rjust(w[i])
                              for i, c in enumerate(b)))
    return "\n".join(out)


def render_detail(r):
    out = []
    emp, fur = r.get("employment", []), r.get("furthered", [])
    out.append("\n%s -- employment (%d respondent%s)"
               % (r["name"], len(emp), "" if len(emp) == 1 else "s"))
    if emp:
        wc = max(len("Company"), max(len(c) for c, _ in emp))
        out.append("  %s | %s" % ("Company".ljust(wc), "Job Title"))
        out.append("  %s-+-%s" % ("-" * wc, "-" * 9))
        for c, j in sorted(emp):
            out.append("  %s | %s" % (c.ljust(wc), j))
    else:
        out.append("  (none reported)")
    out.append("\n%s -- further education (%d respondent%s)"
               % (r["name"], len(fur), "" if len(fur) == 1 else "s"))
    if fur:
        for inst, prog, deg, det in sorted(fur):
            out.append("  %s | %s | %s | %s" % (inst, prog, deg, det))
    else:
        out.append("  (none reported)")
    return "\n".join(out)


def render_titles(rows, show_program=True):
    """Long-format job-title table. All columns left-aligned -- these are text,
    not quantities, so the numeric right-alignment of render_table is wrong here."""
    if not rows:
        return "  (no employment responses reported)"
    head = (["Program"] if show_program else []) + ["Company", "Job Title"]
    body = [list(t[1:] if show_program else t[2:]) for t in rows]
    w = [max(len(head[i]), max(len(b[i]) for b in body)) for i in range(len(head))]
    out = [" | ".join(h.ljust(w[i]) for i, h in enumerate(head)).rstrip(),
           "-+-".join("-" * x for x in w)]
    for b in body:
        out.append(" | ".join(c.ljust(w[i]) for i, c in enumerate(b)).rstrip())
    return "\n".join(out)


def render_titles_csv(rows):
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["Plan Code", "Program", "Company", "Job Title"])
    w.writerows(rows)


def render_csv(results, with_college=False):
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["Plan Code", "Program", "Level"] + COLUMNS)
    for r in results:
        d = r.get("data") or {}
        w.writerow([r["code"], r["name"], r["level"]] + [d.get(c, "") for c in COLUMNS])
        if with_college and r.get("college_total"):
            t = r["college_total"]
            w.writerow(["", r["college_label"], r["level"]] + [t.get(c, "") for c in COLUMNS])


# ------------------------------------------------------------------------ cli
def main(argv=None):
    # Job titles are respondent-entered; one outside Windows' default code page
    # ("≥") crashed output to a file or pipe (see "Failure posture").
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(
        description="NC State post-graduate employment outcomes by academic program.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--program", action="append", default=[], metavar="SPEC",
                    help="plan code or name substring; repeatable")
    ap.add_argument("--level", default="Masters", choices=LEVELS)
    ap.add_argument("--college", metavar="ID")
    ap.add_argument("--all", action="store_true", help="every plan in --college")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--titles", action="store_true",
                    help="output only employer/job-title rows (long format); "
                         "works with --csv/--json")
    ap.add_argument("--with-college", action="store_true")
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--list-colleges", action="store_true")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="seconds to wait for each reply (default %d)" % DEFAULT_TIMEOUT)
    a = ap.parse_args(argv)
    if a.timeout <= 0:
        ap.error("--timeout must be a positive number of seconds")

    try:
        plans, colleges = load_catalog(a.level, a.timeout)
    except Exception as e:                                   # network/site down
        sys.exit("could not reach %s: %s" % (BASE, e))

    if a.list_colleges:
        for cid, cname in sorted(colleges.items()):
            print("  %-4s %s" % (cid, cname))
        return 0

    if a.list:
        sel = {c: n for c, n in plans.items()
               if not a.college or college_of(c) == a.college}
        print("%d plans for %s%s"
              % (len(sel), a.level,
                 " in college %s" % a.college if a.college else ""))
        for c, n in sorted(sel.items(), key=lambda kv: kv[1]):
            print("  %-12s %s" % (c, n))
        return 0

    if a.all:
        if not a.college:
            sys.exit("--all requires --college (see --list-colleges)")
        targets = sorted(((c, n) for c, n in plans.items() if college_of(c) == a.college),
                         key=lambda kv: kv[1])
        notes = []
    elif a.program:
        targets, notes = resolve(a.program, plans)
    else:
        sys.exit("give -p/--program, or --college with --all, or --list")

    for n in notes:
        print("note: " + n, file=sys.stderr)
    if not targets:
        sys.exit("nothing to pull -- try --list to see valid programs")

    # --titles needs employers but not further education; --detail wants both.
    detail = True if a.detail else ("employment" if a.titles else False)

    results, failed, in_a_row = [], [], 0
    for i, (code, name) in enumerate(targets):
        try:
            results.append(pull(code, name, a.level, detail, a.timeout))
            in_a_row = 0
        except Exception as e:
            failed.append((code, name, str(e)))
            print("warning: %s (%s) failed: %s" % (name, code, e), file=sys.stderr)
            in_a_row = in_a_row + 1 if isinstance(e, PgemNetworkError) else 0
            if in_a_row >= MAX_NETWORK_FAILURES and i + 1 < len(targets):
                rest = targets[i + 1:]
                failed += [(c, n, "not tried: the site had stopped answering") for c, n in rest]
                print("warning: %d plans in a row failed on network errors; not trying the "
                      "other %d" % (in_a_row, len(rest)), file=sys.stderr)
                break

    new_cols = sorted({c for r in results for c in r.get("new_columns", [])})
    if new_cols:
        print("note: PGEM now publishes column(s) this tool doesn't read: %s"
              % ", ".join(new_cols), file=sys.stderr)

    def failures_to_stdout():
        """Name the failed plans under a human-readable table."""
        if failed:
            print("\nFAILED, so not in the output above:")
            for c, n, why in failed:
                print("  %s (%s): %s" % (n, c, why))

    def finish():
        """The run's exit code: 1 if any plan is missing, and say which on stderr.
        A partial result must not pass for a complete one (see "Failure posture")."""
        if not failed:
            return 0
        print("error: incomplete: %d of %d plan(s) failed or weren't tried, so are missing from the output: %s"
              % (len(failed), len(targets), "; ".join("%s (%s)" % (n, c) for c, n, _ in failed)),
              file=sys.stderr)
        return 1

    if not results:
        finish()
        sys.exit("no results")

    if a.titles:
        rows = employment_rows(results)
        if a.json:
            print(json.dumps([dict(zip(("code", "program", "company", "job_title"), r))
                              for r in rows], indent=2))
        elif a.csv:
            sys.stdout.write(CSV_BOM)
            render_titles_csv(rows)
        else:
            print("NC State post-graduate job titles -- %s" % a.level)
            print(render_titles(rows, show_program=len(results) > 1))
            print("\n%d employed respondent%s across %d program%s."
                  % (len(rows), "" if len(rows) == 1 else "s",
                     len(results), "" if len(results) == 1 else "s"))
            print("Respondent-entered and uncleaned, per the source's own note.")
            print("Source: %s (NC State University Data and Analytics)" % SUMMARY)
            failures_to_stdout()
        return finish()

    # --detail rows live only in the human-readable output. Say so rather than
    # letting a --detail --csv run look like it captured the job titles.
    if a.detail and a.csv:                       # --json already nests them
        print("note: --csv carries summary rows only; use --titles --csv for job titles",
              file=sys.stderr)

    if a.json:
        # Failed plans ride along as entries with no data and an "error".
        print(json.dumps(results + [{"code": c, "name": n, "level": a.level,
                                     "college_id": college_of(c), "data": None,
                                     "error": "failed: " + why} for c, n, why in failed],
                         indent=2))
    elif a.csv:
        sys.stdout.write(CSV_BOM)
        render_csv(results, a.with_college)
    else:
        print("NC State post-graduate outcomes -- %s" % a.level)
        print(render_table(results, a.with_college))
        if a.detail:
            for r in results:
                print(render_detail(r))
        missing = [r["name"] for r in results if not r.get("data")]
        if missing:
            print("\nno data returned for: " + ", ".join(missing), file=sys.stderr)
        failures_to_stdout()
        print("\nSource: %s (NC State University Data and Analytics)" % SUMMARY)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
