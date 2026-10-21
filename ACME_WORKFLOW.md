# Acme workflow

This fork uses SQLGlot's own conventions for how SQL is parsed and generated. Acme adds repository governance on top: protected paths, mapped regression tests, and human approval. Cursor rules and skills explain the work. They do not block a bad diff.

## Normal change

1. Read the issue and reproduce the behavior.
2. Write the implementation plan, including the files you expect to touch and the dialects that inherit them.
3. Implement. A behavior change gets a regression assertion. A documentation or refactor change may not, and the pull request says which it is.
4. Fetch the default branch and commit. The scope check compares commits, not uncommitted files.

```bash
python -m unittest tests.acme.test_check_change_scope
python scripts/acme/check_change_scope.py --base origin/main --head HEAD
python scripts/acme/check_change_scope.py --base origin/main --head HEAD --print-tests
ruff check scripts/acme tests/acme
ruff format --check scripts/acme tests/acme
```

`--print-tests` prints one unittest module per line. `FALLBACK` means run `SKIP_INTEGRATION=1 python -m unittest`. Run those tests before review.

There is no per-ticket file list. An ordinary feature pull request may change additional source and test files. It may not also change governance files. Growth into another subsystem belongs in the pull request explanation.

## What is guidance and what is enforced

| Artifact | What it says | What it can do |
| --- | --- | --- |
| `.cursor/rules/*.mdc` | SQLGlot architecture, dialect placement, AST style, tests, review, and accountability | Advisory. Cursor loads it. GitHub does not. |
| `.cursor/skills/first-contribution/SKILL.md` | Investigate, assess risk, plan, implement, explain scope, and hand off | Advisory. The agent can still edit the wrong file. |
| `.cursor/skills/pre-review/SKILL.md` | Independent review checklist and a stable summary template | Advisory. It does not approve or merge. A later Cloud Agent or pull request automation can invoke this same skill. That automation is not in this repository. |
| `scripts/acme/check_change_scope.py` in `acme-change-scope.yml` | Protected governance files, mixed feature and policy diffs, and unverifiable git refs | Executable check. It runs from the default branch via `pull_request_target` and does not execute pull request code. |
| `acme-targeted-checks.yml` | Ruff, the guardrail tests, mapped dialect tests, and the unit-suite fallback | Quality signal. The workflow file comes from the pull request, so it is not a security boundary. |

The two GitHub Actions job names stay `change-scope` and `targeted-checks`.

## Protected paths

Ordinary feature work stays out of:

- `.github/workflows/`
- `.github/acme/`
- `.github/CODEOWNERS`, `docs/CODEOWNERS`, and `CODEOWNERS`
- `scripts/acme/`
- `tests/acme/`
- `.cursor/`
- `ACME_WORKFLOW.md`

That floor is hardcoded in `scripts/acme/check_change_scope.py`. `.github/acme/protected-paths.txt` can add paths. It cannot remove the floor. Both are read from the base commit.

A pull request that edits only those files is a policy change. The author must be a GitHub owner or member (`author_association` of `OWNER` or `MEMBER`). The success line still says human review is required. A second person approves it. A local `--policy-actor` flag does not grant that right.

A pull request that mixes a protected file with feature code fails, including for an owner. That stops a feature branch from editing the checker, the mappings, or CI and then judging itself by the weaker copy. `change-scope` executes the checker from the trusted base checkout.

## Test mappings

`.github/acme/test-mappings.txt` pairs production paths with unittest modules. The current map sends Databricks parser, generator, dialect, and typing files to `tests.dialects.test_databricks`, and the Spark and Spark 2 counterparts to `tests.dialects.test_spark`.

`targeted-checks` loads the checker and this map from the base commit. A changed test module is also executed when it still exists. Unmapped `sqlglot/**/*.py` changes select `FALLBACK` and run the unit suite. Documentation-only diffs do not select tests. The map does not require a test file to change, and it does not prove the assertions cover the diff. The pre-review skill and the human reviewer still look at test adequacy.

## Bootstrap and policy updates

This framework has to be on the default branch before `pull_request_target` can run it. The first merge is itself a policy change: an owner or member opens it, and a second maintainer reviews it. Until the workflow exists on the default branch, GitHub will not run `change-scope`. If branch protection already requires that check, an admin has to bypass it once for this introducing pull request.

That introducing pull request is based on a commit that has neither `.github/acme/test-mappings.txt` nor `--print-tests`. `targeted-checks` still runs Ruff and `tests.acme.test_check_change_scope`. It skips mapped dialect selection only because the diff is governance-only. If that same base cannot select tests and the diff includes `sqlglot/**/*.py` or a test module outside `tests/acme/`, the job fails instead of skipping. After the merge, later pull requests select tests with the checker and mappings from the trusted base.

After that, update governance only through a policy pull request:

- Add or change a row in `.github/acme/test-mappings.txt`.
- Add a path to `.github/acme/protected-paths.txt`.
- Change the checker, its tests, the workflows, Cursor guidance, or this document.

Do not put those edits on a feature branch. Feature work after the merge is judged by the policy that was already on the base.

## Limits

- Cursor rules and skills do not stop a model from editing a file.
- `change-scope` does not run dialect tests. `targeted-checks` does, and a pull request can edit that workflow.
- `FALLBACK` runs the unit suite, not a proof that every affected dialect was tested.
- A reviewed policy pull request can still weaken the checker. The previous checker runs until that pull request merges.
- Missing or unverifiable base and head refs fail closed.
- Branch protection, a required `change-scope` check, CODEOWNERS, and the one-time admin bypass are GitHub settings. This repository cannot turn them on.
