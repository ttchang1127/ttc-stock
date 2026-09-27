# ttc-stock — notes for Claude Code sessions

## Merging pull requests (standing authorization from the owner, 2026-09-27)

- Merge your own PR without asking once the GitHub `Tests` check is green on the
  current head and the PR is mergeable. Use a **merge commit** (not squash), so each
  commit stays individually revertible, and tell the owner what was merged.
- **Still ask first**, even with green tests, when a PR:
  1. changes the owner's holdings (`portfolio_holdings.json`);
  2. deletes or rewrites accumulated history (`market_rotation_history/`, SEC event
     history, any append-only snapshot) — appending is fine;
  3. adds or changes the kinds of notifications the workflows send (new GitHub issue
     types, new outward-facing messages).
- Never merge on red or pending CI, and never skip, disable or weaken a test to get green.

## Talking to the owner

- The owner is in Taiwan and writes in Traditional Chinese: reply in Traditional Chinese.
- **Report every time in Taiwan time (UTC+8)**, e.g. 「台灣時間 21:59」, never UTC alone. Workflow crons
  are written in UTC; convert them when mentioning schedules (daily refresh 23:17 UTC = 07:17 台灣時間).

## Checks to run before pushing

```bash
python3 -m unittest discover -s tests
python3 scripts/check_integrity.py --quiet
```

## Conventions

- Generated data files are listed in `data_manifest.json` with their producer; never
  hand-edit them. After editing `portfolio_holdings.json`, rerun
  `python3 scripts/build_sec_position_impact_history.py` and
  `python3 scripts/build_market_rotation_digest.py`, and sync the dashboard fallback
  holdings (C-31, C-47).
- Market-rotation research outputs stay labelled `research`; back-test candidates are
  frozen under a version constant and every result, failures included, is published.
- The maintenance SOPs in `00_Meta/` are the source of truth for procedures.
