---
name: first-contribution
description: >-
  Guides a new engineer or Cursor agent through SQLGlot issue investigation,
  regression planning, implementation, validation, and handoff to independent
  review. Use when starting a contribution, picking up an issue, planning a
  change, or making a first edit in this repository.
---

# First contribution

Work one issue at a time. Do not implement from the issue title alone, and do not silently expand into an unrelated subsystem.

## 1. Investigate the issue

Read the issue, including acceptance criteria and the test plan. Reproduce the current behavior with `parse_one` or an existing test before calling it a bug.

Read `CONTRIBUTING.md`, `posts/onboarding.md`, and `posts/ast_primer.md` when the issue touches parsing or generation. For Spark and Databricks, read the chain Hive, then Spark 2, then Spark, then Databricks.

## 2. Identify likely code changes and regression risks

Name the narrowest layer that owns the behavior: base, Hive, Spark 2, Spark, or Databricks. Name the existing expression that already represents the syntax.

List the dialects that inherit that layer. A Databricks-only change that edits `sqlglot/parser.py` is a wider risk than a change in `sqlglot/parsers/databricks.py`.

## 3. Produce an implementation plan

Write the plan before editing production code.

- Files you expect to change, and why each one is in scope.
- Test method to extend, using `validate_identity` or `validate_all`, plus one neighboring assertion that must stay unchanged.
- Governance files you will not touch: `.github/workflows/`, `.github/acme/`, `scripts/acme/`, `tests/acme/`, `.cursor/`, and `ACME_WORKFLOW.md`.

Source: SQLGlot owns the parser, AST, and generator conventions. Source: Acme policy owns the protected paths and the mapped CI tests. There is no per-ticket file allowlist. Discovering one more file in the same subsystem during implementation is normal. Discovering that the fix belongs in another subsystem means stop and revise the plan in the open.

## 4. Implement and validate

Prefer a failing test before the production edit when the issue changes behavior. Documentation and refactoring may not need a new test. Say which of those it is.

```bash
python -m unittest tests.dialects.test_databricks.TestDatabricks.<method>
python scripts/acme/check_change_scope.py --base origin/main --head HEAD
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --print-tests
ruff check <changed-python-files>
ruff format --check <changed-python-files>
```

Fetch `origin/main` first. Commit before the scope check. It compares commits and reads protected paths from the base. A local `--policy-actor` flag does not grant merge rights.

Run the unittest modules printed by `--print-tests`. `FALLBACK` means `SKIP_INTEGRATION=1 python -m unittest`.

## 5. Explain any meaningful expansion in scope

If the diff touches a file, dialect, or subsystem that the plan did not name, say what was learned and why the extra change is required. Do not leave that explanation for the reviewer to infer.

## 6. Prepare the change for independent review

Summarize the behavior change, the tests run, and any scope expansion. Disclose LLM use. The author owns the lines. Hand the diff to the pre-review skill or a human reviewer. Do not merge.
