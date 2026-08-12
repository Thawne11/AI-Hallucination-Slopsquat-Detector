"""
Clones a public repo, finds its dependency manifest files, and checks every
declared package against the real PyPI/npm registries.
"""

import os
import subprocess
import tempfile
import time

from registry import exists as registry_exists
from scanner.manifest_parser import (
    MANIFEST_PARSERS,
    parse_package_json_own_name,
    parse_pyproject_own_name,
)

_OWN_NAME_PARSERS = {
    "package.json": parse_package_json_own_name,
    "pyproject.toml": parse_pyproject_own_name,
}

_SKIP_DIRS = {
    "node_modules", ".git", "vendor", "venv", ".venv", "dist", "build",
    "__pycache__", "site-packages", ".tox", "target",
    # Test/fixture/example directories often contain deliberately-fake
    # manifest files (e.g. a dependency-resolver's own test suite), which
    # would otherwise show up as false-positive "phantom" packages.
    "test", "tests", "fixture", "fixtures", "__fixtures__", "testdata",
    "example", "examples", "sample", "samples", "spec", "specs",
    "mock", "mocks", "__mocks__", "e2e", "demo", "demos",
}
_CLONE_TIMEOUT = 120
_REGISTRY_SLEEP = 0.2


def clone_repo(repo_url: str, dest_dir: str) -> None:
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", repo_url, dest_dir],
        check=True,
        timeout=_CLONE_TIMEOUT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def find_manifest_files(repo_path: str) -> list[str]:
    found = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in files:
            if filename in MANIFEST_PARSERS:
                found.append(os.path.join(root, filename))
    return found


def scan_repo(repo_url: str) -> dict:
    report = {
        "repo_url": repo_url,
        "manifest_files": [],
        "packages_checked": 0,
        "phantom_packages": [],
        "error": None,
    }

    with tempfile.TemporaryDirectory(prefix="slopsquat-scan-") as tmp_dir:
        try:
            clone_repo(repo_url, tmp_dir)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            report["error"] = f"clone failed: {e}"
            return report

        manifest_paths = find_manifest_files(tmp_dir)
        report["manifest_files"] = [
            os.path.relpath(p, tmp_dir) for p in manifest_paths
        ]

        contents_by_path = {}
        for manifest_path in manifest_paths:
            try:
                contents_by_path[manifest_path] = open(
                    manifest_path, encoding="utf-8", errors="ignore"
                ).read()
            except OSError:
                continue

        # First pass: collect names the repo declares for itself (its own
        # packages, e.g. every workspace member in a monorepo), so a
        # dependency on a sibling package isn't mistaken for a phantom one.
        local_names: set[str] = set()
        for manifest_path, content in contents_by_path.items():
            filename = os.path.basename(manifest_path)
            own_name_parser = _OWN_NAME_PARSERS.get(filename)
            if own_name_parser:
                own_name = own_name_parser(content)
                if own_name:
                    local_names.add(own_name.lower())

        package_cache: dict[tuple[str, str], bool] = {}
        seen_in_repo: set[tuple[str, str]] = set()

        for manifest_path, content in contents_by_path.items():
            filename = os.path.basename(manifest_path)
            ecosystem, parser_fn = MANIFEST_PARSERS[filename]
            rel_path = os.path.relpath(manifest_path, tmp_dir)

            for name in parser_fn(content):
                if name.lower() in local_names:
                    continue  # monorepo self-reference, not a registry dependency

                key = (name, ecosystem)
                seen_in_repo.add(key)

                if key not in package_cache:
                    package_cache[key] = registry_exists(name, ecosystem)
                    time.sleep(_REGISTRY_SLEEP)

                if not package_cache[key]:
                    report["phantom_packages"].append({
                        "name": name,
                        "ecosystem": ecosystem,
                        "found_in": rel_path,
                    })

        report["packages_checked"] = len(seen_in_repo)

    return report
