[简体中文](README.zh-CN.md)

# SourceLedger

**Know which notes need another look when their sources change.**

SourceLedger is a local-first review queue for Markdown handbooks, runbooks, research notes, and agent knowledge folders. Declare which local sources a note depends on. Review exact source diffs. Explicitly accept the snapshot after checking the affected note.

It does not rewrite your notes, call an LLM, fetch URLs, or decide whether a statement is factually correct.

![Actual desktop report rendered by Chromium in CI](docs/images/report-desktop.png)

[Mobile screenshot](docs/images/report-mobile.png) · [Actual HTML example](docs/example-report.html)

## Try a complete example

Python 3.10+ and Git are required. No runtime dependencies or service accounts.

Linux / macOS:

```sh
git clone https://github.com/keweizhuazuki/sourceledger.git
cd sourceledger
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python examples/demo.py
```

Windows PowerShell (activation is optional):

```powershell
git clone https://github.com/keweizhuazuki/sourceledger.git
cd sourceledger
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe examples\demo.py
```

The demo copies a tiny handbook into a temporary directory, accepts its initial sources, changes the access duration from 30 to 14 days, and creates `demo-report.html` in your current folder. Open it in a browser. A second run refuses to overwrite that report; move it first. The original examples stay unchanged. You can also run `python -m sourceledger` from the checkout without installation.

Expected useful output:

```text
0 new, 1 changed, 1 current, 0 error

[CHANGED] onboarding.md ← policy.md → Access [1]
--- accepted
+++ current
@@ -1,4 +1,4 @@
 ## Access
 
-Temporary access lasts 30 days. A manager must approve it.
+Temporary access lasts 14 days. A manager must approve it.
```

## Use your existing knowledge base

1. Run `sourceledger --root /path/to/notes init`.
2. Edit the generated `sourceledger.json` to describe actual dependencies. Paths are relative to that folder, with forward slashes on all platforms.
3. Run `sourceledger --root /path/to/notes headings sources/policy.md` to find exact heading names and duplicate occurrences.
4. Run `sourceledger --root /path/to/notes check`. New dependencies require an initial review, just like changed sources.
5. Review the affected notes and the source diff. Edit your notes yourself if needed, then run `check` again to obtain a fresh token.
6. Accept exactly that review with `sourceledger --root /path/to/notes accept --token TOKEN`.

```json
{
  "version": 1,
  "dependencies": [
    {"note": "notes/onboarding.md", "source": "sources/policy.md", "heading": "Access", "occurrence": 1},
    {"note": "notes/onboarding.md", "source": "sources/support.md"}
  ]
}
```

Omit `heading` to watch the whole UTF-8 file. A heading watches its complete section including subsections, up to the next same-or-higher-level heading. Editing unrelated sections does not flag this dependency. Headings are exact, case-sensitive ATX titles (`#` through `######`); duplicate titles use 1-based `occurrence` in document order. Fenced-code headings are ignored. Setext headings, HTML headings, and rendered Markdown slug interpretation are not supported.

### Review one note or export a report

```sh
sourceledger --root ./handbook check --note notes/onboarding.md
sourceledger --root ./handbook accept --note notes/onboarding.md --token TOKEN
sourceledger --root ./handbook check --format html --output review.html
sourceledger --root ./handbook check --format json --output review.json
```

Use the same `--note` selection for checking and acceptance. A token changes when selected source content, note content, dependency identity, or its accepted baseline changes. A token is a stale-review guard, not a password or signature. Existing output files are never overwritten. CLI output and saved reports use UTF-8.

Exit codes: `0` all selected sources current / action succeeded; `1` new or changed sources require review; `2` invalid configuration, missing source/note/section, unreadable file, or operation error. A missing or renamed source is an error, never an accepted deletion. Correct the path deliberately and review the new dependency.

## Data and safety boundaries

- Accepted source text is stored locally in `.sourceledger/state.sqlite3`. Treat it as sensitive if your sources are sensitive; keep it out of public Git history. Back it up to preserve reviews.
- `check` creates/opens local database storage but never updates accepted baselines. Acceptance is one SQLite transaction; any dependency error prevents the whole selected batch from being accepted.
- Reads are limited to 2 MiB per UTF-8 file. Absolute paths, paths outside the root, and resolved symlink escapes are rejected. Do not run on an untrusted directory being concurrently manipulated; this is a local tool, not a filesystem sandbox.
- Source content is captured at check/accept time; there is no filesystem-wide atomic snapshot. Stop concurrent editors while accepting. SQLite serializes competing acceptance writes.
- Reports can contain full source excerpts, so review them before sharing. HTML is escaped, has no scripts, and loads no remote resources.
- No network source fetching, cron daemon, notifications, cloud syncing, telemetry, or factual validation. Markdown notes are never automatically modified. Removed manifest entries are no longer checked; their prior accepted text remains in the database.

## Why this exists

Link checkers answer whether a target resolves. Website monitors answer whether a page changed. SourceLedger answers **which local notes depend on changed source material, and which changes have I reviewed?** See [research and alternatives](docs/research.md). The product is independently implemented; no claim of global novelty or compatibility with every Markdown renderer.

## Verification and development

```sh
python -m unittest discover -s tests -v
python -m compileall -q sourceledger tests
```

The initial local suite runs on Linux. The repository CI matrix is configured for Linux, macOS, and Windows with Python 3.10 and 3.13; a configured workflow is not itself evidence of a successful run. Symlink tests skip if the OS does not permit creating them. The HTML report is generated from real demo data; browser layout validation is separate from unit tests.

## Completed and next upgrades

Completed: section/whole-file dependency tracking; explicit token-bound acceptance; per-note review; missing-source errors; transactional baseline storage; text/JSON/HTML reports; a runnable disposable demo; regression tests.

Next: local Markdown-link discovery with review before tracking; a richer acceptance history; deterministic anchor mapping for more Markdown dialects; CI baseline import/export; optional Git rename suggestions. No dates promised. Feedback should describe the repeated workflow and include a minimal non-sensitive fixture.

No license has been selected or granted by this repository.
