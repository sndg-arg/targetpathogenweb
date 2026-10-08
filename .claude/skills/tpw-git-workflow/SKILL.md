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

**Do not add a `Co-Authored-By: Claude` trailer** — the user asked for commits in this repo to
not carry that line.

**Write titles like the other humans committing to this repo, not like an AI assistant
narrating itself.** Look at `git log --oneline -20` before writing one if unsure of the register.
This repo's real style: short, single-line, imperative, specific about *what* changed —
`Fix template access to xref attributes (no underscore prefix allowed)`, `Add a Redis service to
the cluster stack for shared caching`, `Show P2RANK Probability alongside Druggability in the
default column set`. That's the whole commit most of the time — no body.

Avoid the tells that mark a commit as AI-written: multi-paragraph bodies that explain and justify
the reasoning at length, a "Why:" or "Verified:" scaffold, hedging ("this should be safe because
Cd..."), or restating the diff in prose. If a body is genuinely warranted (a non-obvious root
cause, a decision future-you would otherwise re-litigate), keep it to 1-3 short lines — not a
essay. Default to title-only.

## Push behavior

Push after committing without re-asking each time — this has been the established convention for
this repo/session. This does **not** extend to force-pushing or amending a commit that's already
been pushed — those remain "ask first" actions regardless of this convention, per the general
git-safety rules (never skip hooks, never force-push without explicit request, never amend
published history).
