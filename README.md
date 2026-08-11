# Wolfpack-Admin

Small, self-contained command-line tools for working with NC State's public web
services. **Unofficial** — not an NC State product or service. MIT-licensed.

**Built for coding agents.** These tools are developed primarily for use by AI
coding agents (Claude Code, Codex, and similar) — and work equally well run by a
human at a terminal. Each is a single stdlib-only Python file with a documented,
importable API, so an agent can read it, invoke it, and compose it with no setup
and no third-party dependencies.

| Tool | What it answers |
|------|-----------------|
| [`class_search.py`](class_search.py) | What sections are offered this term, and how full are they *right now*? |
| [`postgrad_outcomes.py`](postgrad_outcomes.py) | Where do a program's graduates end up — salaries, employers, job titles? |

## Requirements & getting started

**Python 3.8 or newer. Nothing else.** No `pip install`, no dependencies, no API
key, no account. Check what you have:

```
python --version
```

**Getting the files.** Either clone the repo, or just download the one tool you
want — each is a single self-contained file:

```
git clone https://github.com/bmmcconn/Wolfpack-Admin.git
```

To grab a single file instead, open it above, click **Raw**, and save it. Then run
it from whatever folder you saved it in.

**Windows note.** If `python --version` opens the Microsoft Store or prints
nothing useful, you have Windows' placeholder rather than a real Python. Install
from [python.org](https://www.python.org/downloads/) (tick **"Add python.exe to
PATH"** during setup), then use the bundled launcher, which sidesteps the
placeholder entirely:

```
py class_search.py EM --term "Fall 2026"
```

If a plain `python` still misbehaves after installing, turn off the aliases at
**Settings → Apps → Advanced app settings → App execution aliases** (switch off
the `python.exe` and `python3.exe` entries).

**These tools read live public web pages** and write nothing anywhere. Re-run
them any time; there is no state to manage and nothing to uninstall.

## class_search.py

Query NC State **Class Search** (go.ncsu.edu/class_search) for term-specific
sections with **live availability** (seats available/capacity, plus derived
enrolled), meeting times, instructor, mode (on-campus vs. online), published-syllabus
status, and cross-listings. Pure Python standard library — no third-party
dependencies, no API key.

### Quick start

```
python class_search.py EM --term "Fall 2026"
python class_search.py EM --term 2268 --open-only
python class_search.py MAE --term 2268 --mode online
python class_search.py ISE --term 2268 --distance-ed             # all DE-coded sections
python class_search.py ISE --term 2268 --distance-ed --mode in-person   # synchronous DE
python class_search.py EM --term 2268 --json      # structured JSON (stamps pulled_at)
python class_search.py EM --term 2268 --csv       # one row per section (spreadsheet-ready)
python class_search.py EM --term 2268 --summary   # per-course: on-campus vs. online
python class_search.py --list-terms
python class_search.py --list-subjects --term 2268
```

A subject is required — Class Search will not return an entire term at once.

### Term codes

A term code (`strm`) is `2` + the two-digit year + a season digit:

| Season   | Digit | Example (2026) |
|----------|-------|----------------|
| Spring   | 1     | 2261           |
| Summer 1 | 6     | 2266           |
| Summer 2 | 7     | 2267           |
| Fall     | 8     | 2268           |

Pass either the code (`--term 2268`) or a friendly string (`--term "Fall 2026"`).
A bare calendar year (`--term 2026`) is rejected as ambiguous.

### Reading the numbers

- Availability is **seats available / capacity** — seats *open*, not enrolled.
  `27/30` means 27 seats open, so 3 enrolled (enrolled = capacity - available).
- Counts are **live** and move daily until the term settles, so a saved pull is a
  point-in-time snapshot. `--json` stamps `pulled_at` and `--csv` stamps a
  `pulled` column, so repeated CSV pulls concatenate cleanly for tracking over time.
- **Cross-listed** sections share one roster across every subject code they carry,
  so summing the same course under two subjects double-counts it.

### Online vs. distance ed — two different questions

A section can **meet in a room and still be distance-ed coded** (a synchronous DE
section: it meets at a scheduled time and remote students join). So the tool
reports both, and they don't always agree:

| Field | Means | Filter |
|-------|-------|--------|
| `mode` | how it *physically meets* — `online` / `in-person` | `--mode online` |
| `distance_ed` | how it is *coded* — DE tuition and reporting | `--distance-ed` |

`--summary` splits on `distance_ed`, because for enrollment reporting that's the
line that matters — a DE section meeting in a room belongs on the DE side of it.
`--distance-ed --mode in-person` isolates exactly those synchronous sections.

⚠️ **If you have used an earlier copy of this tool, re-check any on-campus vs.
online split you produced.** Mode was previously inferred from the location cell
alone, which classified synchronous DE sections as on-campus. In one department
that understated distance-ed enrollment by half. Departments whose DE sections
are all fully online were unaffected.

### Syllabus status (`SYL` / `NO-SYL`)

Class Search emits a syllabus link only for sections that actually have one
published, so the link's presence is a usable signal. ⚠️ **Cross-listed sections
are tracked separately**: a syllabus posted under one subject code does *not* mark
the other code's listing as having one. Check every prefix a course carries — see
the `also_listed_as` field.

### PowerShell note

Quote inequality arguments so the shell does not treat them as redirection:
`--ineq "<="`.

## postgrad_outcomes.py

Query NC State **Post-Graduate Employment** outcomes (University Data and
Analytics' Future Plans Survey / Survey of Recent Graduates) for one or more
academic programs: graduates, respondents, response rate, grad-school vs.
full-time-job counts, average and median starting salary, and — optionally — the
employers and job titles respondents reported. Public source, no login.

Everything it returns is **aggregate institutional data already published by the
university**; there are no student-level records.

### Quick start

```
python postgrad_outcomes.py -p "Engineering Management"          # one program
python postgrad_outcomes.py -p 14SCEMMR                          # by plan code
python postgrad_outcomes.py -p "Industrial Engineering"          # substring: pulls every match
python postgrad_outcomes.py --college 14 --all                   # every plan in a college
python postgrad_outcomes.py -p 14SCEMMR --titles                 # employers + job titles
python postgrad_outcomes.py -p 14SCEMMR --titles --csv           # ...spreadsheet-ready
python postgrad_outcomes.py -p 14SCEMMR --with-college           # + college total row
python postgrad_outcomes.py --list --college 14                  # plan codes and names
python postgrad_outcomes.py --list-colleges
```

`--level` selects `Seniors` (bachelor's), `Masters` (default), or `Doctoral`.

### Job titles

`--titles` returns one row per employed respondent — plan code, program, company,
job title — in long format, so it survives `--csv`/`--json` and concatenates
cleanly across programs. The source publishes exactly two fields here, company and
job title; there is no location, industry, or degree-relatedness data to be had.
Titles are respondent-entered and uncleaned (`Sr. Manager`, `Program Manager 2`),
so normalize before counting by category.

`--detail` additionally prints further-education rows, but only to the terminal —
use `--titles` when you need the data in a file.

### Reading the numbers

- **`Reporting Salary` is a count of respondents, not a dollar figure.** It is how
  many people reported a salary, which is usually smaller than the number employed.
- Salary cells read `*Data Unavailable` when too few responses exist to publish;
  those come back as empty, never `0`.
- **Check the base before quoting a median.** Response rates run near 50%, and for
  smaller programs a published median can rest on a handful of salaries. The
  respondent count is right there in the table — use it.
- **Duplicate plan names are real.** Several distinct plan codes share a name, and
  some names appear in more than one college, so a name substring can legitimately
  resolve to several rows. The tool pulls all matches and says so; use a plan code
  when you need exactly one.
- Job-title row counts should equal the summary's `Full Time Job` column — a free
  sanity check on any pull.

## License

MIT — see [LICENSE](LICENSE). Questions or issues: open an issue on this repo, or
reach me through my GitHub profile, [@bmmcconn](https://github.com/bmmcconn).
