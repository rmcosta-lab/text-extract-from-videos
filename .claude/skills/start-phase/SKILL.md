---
name: start-phase
description: Kick off the next incomplete roadmap phase: detect it from specs/roadmap.md, gather requirements via questions, then create the spec directory, branch, and spec files.
---

# Start phase

Kick off the next incomplete roadmap phase: gather requirements from the user, create a spec directory, branch, and spec files.

## Instructions

### 1. Detect next phase

- Read `specs/roadmap.md`.
- Find the first `## Fase N` heading that is **not** struck through (`~~`).
- Extract the phase number, name, and bullet list of items.
- If all phases are complete, tell the user and stop.
- Tell the user which phase was detected and list its bullets.

### 2. Ask the user about the feature spec

Use `AskUserQuestion` to ask **three grouped questions** before writing anything to disk:

**Question 1 — Scope**: Show the roadmap bullets for this phase and ask:

> "Here are the roadmap items for Fase N. Which items should be included, excluded, or modified? Any additional scope decisions?"
> Options: "Include all as-is", "I want to adjust scope" (+ let them type).

**Question 2 — Implementation approach**: Based on the phase content, ask:

> "Any preferences on the implementation approach? (e.g., component structure, data source, layout, libraries)"
> Options: "You decide based on specs/tech-stack.md and specs/mission.md", "I have preferences" (+ let them type).

**Question 3 — Validation criteria**: Ask:

> "Any specific validation criteria beyond build/lint/Lighthouse checks?"
> Options: "Standard checks are enough", "I have additional criteria" (+ let them type).

### 3. Create the spec directory

- Directory name: `specs/YYYY-MM-DD-<feature-slug>` using today's date and a kebab-case slug derived from the phase name.
- Follow the same naming pattern as existing directories (e.g., `2026-06-26-experiencia`, `2026-06-26-sobre`).

### 4. Write spec files

Use the user's answers, `specs/mission.md`, `specs/tech-stack.md`, and the roadmap bullets to write three files. Follow the same format and conventions as existing specs (e.g., `specs/2026-06-26-experiencia/`):

**`requirements.md`**

- Title: `# Requirements — Fase N: <Phase Name>`
- Sections: Objetivo, Escopo (Incluido / Excluido), Fonte de conteudo (if applicable), Decisoes (table), Diretrizes visuais
- Reflect the user's scope answers

**`plan.md`**

- Title: `# Plan — Fase N: <Phase Name>`
- Numbered task groups (1. Tipo e dados, 2. Componente, 3. Integracao, etc.)
- Each group has a bullet list of concrete tasks
- Final group is always "Verificacao" with build/lint/Lighthouse checks
- Reflect the user's implementation approach answers

**`validation.md`**

- Title: `# Validation — Fase N: <Phase Name>`
- Sections with `### Category` headings and `- [ ]` checkboxes
- Standard categories: Conteudo, Visual, Responsividade, Acessibilidade, Tecnico, Cross-browser
- Add categories from the user's validation answers
- Tecnico section always includes: `pnpm build` sem erros, `pnpm lint` sem warnings, Lighthouse performance >= 90, Lighthouse accessibility >= 90, sem erros no console

### 5. Create branch

- Create and switch to a new branch: `fase-N-<slug>` (e.g., `fase-5-polish-seo`).
- Follow the same naming pattern as previous phase branches.

### 6. Summary

- Print a short summary: phase detected, spec directory created, branch name.
- Remind the user they can start implementing from the plan.
