---
name: pre-review
description: >-
  Independently reviews a SQLGlot diff for dialect ownership, regression
  risk, test adequacy, deprecated APIs, unexplained changes, and security
  or dependency concerns. Use before opening or approving a pull request,
  when asked to pre-review, or when a Cursor Cloud Agent or pull request
  automation invokes this skill. Does not edit code or merge.
---

# Pre-review

Review the full diff against the trusted base. Do not treat the author's summary as evidence. Do not edit files, approve, or merge. This skill is the review contract a later Cloud Agent or pull request automation can call. That automation is not part of this repository yet.

Inputs are the base ref and the head ref. The default base is `origin/main`.

## 1. Collect the diff

```bash
git fetch origin main
base=$(git merge-base origin/main HEAD)
git diff --name-status -M "$base" HEAD
git diff -M "$base" HEAD
python scripts/acme/check_change_scope.py --base origin/main --head HEAD
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --print-tests
```

A scope-check failure is blocking. Cursor rules and this skill are not a substitute for that command. `--print-tests` lists the modules CI should run. `FALLBACK` means the unit suite, because a production file had no mapping.

## 2. Evaluate

- Architectural conventions and dialect ownership. The edit sits on the narrowest layer. Databricks-only syntax stays on Databricks. Spark syntax that Databricks should inherit stays on Spark.
- Regression risks and test adequacy. Mapped dialect tests ran, or the fallback suite ran. A missing new assertion is a finding when behavior changed. A refactor or doc change may not need a new test; say which it is. Running a test file does not prove the assertions cover the diff.
- Deprecated APIs and anti-patterns. New `exp.Anonymous` nodes, f-string SQL, a `TRANSFORMS` entry that should be an `<expr>_sql` method, and edits that fight recursive descent.
- Unnecessary or unexplained changes. Files outside the stated issue, formatting-only churn, and scope that grew without an explanation.
- Security and dependency concerns. Governance files mixed into a feature diff, new dependencies, and workflow permissions broader than `contents: read`.
- Downstream dialects. Name the dialects that inherit the edited layer and whether their tests were selected.

## 3. Write the summary

Use these headings so a later automation can read them:

```markdown
## Pre-review
- Scope check:
- Tests selected:
- Dialect ownership:
- Test adequacy:
- Anti-patterns:
- Unexplained changes:
- Security and dependencies:
- Downstream dialects:
- Blocking:
- Questions for the human reviewer:
```

Blocking means the scope check failed, behavior changed without a relevant test, or the diff reaches an unrelated subsystem. Questions are not approvals. A human reviewer still approves the pull request.
