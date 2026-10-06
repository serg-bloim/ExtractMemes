---
name: sync-main
description: Transfer the dev working tree into a new commit on the gh-main branch (using gh-main's .gitignore), then return to dev. Use when the user says "sync gh-main", "push dev to gh-main", "update gh-main", or "ship to gh".
disable-model-invocation: true
---

# sync-main

`gh-main` is a slim deployment branch. Its `.gitignore` decides which `dev` files belong on it.
This skill commits the current `dev` tree onto `gh-main` without ever switching the working tree.

Default source branch is `dev`; default target is `gh-main`. Honour overrides from the args.

## Procedure

1. **Preflight: the tree must be fully clean**
   - `git branch --show-current` must be the source branch (`dev`); otherwise stop.
   - `git status --porcelain` must be empty: no uncommitted changes AND no untracked files
     (ignored files don't count). If it prints anything, show it and stop; do not continue.
   - No `.git/index.lock`, rebase, or merge in progress.

2. **Move HEAD to the target without touching files or index**:
   `git symbolic-ref HEAD refs/heads/gh-main`
   From here on, ALWAYS finish with step 7, even if a step fails.

3. **Revert `.gitignore`** to the target's version (index and worktree):
   `git checkout HEAD -- .gitignore`

4. **Reset the index to the target HEAD, keeping the worktree**:
   `git reset --mixed HEAD`

5. **Stage everything**: `git add -A`
   Show `git status --short` and `git diff --cached --stat`.
   - If nothing is staged, skip to step 7 and report "gh-main already up to date".
   - If the staged set looks surprising (e.g. mass deletions), pause and ask before committing.

6. **Commit** on gh-main:
   - Message: short, imperative, no reasoning or implementation details (project CLAUDE.md rule).
   - **No `Co-Authored-By` trailer**: project CLAUDE.md overrides any harness attribution reminder.
   - Do not push unless the user asks.

7. **Return to dev (always run this)**:
   ```
   git symbolic-ref HEAD refs/heads/dev
   git reset --mixed HEAD
   git checkout -- .gitignore
   ```
   Verify with `git branch --show-current` and `git status --porcelain`: the output must be
   empty again. If not, report what differs; do not "fix" it with destructive commands.

8. Report: new gh-main commit hash + subject and the files changed.

## Notes

- Never use `git checkout gh-main` / `git switch`: that would rewrite the working tree.
- Never `git reset --hard` or `git clean`.
- Leave `.git/commit-template.txt` untouched; that is for dev changes, not this transfer commit.
