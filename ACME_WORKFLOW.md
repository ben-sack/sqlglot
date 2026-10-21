# Acme engineering workflow

This fork uses SQLGlot's own conventions for how SQL is parsed and generated. Acme adds an issue allowlist, a scope check, and human approval on top. Cursor rules and skills explain the work. They do not block a bad diff.

## Start a contribution

1. Read the issue. It has an id such as `ACME-123`, acceptance criteria, and a test plan.
2. Open the [first-contribution](.cursor/skills/first-contribution/SKILL.md) skill and follow it: intake, explore, plan, failing test, then the production edit.
3. Confirm `.github/acme/allowlists/ACME-123.txt` already exists on the default branch. A feature branch cannot add its own allowlist.
4. Put `Acme-Issue: ACME-123` in the pull request body. The title or branch may also carry that id. Use one id only.

Local checks before opening the pull request:

```bash
python -m unittest tests.acme.test_check_change_scope
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --issue ACME-123
ruff check scripts/acme tests/acme
ruff format --check scripts/acme tests/acme
```

Fetch `origin/main` first. The scope check compares commits, so commit the branch before running it. Run the dialect test method the issue names, for example `python -m unittest tests.dialects.test_databricks.TestDatabricks.test_databricks`.

## Rules and skills

| Guidance | Where | Source |
|---|---|---|
| Pipeline and Hive → Spark2 → Spark → Databricks | `.cursor/rules/sqlglot-architecture.mdc` | SQLGlot |
| Narrowest dialect layer | `.cursor/rules/dialect-placement.mdc` | SQLGlot, with an Acme Spark-versus-Databricks boundary |
| AST reuse and generator methods | `.cursor/rules/ast-and-generator.mdc` | SQLGlot |
| `validate_identity` and `validate_all` | `.cursor/rules/sqlglot-testing.mdc` | SQLGlot, plus Acme test-first |
| Small pull requests and review | `.cursor/rules/review-and-prs.mdc` | SQLGlot, plus the Acme allowlist |
| Author owns LLM output | `.cursor/rules/ai-accountability.mdc` | SQLGlot `CONTRIBUTING.md`, plus the Acme scope check |
| How to implement an issue | `.cursor/skills/first-contribution/SKILL.md` | Acme workflow |
| How to examine a diff | `.cursor/skills/pre-review/SKILL.md` | Acme workflow |

Rules apply by themselves when they are always-on or when a matching file is in context. Skills apply when the task is a new contribution or a pre-review. Invoke them by name if the agent has not picked them up.

## Review and tests

Run the pre-review skill before requesting review. It reads the merge-base diff, runs the scope check, and writes a summary. That summary is not an approval.

Dialect changes use `validate_identity` or `validate_all` in the existing dialect test module. The new assertion should fail before the production edit and pass after it. Neighboring behavior that the issue does not change stays covered by the existing assertions.

ACME-101 is an Acme pilot, not a SQLGlot rule. `.github/acme/test-requirements/ACME-101.txt` on the trusted base says that a change to `sqlglot/parsers/databricks.py` must also change `tests/dialects/test_databricks.py`, and that test file must still exist on the pull request head. Deleting the test file does not satisfy the gate. The scope check reads this file from the base commit, so the feature branch cannot delete the requirement and then pass.

That pairing does not prove the tests are adequate. A comment-only edit of the test file satisfies it. Reviewers still have to read the assertions.

CI on a pull request:

- `Acme change scope` / `change-scope` reads the allowlist, the ACME-101 pairing, and the checker from the base commit. It rejects a parser-only ACME-101 diff. It does not execute the dialect tests, because that job must not run pull request code.
- `Acme targeted checks` / `targeted-checks` installs SQLGlot with `pip install -e ".[dev]"` so a clean runner can import the package. It runs ruff and `tests.acme.test_check_change_scope`. It then runs unittest for changed test modules. When the base pairing file lists a production file that this pull request changed, it also runs that paired test module. For ACME-101 that is `tests.dialects.test_databricks`, including when the pull request changed the parser and not the test file.

## Advisory versus enforced

