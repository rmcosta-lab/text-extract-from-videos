---
name: implement-phase
description: Implement the current roadmap phase by following its plan.md, then verify every criterion in validation.md (ruff, mypy, real script run, acceptance checks).
---

# Implement phase

Implement the current phase by following its plan, then verify all validation criteria.

## Instructions

### 1. Detect current phase

- Read the current branch name (e.g. `phase-1-thin-vertical-slice`).
- Extract the phase number and slug from the branch.
- Locate the matching spec directory under `specs/` (e.g. `specs/2026-07-05-thin-vertical-slice/`).
- If no matching spec directory is found, tell the user and stop.

### 2. Load spec files

Read all three spec files from the phase's spec directory:

- `requirements.md` — understand objectives, scope, decisions, and visual guidelines.
- `plan.md` — the ordered list of implementation tasks.
- `validation.md` — the acceptance criteria to verify after implementation.

Also read `specs/mission.md` and `specs/tech-stack.md` for project-wide context.

### 3. Implement the plan

Execute each numbered task group in `plan.md` in order, top to bottom:

- Follow the plan faithfully — do not skip, reorder, or add tasks beyond what the plan specifies.
- Use `requirements.md` decisions to resolve ambiguity (e.g., component patterns, data sources, layout choices).
- After completing each task group, briefly tell the user what was done before moving to the next.
- If a task is unclear or blocked, ask the user before proceeding.

### 4. Run automated checks

After all plan tasks are complete, run the automated checks from the Technical section of `validation.md`:

1. `ruff check` (and `ruff format --check`) — lint / formatting.
2. `mypy` on the changed modules — type-checking.
3. A real run of `extract_code_from_video.py` on a test video, per the phase's exit criterion.

If any fail, fix the issues and re-run until all pass.

### 5. Validate acceptance criteria

Go through every checkbox in `validation.md`, section by section:

- **Automatable checks** (ruff, mypy, script run, output artifacts produced): run the command and mark pass/fail.

Present results as a checklist with status:

```
### Section Name
- [x] Check that passed (how it was verified)
- [x] Another passing check
- [ ] Manual check — requires user verification
```

- Update `validation.md`

### 6. Fix failures

If any automatable or inspectable check fails:

- Fix the issue.
- Re-run the failed check to confirm the fix.
- Update the checklist.

Repeat until all non-manual checks pass.

### 7. Summary

Print a final summary:

- Total checks: passed / total (excluding manual).
- List any manual checks the user still needs to verify.
- Remind the user to run `/finish-phase` when satisfied.
