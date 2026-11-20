# Changelog

Notable changes to the tools in this repo, newest first.

**Entries marked ⚠️ change the numbers a tool returns.** If you produced output
before that date, re-check it — that is what this file is for.

There are no version numbers here, because there are no tagged releases. These
tools parse NC State's public web pages, so a pinned copy silently rots when
those pages change; the intended way to use them is to clone and `git pull`.
Dates below are when a change was published to this repo.

---

## 2026-11-20

### Fixed

- **`class_search.py` — unpublished terms read as the schedule.** Class Search
  answers for terms its own term list doesn't offer yet. In November 2026 the
  following Fall returned a full slate of courses with 0 enrolled: the
  registrar's draft. Nothing in the response marks it as a draft. The tool now
  checks each term against the published list (alongside the search, so no
  extra wait). For a term that isn't on it, the tool warns, marks the output
  `!! UNPUBLISHED TERM`, and sets `term_published` to false in `--json` and
  `--csv`. If you saved a pull of a term before it appeared in `--list-terms`,
  treat it as a draft.
- **`class_search.py` and `course_catalog.py` — a stalled server could hold a
  call for about 90 seconds.**
  Each reply was allowed 30 s, with two retries. Real queries answer in under
  3 s, so the default is now 10 s (`--timeout` still overrides it), and a
  stalled server fails in about 30 s. A host name that doesn't resolve now fails
  at once instead of being retried. `class_search.py` rejects `--timeout 0`.
- **`course_catalog.py` — a too-broad keyword search** (a very common word)
  stalls after the server accepts it, and is dropped about 10 s in. It now fails
  once, with a message to narrow the search, instead of timing out and retrying.
- **`postgrad_outcomes.py` — a new column on the site would have shifted the
  numbers.** Values were read by position, so a column the site inserted would
  move every later value without a warning (tested: one inserted before the
  average salary made a program's average read "$7" and its median show the
  average). Columns are now read by their header names: an added column is
  ignored and named in a note, and a missing or renamed one fails that program.
  The site hasn't changed its columns, so no earlier output is affected; this
  guards the next change.
- **`postgrad_outcomes.py` — a failed program was dropped quietly.** If one
  program's request failed, it was left out of the output and the run still
  exited 0, so a partial `--csv` looked complete. Failed programs are now named
  at the end, the run exits 1, and `--json` includes them with `"data": null`
  and an `"error"`.
- **`postgrad_outcomes.py` — an error from the job-title endpoint read as "no
  employment responses reported."** It now fails that program instead. A
  program with no rows still answers `[]` and still prints "none reported".
- **`postgrad_outcomes.py` — a job title with a character outside Windows'
  default code page crashed output sent to a file or pipe.** Output is now
  UTF-8. `--csv` begins with a UTF-8 byte-order mark so Excel shows dashes and
  accented characters correctly; in Python, read it with
  `encoding="utf-8-sig"`.
- **`postgrad_outcomes.py` — 45 s per request, no retries.** Each reply now gets
  10 s (`--timeout` overrides it), with two retries for timeouts and server
  errors. If two programs in a row fail on network errors, the run stops and
  names the programs it didn't try, instead of spending about 30 s on each one
  left.

### Added

- **`class_search.py` — several subjects, course codes and terms in one call**,
  run concurrently (at most four at a time): `EM 501`, `"EM 501, ISE 543" EGR`,
  `--term "Fall 2026, Spring 2027"`. A subject or course with no sections in a
  term is a note, not an error, unless nothing at all was found. With more than
  one term, `--json` returns `{"pulled_at", "terms": [...]}`; with one term it
  keeps its old shape and adds `term_published` and `notes`.
- **`class_search.py --with-crosslists`** fetches each cross-listed course's
  other listings in the same term and gives whole-class totals: a "whole class"
  line in the text output, one row per class in `--summary`, and `class_total`
  in `--json`. Without it, `--summary` now says how many rows count only one
  listing.
- **`--csv` gains two columns at the end** (`crosslist_of`, `term_published`);
  earlier columns are unchanged.
