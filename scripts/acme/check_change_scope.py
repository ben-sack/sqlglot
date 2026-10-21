"""Fail a feature diff that leaves its per-issue allowlist.

Policy is read from the trusted base revision. A pull request cannot widen
its own allowlist, and protected paths stay protected even if an allowlist
names them. The hardcoded floor below cannot be weakened by protected-paths.txt.
"""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import subprocess
import sys

ISSUE_RE = re.compile(r"ACME-\d+")
BODY_ISSUE_RE = re.compile(r"(?m)^Acme-Issue:[ \t]*(ACME-\d+)[ \t]*$")
BRANCH_ISSUE_RE = re.compile(r"(?:^|/)acme-(\d+)(?:$|[^0-9])", re.IGNORECASE)
POLICY_ACTORS = frozenset({"OWNER", "MEMBER"})

# Floor used even when .github/acme/protected-paths.txt is emptied.
HARDCODED_PROTECTED = (
    ".github/acme/",
    ".github/workflows/acme-change-scope.yml",
    ".github/workflows/acme-targeted-checks.yml",
    "scripts/acme/",
    "tests/acme/",
    ".cursor/",
    "ACME_WORKFLOW.md",
)

ALLOWLIST_DIR = ".github/acme/allowlists"
REQUIREMENTS_DIR = ".github/acme/test-requirements"
PROTECTED_FILE = ".github/acme/protected-paths.txt"


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


def merge_base(repo: str, base: str, head: str) -> str:
    completed = run_git(repo, "merge-base", base, head, check=False)
    if completed.returncode != 0:
        raise ScopeError(
            f"Cannot find merge base of {base} and {head}. Fetch the trusted base first.",
            exit_code=2,
        )
    return completed.stdout.strip()


def changed_paths(repo: str, base: str, head: str) -> list[str]:
    """Return every path added, removed, or renamed between the merge base and head."""
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


def normalize_file_path(path: str) -> str:
    if path.startswith(("/", "~", "-")) or "\\" in path:
        raise ScopeError(f"Allowlist path must be a relative repo file: {path}")
    if any(char in path for char in "*?["):
        raise ScopeError(f"Allowlist path must be an exact file, not a glob: {path}")
    if path.endswith("/"):
        raise ScopeError(f"Allowlist path must be an exact file, not a directory: {path}")
    normalized = posixpath.normpath(path)
    if normalized.startswith("../") or normalized in {"..", "."}:
        raise ScopeError(f"Allowlist path escapes the repository: {path}")
    return normalized


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


def resolve_issue(explicit: str | None, title: str, body: str, branch: str) -> str | None:
    found: list[str] = []
    if explicit:
        if not ISSUE_RE.fullmatch(explicit):
            raise ScopeError(f"Issue id must look like ACME-123, got {explicit!r}.", exit_code=2)
        found.append(explicit)
    marker = BODY_ISSUE_RE.findall(body)
    if len(marker) > 1:
        raise ScopeError(f"Pull request body has multiple Acme-Issue markers: {marker}")
    if len(marker) == 1:
        found.append(marker[0])
    title_ids = ISSUE_RE.findall(title)
    if len(title_ids) > 1:
        raise ScopeError(f"Pull request title has multiple issue ids: {title_ids}")
    if len(title_ids) == 1:
        found.append(title_ids[0])
    branch_ids = [f"ACME-{number}" for number in BRANCH_ISSUE_RE.findall(branch)]
    if len(set(branch_ids)) > 1:
        raise ScopeError(f"Branch name has multiple issue ids: {branch_ids}")
    if len(set(branch_ids)) == 1:
        found.append(branch_ids[0])
    unique = list(dict.fromkeys(found))
    if len(unique) > 1:
        raise ScopeError(f"Issue id is ambiguous: {unique}")
    return unique[0] if unique else None


def load_allowlist(repo: str, base: str, issue: str, rules: tuple[str, ...]) -> set[str]:
    path = f"{ALLOWLIST_DIR}/{issue}.txt"
    text = git_show(repo, base, path)
    if text is None:
        raise ScopeError(
            f"No allowlist {path} on the trusted base. Open a maintainer policy change first."
        )
    allowed: set[str] = set()
    for entry in strip_entries(text):
        normalized = normalize_file_path(entry)
        if is_protected(normalized, rules):
            raise ScopeError(
                f"Allowlist {path} on the trusted base grants protected path {normalized}."
            )
        allowed.add(normalized)
    return allowed


