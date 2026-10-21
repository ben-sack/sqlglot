---
name: pre-review
description: >-
  Independently reviews a SQLGlot diff for conventions, tests, and
  regression risk, then writes a review summary. Use before opening or
  approving a pull request, when asked to pre-review, or when checking
  that a change stays inside its issue allowlist.
---

# Pre-review

Review the full diff against the trusted base. Do not treat the author's summary as evidence. Do not approve or merge.

## 1. Collect the diff

```bash
git fetch origin main
base=$(git merge-base origin/main HEAD)
git diff --name-status -M "$base" HEAD
git diff -M "$base" HEAD
```

Read the issue id from the pull request body (`Acme-Issue: ACME-123`), the title, or the branch. Then run:

```bash
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --issue ACME-123
```

A failure here is a blocking finding. Cursor rules and skills are not a substitute for this command.

## 2. Check the change

- The production edit matches the issue and sits on the narrowest dialect layer.
- Existing expression types are reused. Generator methods follow `<expr>_sql`, and `TRANSFORMS` is only a one-liner.
- Tests use `validate_identity` or `validate_all` and cover the new form plus one unchanged neighbor.
- Unrelated dialects are untouched. A Databricks-only issue must not edit `sqlglot/parser.py` or another dialect's tests.
- The author can explain the diff. LLM use is disclosed. The pull request does one thing.

## 3. Regression risks

Name the behavior that could change accidentally: inherited dialects, shared style sets, token types, and canonical SQL that existing identity tests pin. Call out a risk only when the diff can reach it.

## 4. Write the summary

```markdown
## Pre-review
- Issue:
- Scope check: pass or fail, with the command result
- Intent of the diff:
- Conventions:
- Tests run:
- Regression risks:
- Blocking:
- Questions for the human reviewer:
```

Blocking means the scope check failed, tests are missing, or behavior outside the issue changed. Questions are not approvals. A human reviewer still approves the pull request.
