"""Reject feature diffs that edit protected governance files.

Policy is read from the trusted base revision. A feature pull request cannot
replace this checker or its mappings and then be judged by that replacement.
Ordinary source and test files do not need a per-ticket allowlist.
"""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import subprocess
import sys

POLICY_ACTORS = frozenset({"OWNER", "MEMBER"})
MAPPING_FILE = ".github/acme/test-mappings.txt"
CHECKER_PATH = "scripts/acme/check_change_scope.py"
PROTECTED_FILE = ".github/acme/protected-paths.txt"
FALLBACK = "FALLBACK"
MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# Floor used even when protected-paths.txt is emptied or missing.
HARDCODED_PROTECTED = (
    ".github/workflows/",
    ".github/acme/",
    ".github/CODEOWNERS",
    "docs/CODEOWNERS",
    "CODEOWNERS",
    "scripts/acme/",
    "tests/acme/",
    ".cursor/",
    "ACME_WORKFLOW.md",
)


class ScopeError(Exception):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def run_git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def git_bytes(repo: str, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", repo, *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ScopeError(f"git {' '.join(args)} failed: {detail}", exit_code=2)
    return completed.stdout


def git_show(repo: str, revision: str, path: str) -> str | None:
    completed = run_git(repo, "show", f"{revision}:{path}", check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout


def verify_refs(repo: str, base: str, head: str) -> None:
    for revision in (base, head):
        completed = run_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}", check=False)
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ScopeError(f"Unverifiable git reference: {revision}", exit_code=2)


def merge_base(repo: str, base: str, head: str) -> str:
    completed = run_git(repo, "merge-base", base, head, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ScopeError(
            f"Cannot find merge base of {base} and {head}. Fetch the trusted base first.",
            exit_code=2,
        )
    return completed.stdout.strip()


def changed_paths(repo: str, base: str, head: str) -> list[str]:
    """Return every path added, removed, or renamed between the merge base and head."""
    verify_refs(repo, base, head)
    ancestor = merge_base(repo, base, head)
    raw = git_bytes(repo, "diff", "-z", "--name-status", "-M", ancestor, head)
    parts = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(parts) and parts[index] != b"":
        status = parts[index].decode("utf-8")
        index += 1
        if status.startswith(("R", "C")):
            old = parts[index].decode("utf-8")
            new = parts[index + 1].decode("utf-8")
            index += 2
            paths.extend((old, new))
        else:
            paths.append(parts[index].decode("utf-8"))
            index += 1
    return paths


def strip_entries(text: str) -> list[str]:
    entries: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def is_protected(path: str, rules: tuple[str, ...]) -> bool:
    for rule in rules:
        if rule.endswith("/"):
            if path.startswith(rule) or f"{path}/" == rule:
                return True
        elif path == rule:
            return True
    return False


def protected_rules(text: str | None) -> tuple[str, ...]:
    extra = tuple(strip_entries(text or ""))
    return tuple(dict.fromkeys((*HARDCODED_PROTECTED, *extra)))


def normalize_pattern(path: str) -> str:
    directory = path.endswith("/")
    raw = path[:-1] if directory else path
    if raw.startswith(("/", "~", "-")) or "\\" in raw or any(char in raw for char in "*?["):
        raise ScopeError(f"Mapping path must be a relative repo path: {path}")
    normalized = posixpath.normpath(raw)
    if normalized.startswith("../") or normalized in {"..", "."}:
        raise ScopeError(f"Mapping path escapes the repository: {path}")
    return normalized + ("/" if directory else "")


def load_mappings(repo: str, base: str) -> list[tuple[str, str]]:
    text = git_show(repo, base, MAPPING_FILE)
    if text is None:
        return []
    mappings: list[tuple[str, str]] = []
    for entry in strip_entries(text):
        parts = entry.split()
        if len(parts) != 2 or not MODULE_RE.fullmatch(parts[1]):
            raise ScopeError(
                f"{MAPPING_FILE} lines must be 'path-or-prefix unittest.module'. Got: {entry}",
                exit_code=2,
            )
        mappings.append((normalize_pattern(parts[0]), parts[1]))
    return mappings


def match_mapping(path: str, mappings: list[tuple[str, str]]) -> str | None:
    best: tuple[int, str] | None = None
    for pattern, module in mappings:
        if pattern.endswith("/"):
            matched = path.startswith(pattern)
            score = len(pattern)
        else:
            matched = path == pattern
            score = len(pattern) + 1
        if matched and (best is None or score > best[0]):
            best = (score, module)
    return None if best is None else best[1]


def test_module(path: str) -> str | None:
    if not (path.startswith("tests/") and path.endswith(".py")):
        return None
    module = path[:-3].replace("/", ".")
    if not MODULE_RE.fullmatch(module):
        return None
    return module


def base_has_test_selection(repo: str, base: str) -> bool:
    script = git_show(repo, base, CHECKER_PATH)
    mappings = git_show(repo, base, MAPPING_FILE)
    return script is not None and "--print-tests" in script and mappings is not None


def paths_requiring_mapped_tests(paths: list[str]) -> list[str]:
    required: list[str] = []
    for path in paths:
        if is_protected(path, HARDCODED_PROTECTED):
            continue
        if (path.startswith("sqlglot/") and path.endswith(".py")) or test_module(path):
            required.append(path)
    return required


def migration_skip(repo: str, base: str, head: str) -> str:
    """Skip dialect selection only for a governance diff on a pre-mapping base.

    A feature diff fails closed when that base cannot provide --print-tests and
    test-mappings.txt. Later pull requests use the base checker instead.
    """
    paths = changed_paths(repo, base, head)
    if base_has_test_selection(repo, base):
        raise ScopeError(
            "Trusted base can select tests. Run that checker's --print-tests instead of skipping.",
            exit_code=2,
        )
    required = paths_requiring_mapped_tests(paths)
    if required:
        raise ScopeError(
            "Trusted base has no test-mapping infrastructure. "
            "Refusing to skip tests for a feature change:\n  " + "\n  ".join(required)
        )
    return (
        "targeted-checks: base has no test mappings; "
        "skipping mapped dialect tests for a governance-only diff"
    )


def select_tests(repo: str, base: str, head: str) -> list[str]:
    """Map a diff to unittest modules using the base commit's mapping file.

    Unmapped production Python under sqlglot/ returns FALLBACK instead of an
    empty selection. Changed test modules are included when they still exist.
    """
    mappings = load_mappings(repo, base)
    selected: list[str] = []
    unmapped_production = False
    for path in changed_paths(repo, base, head):
        if is_protected(path, HARDCODED_PROTECTED):
            continue
        module = test_module(path)
        if module and git_show(repo, head, path) is not None:
            selected.append(module)
        mapped = match_mapping(path, mappings)
        if mapped:
            selected.append(mapped)
        elif path.startswith("sqlglot/") and path.endswith(".py"):
            unmapped_production = True
    if unmapped_production:
        return [FALLBACK]
    return list(dict.fromkeys(selected))


def evaluate(repo: str, base: str, head: str, actor: str) -> str:
    verify_refs(repo, base, head)
    rules = protected_rules(git_show(repo, base, PROTECTED_FILE))
    paths = changed_paths(repo, base, head)
    if not paths:
        return "change-scope: OK (no file changes)"

    protected = [path for path in paths if is_protected(path, rules)]
    feature = [path for path in paths if path not in protected]
    if protected and feature:
        raise ScopeError(
            "Mixed policy and feature changes are not allowed.\n"
            "Protected:\n  " + "\n  ".join(protected) + "\n"
            "Feature:\n  " + "\n  ".join(feature)
        )
    if protected:
        if actor not in POLICY_ACTORS:
            raise ScopeError(
                "Protected governance files changed. Only a GitHub OWNER or MEMBER can open "
                "that pull request, and branch protection must still require review.\n"
                f"Actor: {actor or '(unset)'}\n"
                "Protected:\n  " + "\n  ".join(protected)
            )
        return (
            "change-scope: OK policy change for "
            f"{actor}. Human review is still required before merge.\n"
            "Protected:\n  " + "\n  ".join(protected)
        )
    return f"change-scope: OK feature files={len(feature)}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True, help="Trusted base commit or branch")
    parser.add_argument("--head", required=True, help="Pull request head commit or branch")
    parser.add_argument(
        "--policy-actor",
        default=os.environ.get("ACME_ACTOR", ""),
        help="GitHub author_association. Local use does not grant merge rights.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--print-tests",
        action="store_true",
        help="Print unittest modules for this diff. FALLBACK means the unit suite.",
    )
    mode.add_argument(
        "--migration-skip",
        action="store_true",
        help="Governance-only skip when the trusted base has no test-selection interface.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.migration_skip:
            print(migration_skip(args.repo, args.base, args.head))
            return 0
        if args.print_tests:
            for module in select_tests(args.repo, args.base, args.head):
                print(module)
            return 0
        message = evaluate(
            args.repo,
            args.base,
            args.head,
            args.policy_actor.strip().upper(),
        )
    except ScopeError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