def load_test_requirements(repo: str, base: str, issue: str) -> list[tuple[str, str]]:
    """Pairs from the trusted base. Missing file means the issue has no pairing gate."""
    text = git_show(repo, base, f"{REQUIREMENTS_DIR}/{issue}.txt")
    if text is None:
        return []
    pairs: list[tuple[str, str]] = []
    for entry in strip_entries(text):
        parts = entry.split()
        if len(parts) != 2:
            raise ScopeError(
                f"{REQUIREMENTS_DIR}/{issue}.txt must contain lines of 'production-file test-file'."
            )
        pairs.append((normalize_file_path(parts[0]), normalize_file_path(parts[1])))
    return pairs


def require_paired_tests(
    repo: str,
    head: str,
    issue: str,
    changed: list[str],
    pairs: list[tuple[str, str]],
) -> None:
    """Pilot gate: a listed production edit must also change its test file.

    The test path has to remain on the head. Deleting it does not count.
    A diff that touches the test file does not prove the assertions are adequate.
    """
    present = set(changed)
    missing: list[str] = []
    for source, test in pairs:
        if source not in present:
            continue
        if test not in present or git_show(repo, head, test) is None:
            missing.append(f"{source} requires {test}")
    if missing:
        raise ScopeError(
            f"Pilot test pairing failed for {issue}. "
            "A production change must also change its paired test file, and that file "
            "must still exist on the pull request head. "
            "A changed test file does not prove the assertions are adequate.\n" + "\n".join(missing)
        )


def validate_policy_edits(repo: str, head: str, paths: list[str], rules: tuple[str, ...]) -> None:
    for path in paths:
        if not path.startswith(f"{ALLOWLIST_DIR}/") or not path.endswith(".txt"):
            continue
        text = git_show(repo, head, path)
        if text is None:
            continue
        for entry in strip_entries(text):
            normalized = normalize_file_path(entry)
            if is_protected(normalized, rules):
                raise ScopeError(f"Policy edit {path} would grant protected path {normalized}.")


def evaluate(
    repo: str,
    base: str,
    head: str,
    issue: str | None,
    actor: str,
) -> str:
    rules_text = git_show(repo, base, PROTECTED_FILE)
    rules = protected_rules(rules_text)
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
                "Protected policy files changed. Only a GitHub OWNER or MEMBER can open "
                "that pull request, and branch protection must still require review.\n"
                f"Actor: {actor or '(unset)'}\n"
                "Protected:\n  " + "\n  ".join(protected)
            )
        validate_policy_edits(repo, head, protected, rules)
        return (
            "change-scope: OK policy change for "
            f"{actor}. Human review is still required before merge.\n"
            "Protected:\n  " + "\n  ".join(protected)
        )

    if issue is None:
        raise ScopeError(
            "Could not determine the issue id. Pass --issue ACME-123 or set "
            "Acme-Issue: ACME-123 in the pull request body.\n"
            "Changed:\n  " + "\n  ".join(feature)
        )
    allowed = load_allowlist(repo, base, issue, rules)
    unauthorized = [path for path in feature if path not in allowed]
    if unauthorized:
        raise ScopeError(
            f"Unauthorized changes for {issue}. The allowlist is read from the trusted base, "
            "not from this branch.\n"
            "Unauthorized:\n  " + "\n  ".join(unauthorized) + "\n"
            "Allowed:\n  " + ("\n  ".join(sorted(allowed)) if allowed else "(empty)")
        )
    require_paired_tests(
        repo,
        head,
        issue,
        feature,
        load_test_requirements(repo, base, issue),
    )
    return f"change-scope: OK issue={issue} files={len(feature)}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True, help="Trusted base commit or branch")
    parser.add_argument("--head", required=True, help="Pull request head commit or branch")
    parser.add_argument("--issue", help="Issue id, for example ACME-101")
    parser.add_argument(
        "--policy-actor",
        default=os.environ.get("ACME_ACTOR", ""),
        help="GitHub author_association. Local use does not grant merge rights.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        issue = resolve_issue(
            args.issue,
            os.environ.get("PR_TITLE", ""),
            os.environ.get("PR_BODY") or "",
            os.environ.get("HEAD_REF", ""),
        )
        message = evaluate(
            args.repo,
            args.base,
            args.head,
            issue,
            args.policy_actor.strip().upper(),
        )
    except ScopeError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
