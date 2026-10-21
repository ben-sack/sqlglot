---
name: first-contribution
description: >-
  Guides a new engineer or Cursor agent through SQLGlot issue intake,
  repository exploration, implementation planning, test-first development,
  and validation. Use when starting a contribution, picking up an issue,
  planning a change, or making a first edit in this repository.
---

# First contribution

Work one issue at a time. Do not implement from the issue title alone.

## 1. Issue intake

Read the issue, including acceptance criteria, test plan, and the file boundary.

- Record the issue id (`ACME-123`). The scope check looks for `Acme-Issue: ACME-123` in the pull request body, or that id alone in the title or branch name.
- Read the allowlist at `.github/acme/allowlists/ACME-123.txt` on the trusted base branch. Those paths are the only feature files this issue may change.
- If the allowlist is missing, stop and ask a maintainer. Do not invent a new allowlist on the feature branch.

## 2. Explore

Read `CONTRIBUTING.md`, `posts/onboarding.md`, and `posts/ast_primer.md` when the issue touches parsing or generation.

Then read the dialect chain that owns the behavior. For Spark and Databricks that is Hive, then Spark 2, then Spark, then Databricks. Confirm the current behavior with `parse_one` or an existing test before calling it a bug.

## 3. Plan

Write the plan before editing production code.

- Name the narrowest layer: base, Hive, Spark 2, Spark, or Databricks.
- Name the expression that already represents the syntax. Add a node only when none fits.
- List the test method to extend and the assertions, including one unchanged neighboring form.
- List files. Every feature file must already be on the issue allowlist. Protected policy paths cannot be added to that list.

Stop if the plan needs a file outside the allowlist.

## 4. Test first

Add or extend assertions with `validate_identity` or `validate_all` in the existing dialect test. Run that test and confirm the new assertion fails for the reason in the issue.

```bash
python -m unittest tests.dialects.test_databricks.TestDatabricks.<method>
```

Use the dialect and method the issue names. Do not start the production edit while the new test is still green.

## 5. Implement and validate

Edit only the planned files. Keep the production change smaller than the test.

```bash
python -m unittest <targeted-test-module>
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --issue ACME-123
ruff check <changed-python-files>
ruff format --check <changed-python-files>
```

Fetch `origin/main` first so `--base` is the trusted branch. Commit the branch first. The checker does not see uncommitted files. A local `--policy-actor` flag does not authorize anything.

The human author explains the diff, discloses LLM use, and opens the pull request. The agent does not merge.
