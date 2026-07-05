---
name: changelog
description: Update the project's CHANGELOG.md from git history before merging or releasing.
---

# Changelog

Update the project's CHANGELOG.md before merging.

## Instructions

1. **If `CHANGELOG.md` does not exist** in the project root:
   - Run `git log --format="%ad %s" --date=short` to collect all commit history.
   - Group commits by date (newest first).
   - Create `CHANGELOG.md` with one `## YYYY-MM-DD` heading per date, and a bullet for each commit under it.

2. **If `CHANGELOG.md` already exists**:
   - Determine the most recent date heading already in the file.
   - Run `git log --format="%ad %s" --date=short` and collect commits whose date is **after** that most recent heading.
   - If there are no new commits, check `git diff --cached --stat` and `git diff --stat` for uncommitted changes. If there are uncommitted staged/unstaged changes, ask the user what changelog entry to add for today.
   - If there are new commits, group them by date and prepend new `## YYYY-MM-DD` sections (newest first) at the top of the changelog, below any existing front-matter or title.
   - If today's date heading already exists, append new bullets to it instead of creating a duplicate heading.

3. **Formatting rules**:
   - First line: `# Changelog`
   - One blank line, then date sections.
   - Date sections use `## YYYY-MM-DD` format.
   - Each entry is a `- ` bullet with a concise description (rewrite raw commit messages into human-readable form if needed).
   - Newest dates first.

4. **After updating**, show the user the diff of CHANGELOG.md so they can review before committing.
