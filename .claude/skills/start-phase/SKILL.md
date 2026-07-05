---
name: start-phase
description: Kick off the next incomplete roadmap phase: detect it from specs/roadmap.md, gather requirements via questions, then create the spec directory, branch, and spec files.
---

# Start phase

Kick off the next incomplete roadmap phase: gather requirements from the user, create a spec directory, branch, and spec files.

## Instructions

### 1. Detect next phase

- Read `specs/roadmap.md`.
- Find the first `## Phase N` heading that is **not** struck through (`~~`).
- Extract the phase number, name, and bullet list of items.
- If all phases are complete, tell the user and stop.
- Tell the user which phase was detected and list its bullets.

### 2. Ask the user about the feature spec

Use `AskUserQuestion` to ask **three grouped questions** before writing anything to disk:

**Question 1 — Scope**: Show the roadmap bullets for this phase and ask:

> "Here are the roadmap items for Phase N. Which items should be included, excluded, or modified? Any additional scope decisions?"
> Options: "Include all as-is", "I want to adjust scope" (+ let them type).

**Question 2 — Implementation approach**: Based on the phase content, ask:

> "Any preferences on the implementation approach? (e.g., module/function structure, OCR engine wiring, sampling strategy, data models, libraries)"
> Options: "You decide based on specs/tech-stack.md and specs/mission.md", "I have preferences" (+ let them type).

**Question 3 — Validation criteria**: Ask:

> "Any specific validation criteria beyond the standard checks (ruff, mypy, and a real script run)?"
> Options: "Standard checks are enough", "I have additional criteria" (+ let them type).

### 3. Create the spec directory

- Directory name: `specs/YYYY-MM-DD-<feature-slug>` using today's date and a kebab-case slug derived from the phase name (e.g., `2026-07-05-thin-vertical-slice`).

### 4. Write spec files

Use the user's answers, `specs/mission.md`, `specs/tech-stack.md`, the roadmap bullets, and the deliverables in `README.md` to write three files (in English, matching the rest of `specs/`):

**`requirements.md`**

- Title: `# Requirements — Phase N: <Phase Name>`
- Sections: Objective, Scope (Included / Excluded), Deliverables / output artifacts (if applicable), Decisions (table), Fidelity & error-handling rules (per `mission.md` and the README's error cases)
- Reflect the user's scope answers

**`plan.md`**

- Title: `# Plan — Phase N: <Phase Name>`
- Numbered task groups named after the work (e.g., 1. Data models, 2. Function/seam, 3. Pipeline wiring, 4. Outputs)
- Each group has a bullet list of concrete tasks
- Final group is always "Verification" with the ruff / mypy / script-run checks
- Reflect the user's implementation approach answers

**`validation.md`**

- Title: `# Validation — Phase N: <Phase Name>`
- Sections with `### Category` headings and `- [ ]` checkboxes
- Standard categories: Output artifacts, Metadata, OCR / fidelity, Error handling, Offline (no network), Technical (ruff, mypy, real script run)
- Add categories from the user's validation answers

### 5. Create branch

- Create and switch to a new branch: `phase-N-<slug>` (e.g., `phase-1-thin-vertical-slice`).

### 6. Summary

- Print a short summary: phase detected, spec directory created, branch name.
- Remind the user they can start implementing from the plan.
