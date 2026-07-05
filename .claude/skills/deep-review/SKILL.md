---
name: deep-review
description: Deep multi-agent review of all changes on the current branch — fans out three subagents (correctness, code quality, product/frontend) over the branch diff and returns one prioritized findings report. Use when asked for a deep/thorough review of branch changes before merge.
---

# Deep review

Deep-review every change on the current branch (or a passed target) by fanning out three subagents, each reading the full diff from a different perspective, then merge their findings into one prioritized report.

## Instructions

### 1. Determine the review scope

- **If an argument was passed**, it names the review target instead of the current branch — resolve it first:
  - A **PR number** (`42` / `#42`) → use `gh pr diff <n>` for the diff and `gh pr view <n>` for title/description context.
  - A **branch name** → review that branch's diff against its merge-base with `main`.
  - A **path** (file or directory) → scope the diff to that path only.
- **With no argument**, review the current branch (default):
  - Run `git rev-parse --abbrev-ref HEAD` to get the current branch. If it is `main`, tell the user there is nothing to review against and stop.
  - Compute the merge base: `git merge-base main HEAD`.
  - Build the change set the subagents must review (committed **and** uncommitted work on this branch):
    - `git diff $(git merge-base main HEAD)` — full diff vs the merge base, includes working-tree changes.
    - `git diff $(git merge-base main HEAD) --stat` — file-level summary.
    - `git log main..HEAD --oneline` — the commits on this branch.
- If the resolved diff is empty, tell the user there are no changes to review and stop.
- Read `specs/mission.md` and `specs/tech-stack.md` (and, if a matching `specs/<date>-<slug>/` directory exists for this branch, its `requirements.md`) so you can hand the subagents the project's intent and conventions.

### 2. Pick the three perspectives

Use these three lenses by default. Adapt the emphasis to what the diff actually touches, but always keep them distinct so coverage does not overlap:

- **A — Correctness & bugs**: logic errors, broken behavior, unhandled edge cases, regressions, type-safety holes, async/state mistakes, broken or missing `next-intl` message keys, mismatches between `pt` and `en` data, runtime errors. "Does it actually work, and is anything subtly wrong?"
- **B — Code quality & consistency**: simplification, duplication that should be reused, dead code, naming, file/component structure, and whether the change follows the patterns already used elsewhere in the repo (component conventions, `data/` shape, Tailwind usage). "Is this the simplest, most consistent way to do it?"
- **C — Product & frontend quality**: UX, accessibility (semantics, keyboard, contrast, `aria-*`, alt text), responsiveness, i18n completeness (no hardcoded strings, locale-aware routing/metadata), SEO (metadata, `sitemap`, `opengraph`), and performance. "Is the end result good for the user in both languages?"

### 3. Spawn the three subagents in parallel

In a **single message**, launch three `general-purpose` agents — one per perspective. Give every agent the same shared context and a perspective-specific charge. Each prompt must include:

- The branch name, merge-base command, and the exact git commands from step 1 so the agent can regenerate the diff itself (do not paste a huge diff into the prompt — tell it to run the commands).
- The project intent from the spec files you read.
- This instruction block so each agent returns findings in a consistent shape:

  > You are doing a **read-only** review — do not edit, stage, or commit anything. Run the git commands above to see the full diff, then read the surrounding source files for any change you are unsure about (a diff hunk alone is not enough context). Review strictly from the **<PERSPECTIVE NAME>** perspective: <perspective description>.
  >
  > Return a markdown list of findings. For each finding give:
  >
  > - **Severity**: `high` (bug / breaks something / blocks merge), `medium` (should fix), or `low` (nice-to-have / nit).
  > - **Location**: `file:line` (clickable).
  > - **What**: the issue in one or two sentences.
  > - **Why / suggestion**: why it matters and a concrete fix.
  >
  > If the change is clean from your perspective, say so explicitly. Do not invent problems to fill space, and do not comment outside your perspective.

### 4. Merge and deduplicate

When all three agents return:

- Collect every finding into one list.
- Deduplicate: if two agents flag the same location/issue, keep one entry and note which perspectives raised it.
- Sort by severity (high → medium → low), then group by file.
- Drop anything that is clearly wrong (e.g., a "bug" that the surrounding code already handles) — verify questionable high-severity claims yourself by reading the file before including them.

### 5. Present the report

Print a single consolidated report:

```
## Deep review — <branch> (<N> files, <M> findings)

### High
- [ ] `file:line` — issue. _(A, C)_ Suggestion.

### Medium
- [ ] `file:line` — issue. _(B)_ Suggestion.

### Low / nits
- [ ] `file:line` — issue. _(B)_ Suggestion.
```

- Use clickable `[file.tsx:42](path#L42)` markdown links for every location.
- End with a one-line verdict: is the branch in good shape to merge, or are there blockers to address first?
- Do **not** apply any fixes. This skill only reports. Offer to fix specific findings if the user wants.
