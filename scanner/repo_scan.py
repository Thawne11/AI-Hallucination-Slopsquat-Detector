"""
Finds a codebase's dependency manifest files and checks every declared
package against the real PyPI/npm registries.

The scanning core (`scan_path`) works on a directory, so it serves both a
working copy on disk and a cloned remote repo -- `scan_repo` is just a clone
followed by a `scan_path`.
"""

import os
import subprocess
import tempfile
import time

from extractor import extract_packages
from registry import exists as registry_exists
from registry import fetch_metadata
from risk import score_package
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


SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
}


def find_source_files(repo_path: str) -> list[tuple[str, str]]:
    """(path, ecosystem) for every source file, under the same skip rules."""
    found = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in files:
            ecosystem = SOURCE_EXTENSIONS.get(os.path.splitext(filename)[1])
            if ecosystem:
                found.append((os.path.join(root, filename), ecosystem))
    return found


def local_python_modules(repo_path: str) -> set[str]:
    """Module names the codebase defines for itself.

    Python resolves a bare `import foo` against the local directory, so
    `import helpers` next to a `helpers.py` is not a registry dependency at
    all. Without this, scanning source imports would flag every internal
    module in the project.

    Python only, deliberately: Node does not resolve bare specifiers
    locally -- a local file has to be required as `./foo` -- and the
    extractor already drops relative specifiers.
    """
    names = set()
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in files:
            if filename == "__init__.py":
                names.add(os.path.basename(root).lower())
            elif filename.endswith(".py"):
                names.add(filename[:-3].lower())
    return names


REMOTE_PREFIXES = ("http://", "https://", "git://", "ssh://", "git@")


def looks_like_remote(target: str) -> bool:
    """Whether a scan target should be cloned rather than read from disk."""
    return target.startswith(REMOTE_PREFIXES)


def _new_report(target: str) -> dict:
    return {
        "target": target,
        "manifest_files": [],
        "source_files": 0,
        "packages_checked": 0,
        "phantom_packages": [],
        "risk": [],
        "error": None,
    }


def _assess(name: str, ecosystem: str, with_risk: bool):
    """Return (exists, risk_or_None) for one package.

    In risk mode the metadata fetch already reveals whether the package
    exists, so it replaces the existence check rather than adding to it --
    scoring costs no extra registry round-trip for the existence question.
    """
    if not with_risk:
        return registry_exists(name, ecosystem), None

    metadata = fetch_metadata(name, ecosystem)
    return metadata["exists"], score_package(metadata)


def _read(path: str) -> str | None:
    try:
        return open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None


def _manifest_candidates(root: str, report: dict) -> list[tuple[str, str, str, str]]:
    """(name, ecosystem, rel_path, origin) for every manifest-declared dep."""
    manifest_paths = find_manifest_files(root)
    report["manifest_files"] = [os.path.relpath(p, root) for p in manifest_paths]

    contents_by_path = {}
    for manifest_path in manifest_paths:
        content = _read(manifest_path)
        if content is not None:
            contents_by_path[manifest_path] = content

    # Names the codebase declares for itself (every workspace member in a
    # monorepo), so a dependency on a sibling package isn't mistaken for a
    # phantom one.
    declared_names: set[str] = set()
    for manifest_path, content in contents_by_path.items():
        own_name_parser = _OWN_NAME_PARSERS.get(os.path.basename(manifest_path))
        if own_name_parser:
            own_name = own_name_parser(content)
            if own_name:
                declared_names.add(own_name.lower())

    candidates = []
    for manifest_path, content in contents_by_path.items():
        ecosystem, parser_fn = MANIFEST_PARSERS[os.path.basename(manifest_path)]
        rel_path = os.path.relpath(manifest_path, root)
        for name in parser_fn(content):
            if name.lower() in declared_names:
                continue  # monorepo self-reference, not a registry dependency
            candidates.append((name, ecosystem, rel_path, "manifest"))
    return candidates


def _import_candidates(root: str, report: dict) -> list[tuple[str, str, str, str]]:
    """(name, ecosystem, rel_path, origin) for every third-party import."""
    source_files = find_source_files(root)
    report["source_files"] = len(source_files)

    local_modules = local_python_modules(root)

    candidates = []
    for source_path, ecosystem in source_files:
        content = _read(source_path)
        if content is None:
            continue

        rel_path = os.path.relpath(source_path, root)
        for name in extract_packages(content, ecosystem):
            if ecosystem == "python" and name.lower() in local_modules:
                continue  # resolves to a module inside the project itself
            candidates.append((name, ecosystem, rel_path, "import"))
    return candidates


def _scan_directory_into(
    report: dict, root: str, with_risk: bool = False,
    include_imports: bool = False,
) -> None:
    candidates = _manifest_candidates(root, report)
    if include_imports:
        candidates += _import_candidates(root, report)

    package_cache: dict[tuple[str, str], bool] = {}
    risk_cache: dict[tuple[str, str], dict] = {}
    reported: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str]] = set()

    for name, ecosystem, rel_path, origin in candidates:
        key = (name, ecosystem)
        seen.add(key)

        if key not in package_cache:
            package_exists, risk = _assess(name, ecosystem, with_risk)
            package_cache[key] = package_exists
            if risk:
                risk_cache[key] = {**risk, "found_in": rel_path, "origin": origin}
            time.sleep(_REGISTRY_SLEEP)

        # A name imported from several files is one finding, not several.
        if not package_cache[key] and (name, ecosystem, origin) not in reported:
            reported.add((name, ecosystem, origin))
            report["phantom_packages"].append({
                "name": name,
                "ecosystem": ecosystem,
                "found_in": rel_path,
                "origin": origin,
            })

    report["packages_checked"] = len(seen)
    report["risk"] = sorted(
        risk_cache.values(), key=lambda r: r["score"], reverse=True
    )


def scan_path(directory: str, with_risk: bool = False,
              include_imports: bool = False) -> dict:
    """Scan a directory that already exists on disk (a working copy)."""
    report = _new_report(str(directory))

    if not os.path.isdir(directory):
        report["error"] = f"not a directory: {directory}"
        return report

    _scan_directory_into(report, str(directory), with_risk, include_imports)
    return report


def scan_repo(repo_url: str, with_risk: bool = False,
              include_imports: bool = False) -> dict:
    """Shallow-clone a remote repo into a temporary directory and scan it."""
    report = _new_report(repo_url)

    with tempfile.TemporaryDirectory(prefix="slopsquat-scan-") as tmp_dir:
        try:
            clone_repo(repo_url, tmp_dir)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            report["error"] = f"clone failed: {e}"
            return report

        _scan_directory_into(report, tmp_dir, with_risk, include_imports)

    return report


def scan(target: str, with_risk: bool = False,
         include_imports: bool = False) -> dict:
    """Scan either a remote URL or a local directory, whichever `target` is."""
    if looks_like_remote(target):
        return scan_repo(target, with_risk, include_imports)
    return scan_path(target, with_risk, include_imports)
