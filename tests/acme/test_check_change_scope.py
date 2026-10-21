"""Tests for the Acme change-scope guardrail."""

from __future__ import annotations

import importlib.util
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

PERMITTED = (
    "sqlglot/parsers/databricks.py",
    "tests/dialects/test_databricks.py",
)


def load_checker():
    spec = importlib.util.spec_from_file_location("check_change_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


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
            (ROOT / ".github/acme/protected-paths.txt").read_text(encoding="utf-8"),
        )
        self.write(
            ".github/acme/allowlists/ACME-101.txt",
            "".join(f"{path}\n" for path in PERMITTED),
        )
        for path in PERMITTED:
            self.write(path, "original = 1\n")
        self.write("scripts/acme/check_change_scope.py", "# trusted checker\n")
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
        for name in ("ACME_ACTOR", "PR_TITLE", "PR_BODY", "HEAD_REF"):
            env.pop(name, None)
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

    def pair_databricks_tests(self) -> None:
        self.write(
            ".github/acme/test-requirements/ACME-101.txt",
            "sqlglot/parsers/databricks.py tests/dialects/test_databricks.py\n",
        )
        self.commit("pair")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def test_parser_change_without_test_change_fails(self) -> None:
        self.pair_databricks_tests()
        self.branch({"sqlglot/parsers/databricks.py": "changed = 1\n"})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Pilot test pairing failed", result.stderr)
        self.assertIn("tests/dialects/test_databricks.py", result.stderr)

    def test_parser_change_with_test_change_passes(self) -> None:
        self.pair_databricks_tests()
        self.branch({path: "changed = 1\n" for path in PERMITTED})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("change-scope: OK issue=ACME-101", result.stdout)

    def test_unauthorized_file_still_rejected_when_pairing_is_present(self) -> None:
        self.pair_databricks_tests()
        self.branch({"sqlglot/parser.py": "changed = 1\n"})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unauthorized", result.stderr)
        self.assertIn("sqlglot/parser.py", result.stderr)

    def test_accepts_permitted_files(self) -> None:
        self.branch({path: "changed = 1\n" for path in PERMITTED})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("change-scope: OK issue=ACME-101", result.stdout)

    def test_rejects_unauthorized_file(self) -> None:
        self.branch({"sqlglot/parser.py": "changed = 1\n"})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1)
        self.assertIn("sqlglot/parser.py", result.stderr)
        self.assertIn("Unauthorized", result.stderr)

    def test_rejects_protected_policy_file(self) -> None:
        self.branch({".github/acme/allowlists/ACME-101.txt": "sqlglot/parser.py\n"})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/acme/allowlists/ACME-101.txt", result.stderr)
        self.assertIn("Protected policy files", result.stderr)

    def test_rejects_allowlist_bypass_on_head(self) -> None:
        self.branch(
            {
                ".github/acme/allowlists/ACME-101.txt": "sqlglot/parser.py\n",
                "sqlglot/parser.py": "changed = 1\n",
            }
        )
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("sqlglot/parser.py", result.stderr)
        self.assertIn(".github/acme/allowlists/ACME-101.txt", result.stderr)

    def test_rejects_protected_path_even_when_allowlisted(self) -> None:
        self.write(
            ".github/acme/allowlists/ACME-101.txt",
            "sqlglot/parsers/databricks.py\nscripts/acme/check_change_scope.py\n",
        )
        self.commit("bad allowlist")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.branch({"sqlglot/parsers/databricks.py": "changed = 1\n"})
        result = self.check("--issue", "ACME-101")
        self.assertEqual(result.returncode, 1)
        self.assertIn("grants protected path scripts/acme/check_change_scope.py", result.stderr)

    def test_policy_change_requires_maintainer_and_still_asks_for_review(self) -> None:
        self.branch({".github/acme/allowlists/ACME-102.txt": "README.md\n"})
        denied = self.check("--issue", "ACME-102")
        self.assertEqual(denied.returncode, 1)
        allowed = self.check("--issue", "ACME-102", "--policy-actor", "MEMBER")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("Human review is still required", allowed.stdout)

    def test_repository_allowlist_is_exact(self) -> None:
        text = (ROOT / ".github/acme/allowlists/ACME-101.txt").read_text(encoding="utf-8")
        self.assertEqual(CHECKER.strip_entries(text), list(PERMITTED))
        requirements = (ROOT / ".github/acme/test-requirements/ACME-101.txt").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            CHECKER.strip_entries(requirements),
            ["sqlglot/parsers/databricks.py tests/dialects/test_databricks.py"],
        )
        for rule in CHECKER.HARDCODED_PROTECTED:
            sample = rule if not rule.endswith("/") else f"{rule}owned-by-policy.txt"
            self.assertTrue(CHECKER.is_protected(sample, CHECKER.HARDCODED_PROTECTED))

    def test_workflow_and_docs_name_the_enforced_command(self) -> None:
        scope = SCOPE_WORKFLOW.read_text(encoding="utf-8")
        targeted = TARGETED_WORKFLOW.read_text(encoding="utf-8")
        doc = WORKFLOW_DOC.read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", scope)
        self.assertIn("contents: read", scope)
        self.assertIn("github.event.pull_request.base.sha", scope)
        self.assertNotIn("github.event.pull_request.head.sha", scope)
        self.assertIn("scripts/acme/check_change_scope.py", scope)
        self.assertIn('pip install -e ".[dev]"', targeted)
        self.assertIn(".github/acme/test-requirements", targeted)
        self.assertIn("ruff check scripts/acme tests/acme", targeted)
        self.assertIn("python -m unittest tests.acme.test_check_change_scope", targeted)
        self.assertIn("python -m unittest tests.acme.test_check_change_scope", doc)
        self.assertIn(
            "python scripts/acme/check_change_scope.py --base origin/main --head HEAD --issue ACME-123",
            doc,
        )
        self.assertIn("ruff check scripts/acme tests/acme", doc)
        self.assertIn("ruff format --check scripts/acme tests/acme", doc)


if __name__ == "__main__":
    unittest.main()
