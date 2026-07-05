---
name: finish-phase
description: Wrap up the current roadmap phase: update the changelog, mark the phase complete in specs/roadmap.md, commit, merge to main, and delete the branch.
---

# Finish phase

Wrap up the current roadmap phase: update changelog, mark complete, commit, merge to main, and clean up the branch.

## Instructions

### 1. Detect current phase

- Read the current branch name (e.g. `phase-1-thin-vertical-slice`).
- Extract the phase number and name from the branch.
- Open `specs/roadmap.md` and locate the matching `## Phase N` heading.
- If no matching phase is found, stop and tell the user.

### 2. Update changelog

- Invoke the `changelog` skill to update `CHANGELOG.md` with recent commits.

### 3. Mark phase complete in roadmap

- In `specs/roadmap.md`, apply strikethrough and the ✅ marker to the phase heading (e.g. `## Phase 1 — Thin vertical slice ⭐` → `## ~~Phase 1 — Thin vertical slice~~ ✅`).
- Apply strikethrough to each bullet under that phase (e.g. `- Item` → `- ~~Item~~`).
- Once any phase is complete, keep every later phase consistent with that same formatting pattern.

### 4. Commit

- Stage only the changed files (`CHANGELOG.md`, `specs/roadmap.md`, and any other modified/untracked project files).
- Create a single commit. Use the message pattern: `Complete Fase N — <Phase Name>`.
- Do NOT push.

### 5. Merge to main

- Switch to `main` branch.
- Merge the phase branch into main using `git merge --no-ff <branch>` to preserve the merge commit.
- Do NOT push.

### 6. Delete the phase branch

- Delete the local phase branch: `git branch -d <branch>`.
- Do NOT delete remote branches.

### 7. Summary

- Print a short summary: what was merged, the merge commit hash, and remind the user to `git push` when ready.