| Check | What it can stop | Enforced by |
|---|---|---|
| `.cursor/rules/` and skills | Nothing by themselves. An agent can ignore them. | Advisory |
| Pre-review summary | Nothing by itself. | Advisory |
| `acme-targeted-checks.yml` | Style and test failures in the copy of the workflow that the pull request ran. The author can edit that file. | Advisory as a security boundary. Optional required status check only. |
| `scripts/acme/check_change_scope.py` in `acme-change-scope.yml` | Files outside the base allowlist, mixed feature and policy diffs, protected paths, an allowlist that grants a protected path, and an ACME-101 parser diff that does not also change `tests/dialects/test_databricks.py`. | Executable check. It runs from the default branch via `pull_request_target` and does not execute pull request code. |
| GitHub branch protection | Merge while `change-scope` is failing, and merge of a policy diff without a review. | Repository setting. Not something this repository file can turn on. |
| `author_association` of `OWNER` or `MEMBER` | Policy-only edits from contributors. | GitHub permission data passed into the checker. A local `--policy-actor` flag does not grant rights. |
| CODEOWNERS review | A maintainer merging a policy diff that weakens the checker or empties the protected-path floor. | GitHub setting Acme still has to configure. |

The protected floor hardcoded in `scripts/acme/check_change_scope.py` covers `.github/acme/`, the two Acme workflows, `scripts/acme/`, `tests/acme/`, `.cursor/`, and `ACME_WORKFLOW.md`. `.github/acme/protected-paths.txt` can add paths. It cannot remove that floor. Removing the floor means editing the script, which is a policy change reviewed on the old checker before it can take effect.

The ACME-101 pairing is a presence check. It does not read the test body, so it cannot tell a real regression assertion from a blank line. `targeted-checks` is the job that executes `tests.dialects.test_databricks`, and a pull request can edit that workflow. Human review is still required to decide whether the test change matches the parser change.

## Human approval

- Feature pull request: scope check passes, targeted tests pass, and a human reviewer who can explain the diff approves it.
- Policy pull request (allowlists, this document, rules, skills, the checker, or its workflow): a GitHub owner or member opens it, it changes no feature files, and a second person approves it. The script's success line still says human review is required.
- Disclose LLM use in the pull request. The author owns the lines.
- Nobody merges their own policy change by bypassing the required check except as a recorded admin break-glass.

## Extend the workflow

1. Add `.github/acme/allowlists/ACME-456.txt` in a policy pull request. One exact relative path per line. No globs, directories, or protected paths. To require a test file whenever a production file changes, add `.github/acme/test-requirements/ACME-456.txt` in that same policy pull request, with one `production-file test-file` pair per line. The ACME-101 pair is the pilot.
2. Merge that pull request to the default branch before the feature branch opens.
3. Add a Cursor rule or skill only when the guidance is reused across issues. Keep SQLGlot facts labeled as SQLGlot, and Acme-only gates labeled as Acme.
4. Extend `tests/acme/test_check_change_scope.py` when the checker changes, and keep the documented commands in this file in sync with CI.

Upstream syncs that touch files outside an allowlist fail closed. Give that sync its own allowlist, or use the admin break-glass. Do not weaken the checker to land it.

## Manual GitHub and Cursor setup

These are not applied by the files in this repository:

- Default branch includes this workflow, then branch protection requires the `change-scope` status check. Turn off bypass except for admins, and require one approval.
- Add CODEOWNERS for `.github/acme/`, `.github/workflows/acme-change-scope.yml`, `.github/workflows/acme-targeted-checks.yml`, `scripts/acme/`, `tests/acme/`, `.cursor/`, and `ACME_WORKFLOW.md`, using real Acme identities.
- Decide whether `targeted-checks` is a required status check. Required or not, it is not the security boundary.
- For private repositories, leave the workflow token at `contents: read`.
- First-time contributor workflow approval, if enabled, delays `pull_request_target` until a maintainer approves the run.
- Cursor project rules and skills are picked up from `.cursor/` after the branch is checked out. No separate Cursor dashboard setting is required for this layout. Cloud agents need this framework on the branch they start from.
