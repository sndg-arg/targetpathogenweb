---
name: tpw-git-workflow
description: Git commit/push discipline specific to Target Pathogen Web — fetch-and-compare before committing, exact-filename staging (never git add -A), commit message format, and push behavior. Load before committing or pushing changes in this repo.
---

# Target Pathogen Web — git workflow

## Before every commit

Run `git fetch origin <branch>` and compare `HEAD` against `origin/<branch>` in both directions
(`git log --oneline HEAD..origin/<branch>` and `git log --oneline origin/<branch>..HEAD`) to
confirm there's no divergence before proceeding. Don't skip this even for a small change — it's
cheap and catches a stale local branch before it turns into a conflicted push.

## Stage explicitly, never broadly

Stage only the specific files intentionally changed, by exact name (`git add path/to/file.py
path/to/other.css`). **Never `git add -A` or `git add .` in this repo.** The user routinely keeps
personal, in-progress working documents sitting modified or untracked in the working tree —
observed examples: `docs/TARGET_ROADMAP.md`, `docs/TARGET_FUNCTIONAL_REPORT.md`. These must never
be swept into a commit unless the user explicitly asked for that specific file to be included.
Run `git status --short` after staging to confirm only the intended files are staged.

In practice `docs/TARGET_ROADMAP.md` gets updated and committed often — the rule above is about
never including it *by accident* via broad staging, not about avoiding it. When a code change
completes or corrects a roadmap item (or the user directly asks to update the roadmap), edit and
stage it explicitly by name like any other intentionally-changed file.

## Commit message

Concise, explains *why* the change was made, not just what changed. End with:

```
Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

Pass the message via a heredoc, per standard git-commit discipline.

## Push behavior

Push after committing without re-asking each time — this has been the established convention for
this repo/session. This does **not** extend to force-pushing or amending a commit that's already
been pushed — those remain "ask first" actions regardless of this convention, per the general
git-safety rules (never skip hooks, never force-push without explicit request, never amend
published history).
