"""Tests for repository-level Acme scope and test selection."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "acme" / "check_change_scope.py"
SCOPE_WORKFLOW = ROOT / ".github" / "workflows" / "acme-change-scope.yml"
TARGETED_WORKFLOW = ROOT / ".github" / "workflows" / "acme-targeted-checks.yml"
WORKFLOW_DOC = ROOT / "ACME_WORKFLOW.md"
MAPPINGS = ROOT / ".github" / "acme" / "test-mappings.txt"


class ChangeScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        self.git_env = os.environ.copy()
        self.git_env.update(
            {
                "GIT_AUTHOR_NAME": "Acme Test",
                "GIT_AUTHOR_EMAIL": "acme@example.com",
                "GIT_COMMITTER_NAME": "Acme Test",
                "GIT_COMMITTER_EMAIL": "acme@example.com",
            }
        )
        self.git("init", "-b", "main", "--template=")
        self.write(
            ".github/acme/protected-paths.txt",
            (ROOT / ".github/acme/protected-paths.txt").read_text(),
        )
        self.write(".github/acme/test-mappings.txt", MAPPINGS.read_text(encoding="utf-8"))
        self.write("sqlglot/parsers/databricks.py", "original = 1\n")
        self.write("sqlglot/generators/databricks.py", "original = 1\n")
        self.write("sqlglot/parsers/spark.py", "original = 1\n")
        self.write("sqlglot/parser.py", "original = 1\n")
        self.write("scripts/acme/check_change_scope.py", "original = 1\n")
        self.write(".github/workflows/acme-change-scope.yml", "name: change-scope\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", "-C", self.repo, *args],
            check=False,
            capture_output=True,
            text=True,
            env=self.git_env,
        )
        if completed.returncode != 0:
            raise AssertionError(f"git {args} failed\n{completed.stderr}")
        return completed

    def write(self, path: str, content: str) -> None:
        target = Path(self.repo) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", message)

    def branch(self, files: dict[str, str]) -> None:
        self.git("checkout", "-b", "feature")
        for path, content in files.items():
            self.write(path, content)
        self.commit("feature")

    def check(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("ACME_ACTOR", None)
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                self.repo,
                "--base",
                self.base,
                "--head",
                "HEAD",
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_feature_can_add_a_source_file_without_an_allowlist(self) -> None:
        self.branch(
            {
                "sqlglot/parsers/databricks.py": "changed = 1\n",
                "sqlglot/generators/databricks.py": "changed = 1\n",
            }
        )
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("change-scope: OK feature files=2", result.stdout)
        self.assertFalse((ROOT / ".github/acme/allowlists/ACME-101.txt").exists())

    def test_databricks_parser_selects_databricks_tests(self) -> None:
        self.branch({"sqlglot/parsers/databricks.py": "changed = 1\n"})
        result = self.check("--print-tests")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["tests.dialects.test_databricks"])

    def test_spark_parser_selects_spark_tests(self) -> None:
        self.branch({"sqlglot/parsers/spark.py": "changed = 1\n"})
        result = self.check("--print-tests")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["tests.dialects.test_spark"])

    def test_unmapped_production_change_uses_fallback(self) -> None:
        self.branch({"sqlglot/parser.py": "changed = 1\n"})
        result = self.check("--print-tests")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "FALLBACK")

    def test_changed_test_module_is_selected(self) -> None:
        self.write("tests/dialects/test_databricks.py", "original = 1\n")
        self.commit("add test")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.branch({"tests/dialects/test_databricks.py": "changed = 1\n"})
        result = self.check("--print-tests")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests.dialects.test_databricks", result.stdout.splitlines())

    def test_feature_pr_cannot_modify_any_codeowners_file(self) -> None:
        self.write(".github/acme/protected-paths.txt", "# extra paths removed\n")
        self.commit("rely on hardcoded floor")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        for path in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            with self.subTest(path=path):
                self.git("checkout", "-B", "feature", self.base)
                self.write("sqlglot/parsers/databricks.py", "changed = 1\n")
                self.write(path, "* @acme/owners\n")
                self.commit("feature")
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"Protected:\n  {path}", result.stderr)
                self.assertIn("Mixed policy and feature changes", result.stderr)
                self.assertNotIn("change-scope: OK", result.stdout)

    def test_feature_pr_cannot_modify_protected_ci(self) -> None:
        self.branch(
            {
                "sqlglot/parsers/databricks.py": "changed = 1\n",
                ".github/workflows/acme-change-scope.yml": "name: disabled\n",
            }
        )
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/workflows/acme-change-scope.yml", result.stderr)
        self.assertIn("Mixed policy and feature changes", result.stderr)

    def test_feature_pr_cannot_weaken_the_checker(self) -> None:
        self.branch(
            {
                "scripts/acme/check_change_scope.py": "import sys\nsys.exit(0)\n",
                "sqlglot/parsers/databricks.py": "changed = 1\n",
            }
        )
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("scripts/acme/check_change_scope.py", result.stderr)
        self.assertNotIn("change-scope: OK", result.stdout)

    def test_policy_only_change_remains_possible_for_a_maintainer(self) -> None:
        self.branch({".github/acme/test-mappings.txt": MAPPINGS.read_text(encoding="utf-8") + "\n"})
        denied = self.check()
        self.assertEqual(denied.returncode, 1)
        self.assertIn("Protected governance files", denied.stderr)
        allowed = self.check("--policy-actor", "MEMBER")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("Human review is still required", allowed.stdout)

    def test_unverifiable_git_reference_fails_closed(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                self.repo,
                "--base",
                "does-not-exist",
                "--head",
                "HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unverifiable git reference", result.stderr)

    def test_ticket_policy_files_are_gone_and_jobs_keep_their_names(self) -> None:
        self.assertFalse((ROOT / ".github/acme/allowlists/ACME-101.txt").exists())
        self.assertFalse((ROOT / ".github/acme/test-requirements/ACME-101.txt").exists())
        self.assertIn(
            "sqlglot/parsers/databricks.py tests.dialects.test_databricks", MAPPINGS.read_text()
        )
        scope = SCOPE_WORKFLOW.read_text(encoding="utf-8")
        targeted = TARGETED_WORKFLOW.read_text(encoding="utf-8")
        doc = WORKFLOW_DOC.read_text(encoding="utf-8")
        self.assertIn("name: change-scope", scope)
        self.assertIn("pull_request_target:", scope)
        self.assertIn("contents: read", scope)
        self.assertIn("github.event.pull_request.base.sha", scope)
        self.assertNotIn("github.event.pull_request.head.sha", scope)
        self.assertIn("name: targeted-checks", targeted)
        self.assertIn('pip install -e ".[dev]"', targeted)
        self.assertIn("--print-tests", targeted)
        self.assertIn('git show "$BASE_SHA:scripts/acme/check_change_scope.py"', targeted)
        self.assertIn("python -m unittest tests.acme.test_check_change_scope", doc)
        self.assertIn(
            "python scripts/acme/check_change_scope.py --base origin/main --head HEAD",
            doc,
        )
        self.assertNotIn("allowlists/ACME-101.txt", doc)
        self.assertIn("ruff check scripts/acme tests/acme", doc)
        self.assertIn("ruff format --check scripts/acme tests/acme", doc)


if __name__ == "__main__":
    unittest.main()
