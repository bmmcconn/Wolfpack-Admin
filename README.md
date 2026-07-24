# Wolfpack-Admin

Small, self-contained command-line tools for working with NC State's public web
services. **Unofficial** — not an NC State product or service. MIT-licensed.

**Built for coding agents.** These tools are developed primarily for use by AI
coding agents (Claude Code, Codex, and similar) — and work equally well run by a
human at a terminal. Each is a single stdlib-only Python file with a documented,
importable API, so an agent can read it, invoke it, and compose it with no setup
and no third-party dependencies.

## class_search.py

Query NC State **Class Search** (go.ncsu.edu/class_search) for term-specific
sections with **live availability** (seats available/capacity, plus derived
enrolled), meeting times, instructor, mode (on-campus vs. online), and cross-listings. Pure Python standard library —
no third-party dependencies, no API key.

### Quick start

```
python class_search.py EM --term "Fall 2026"
python class_search.py EM --term 2268 --open-only
python class_search.py MAE --term 2268 --mode online
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

### PowerShell note

Quote inequality arguments so the shell does not treat them as redirection:
`--ineq "<="`.

## License

MIT — see [LICENSE](LICENSE). Questions or issues: open an issue on this repo, or
reach me through my GitHub profile, [@bmmcconn](https://github.com/bmmcconn).
