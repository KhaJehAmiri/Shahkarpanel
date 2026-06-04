# Git commit messages

## Cursor attribution

If commits on GitHub show `Co-authored-by: Cursor <cursoragent@cursor.com>`, that is added by the **Cursor IDE agent**, not by NexusPanel code.

Turn it off: **Cursor Settings → Agent → Attribution** (disable).

Project hook `.cursor/hooks/strip-commit-attribution.sh` blocks explicit `Co-authored-by: Cursor` in `git commit` commands from the agent.

## Phase prefixes

Avoid `Phase N:` in commit subjects; use a short imperative summary instead (e.g. `Add WireGuard unified accounting`).

To clean existing history on a clone:

```bash
git filter-branch -f --msg-filter 'python3 scripts/filter_commit_msg.py' master
```

Then force-push only if you intend to rewrite `master` on the remote.
