# Changelog

Notable changes to the tools in this repo, newest first.

**Entries marked ⚠️ change the numbers a tool returns.** If you produced output
before that date, re-check it — that is what this file is for.

There are no version numbers here, because there are no tagged releases. These
tools parse NC State's public web pages, so a pinned copy silently rots when
those pages change; the intended way to use them is to clone and `git pull`.
Dates below are when a change was published to this repo.

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