- **`class_search.py` and `course_catalog.py` — clearer errors.** A four-digit course number (another school's
  numbering) says so. An unknown subject names close matches ("EMG" → EM).
  `class_search.py` accepts five-letter subjects, as `course_catalog.py` does.

---

## 2026-10-08

### Fixed

- ⚠️ **`class_search.py` — cross-listings were cut to the first code.** Class
  Search separates a course's cross-listings with spaces, and the parser expected
  commas, so it kept only the first: ISE 505 showed MA 505 but not OR 505 (17 of
  64 cross-listed courses in one sample). `also_listed_as` now carries every
  code. If you checked syllabi or enrollment across a course's prefixes, re-check.
- ⚠️ **`class_search.py` — multi-line cells were run together.** A section that
  meets at different times on different days lost every meeting time after the
  first. Co-taught sections ran their instructors together ("Doe,Jane A.
  Roe,John"), which can't be split back because names contain spaces, and
  rooms were repeated. `days` and `time` now hold one entry per meeting, aligned
  and joined with "; ". `instructor` and `location` list each entry once, joined
  with "; ".
- ⚠️ **`class_search.py` — with no `--term`, the tool queried the wrong term.**
  It took the first entry in the site's term list, which is the coming Summer 2
  term, not the term the site opens on. A bare `class_search.py EM` failed with
  "unknown or mistyped subject", and `--summary` reported Summer 2 without saying
  so. The tool now uses the site's own default, and says so on stderr.
- ⚠️ **`class_search.py` — ended and future terms read as empty or
  non-compliant.** Class Search stops publishing seat counts once a term ends,
  and shows syllabus links only while a term is in session. So outside a session
  the syllabus flag is now blank (`null` in `--json`) rather than `NO-SYL` on
  every row. A term with no published seat counts now reports course totals as
  `null`, not 0. `--summary` prints `n/a`, not 0/0, and `--open-only` stops with
  an error instead of silently returning nothing. An empty result in a term
  that does publish counts no longer claims "enrollment not published".
- **`class_search.py` — term names.** "Summer 2026" was read as Summer 2 (from
  the "2" in the year); it now means Summer 1, as documented. Years outside
  2000-2099 are refused: "Fall 1999" became Fall 2099.
- **`class_search.py` — errors.** A malformed `--number`, a bad subject-list
  response, and a connection dropped mid-response now give a clear error instead
  of a silent "0 courses" or a traceback. An unknown subject now reads "no ZZZ
  sections in <term> — wrong term, or mistyped subject". Piping output into a
  reader that stops early (`| head -1`) no longer prints a traceback on Windows.
- **README — cross-listed totals.** The README said summing a cross-listed course
  across subjects double-counts it. It's the reverse: each listing is a separate
  class with its own enrollment, so the course's real size is the sum across its
  listings, and a per-subject total undercounts it.

### Added

- **`course_catalog.py`** — new tool. Looks up courses in the registrar's Course
  Catalog: title, credit hours, requisite text, the terms a course is typically
  offered, GEP categories, cross- and dual-listings, the terms with sections
  scheduled, and the description. Search by course code (several at once, across
  subjects), by subject, by a phrase in course descriptions, or by GEP category.
  Text, `--brief`, `--json` and `--csv` output. NC State's two catalogs can give
  a dual-listed course different requisites; the README explains which is which.
- **`class_search.py` — course `description` and `requisites`.** Class Search
  already prints the catalog description and requisite text above each course;
  the tool now keeps them (`--json`; `requisites` is also a new `--csv` column).
- **`class_search.py` — section notes, split by kind.** `class_notes`,
  `class_requisites`, and `seat_reserves`: a list of seat counts and who the
  seats are reserved for, e.g. `{"seats": 40, "reserved_for": "R: MEM Students
  Only"}`. They are new `--csv` columns, added at the end so older pulls still
  line up. `notes` still holds all three.
- **`class_search.py` — `--list-terms` marks the default term.**

---

## 2026-08-14

### Added

- **`class_search.py` — special-topics sections now report their actual `topic`.**
  The results table has a **Topic** column that this tool never read. Every
  special-topics section (ISE 489/589, EM 589, and the equivalent in any other
  subject) carries a catalog `title` of only "Special Topics in …", so the real
  subject was invisible: **searching titles found none of them.** Sections now
  carry a `topic` field, printed beneath the section line, added to `--csv` as a
  new column, and present in `--json`. Example: ISE 589-012, Spring 2026 — title
  "Special Topics In Industrial Engineering", topic "Optimization for Machine
  Learning". This is where a department's newest courses appear before they are
  assigned a permanent number, so it is the field to search when asking what is
  actually being taught.

### Fixed

- ⚠️ **`class_search.py` — every field from `Avail.` rightward was wrong for past
  terms.** The results table's column *set* is not constant: terms whose
  enrollment has closed omit the **Avail.** column entirely, shifting every later
  column one place left. The parser read fixed column positions, so for those
  terms it returned the **Begin/End date in the `instructor` field**, the
  instructor in `location`, and no meeting days or times at all. Current and
  future terms were unaffected, which is why this went unnoticed. Cells are now
  located by **header name**, so a column set that varies — or is reordered —
  parses correctly either way. Re-check any saved pull of a completed term.
- **`class_search.py` — the "unparseable Avail. cell" warning fired on every
  course in every completed term.** Those terms publish no Avail. column at all;
  that is absent data, not the markup drift the warning is meant to catch, and a
  warning that always fires is one nobody reads. Courses now carry
  `enrollment_published`, the warning is limited to genuine drift, and the CLI
  prints "enrollment not published for this term" instead of an
  enrollment-shaped `Avail 0/0 · Enr 0` that reads as an empty class.

---

## 2026-08-11

### Fixed

- ⚠️ **`class_search.py` — `--instructor` returned every unassigned section as a
  match.** Class Search applies its instructor filter only to sections that have
  an instructor of record; "Staff"/TBA sections come back regardless, and the
  tool passed them through. A search of one department returned 19 sections when
  1 was a real match. Results are now filtered against the parsed data.
- ⚠️ **`class_search.py` — `--open-only` returned sections with no seats left.**
  The site's "open classes" means *not closed*, which includes zero-seat
  waitlisted sections, but this tool documents the flag as "has seats available."
  It now honors that: one department's pull dropped from 88 sections to 72.
- ⚠️ **`class_search.py` — distance-ed sections that meet in a room were counted
  as on-campus.** Delivery mode was inferred from the location cell alone, so a
  *synchronous* DE section — one that meets at a scheduled time in a real room
  while remote students join — was classified on-campus. `--summary` split on
  that field, so in one department's Fall 2026 data **distance-ed enrollment read
  half its true value**. Mode is now detected from both available signals, and
  `--summary` splits on how a section is *coded* rather than how it meets.
  **If you have produced an on-campus vs. online split with this tool, re-run
  it.** Departments whose DE sections are all fully online are unaffected.

### Added

- **`postgrad_outcomes.py`** — new tool. Post-graduate employment outcomes by
  academic program: graduates, respondents, response rate, grad-school vs.
  full-time-job counts, average and median starting salary, and `--titles` for
  the employers and job titles respondents reported.
- **`class_search.py` — `--distance-ed` / `--no-distance-ed`.** Filter to
  distance-ed-coded sections or on-campus-coded ones. Combines with `--mode`, so
  `--distance-ed --mode in-person` isolates synchronous DE sections — a query
  that could not be expressed before.
- **`class_search.py` — published-syllabus status.** Sections show `SYL` /
  `NO-SYL`, and a `syllabus` boolean appears in `--json` / `--csv`. Note that
  cross-listed sections are tracked separately: a syllabus posted under one
  subject code does not mark the other code's listing.
- **`class_search.py` — `distance_ed` field** in `--json` and `--csv`, alongside
  the existing `mode`. They answer different questions and can disagree.

### Changed

- README: added requirements and getting-started (including the Windows
  Microsoft-Store placeholder trap), made cloning the recommended install, and
  documented why there are no tagged releases.

---

## 2026-07-24

### Added

- **`class_search.py`** — initial release. Term-specific section listings with
  live availability, meeting times, instructor, mode and cross-listings, plus
  `--json`, `--csv` and `--summary` output.
- MIT license.
