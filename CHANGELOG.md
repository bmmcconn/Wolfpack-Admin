# Changelog

Notable changes to the tools in this repo, newest first.

**Entries marked ⚠️ change the numbers a tool returns.** If you produced output
before that date, re-check it — that is what this file is for.

There are no version numbers here, because there are no tagged releases. These
tools parse NC State's public web pages, so a pinned copy silently rots when
those pages change; the intended way to use them is to clone and `git pull`.
Dates below are when a change was published to this repo.

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
- MIT licence.
