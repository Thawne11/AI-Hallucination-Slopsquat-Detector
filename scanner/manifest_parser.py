"""
Parses dependency manifest files into (package_name, ecosystem) pairs.

This is the actual attack surface for slopsquatting: a phantom package only
matters if something would install it. Manifest files are what `pip install
-r requirements.txt` / `npm install` actually read, so that's what we check
-- not arbitrary source-code imports (see README for the reasoning).
"""

import json
import re
import tomllib

_REQ_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_SKIP_PREFIXES = ("-e ", "-r ", "--", "git+", "http://", "https://", "#")


def parse_requirements_txt(content: str) -> list[str]:
    packages = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_SKIP_PREFIXES):
            continue
        line = line.split(";")[0].strip()  # drop environment markers
        match = _REQ_LINE_RE.match(line)
        if match:
            packages.append(match.group(1))
    return packages


def _strip_requirement_spec(spec: str) -> str | None:
    spec = spec.strip()
    if not spec or spec.startswith(("git+", "http://", "https://")):
        return None
    if " @ " in spec:
        return None  # PEP 508 direct reference (file:///, git+, etc.) -- not a plain registry dep
    spec = spec.split(";")[0].strip()  # environment markers
    match = _REQ_LINE_RE.match(spec)
    return match.group(1) if match else None


def parse_pyproject_toml(content: str) -> list[str]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    packages = []

    project = data.get("project", {})
    for spec in project.get("dependencies", []):
        name = _strip_requirement_spec(spec)
        if name:
            packages.append(name)
    for group in project.get("optional-dependencies", {}).values():
        for spec in group:
            name = _strip_requirement_spec(spec)
            if name:
                packages.append(name)

    poetry = data.get("tool", {}).get("poetry", {})
    for section_name in ("dependencies", "dev-dependencies"):
        for name, spec in poetry.get(section_name, {}).items():
            if name.lower() != "python" and _is_registry_poetry_dep(spec):
                packages.append(name)
    for group in poetry.get("group", {}).values():
        for name, spec in group.get("dependencies", {}).items():
            if name.lower() != "python" and _is_registry_poetry_dep(spec):
                packages.append(name)

    return packages


def _is_registry_poetry_dep(spec) -> bool:
    """False for path/git/url-sourced poetry deps -- those are explicitly
    sourced from somewhere other than PyPI (often a sibling package in the
    same monorepo), so an existence-check against PyPI doesn't apply."""
    if isinstance(spec, dict):
        return not any(k in spec for k in ("path", "git", "url"))
    return True


_INSTALL_REQUIRES_RE = re.compile(
    r"install_requires\s*=\s*\[(.*?)\]", re.DOTALL
)
_QUOTED_STRING_RE = re.compile(r"""['"]([^'"]+)['"]""")


def parse_setup_py(content: str) -> list[str]:
    match = _INSTALL_REQUIRES_RE.search(content)
    if not match:
        return []
    packages = []
    for spec in _QUOTED_STRING_RE.findall(match.group(1)):
        name = _strip_requirement_spec(spec)
        if name:
            packages.append(name)
    return packages


_NON_REGISTRY_VERSION_PREFIXES = (
    "workspace:", "file:", "link:", "portal:", "git+", "git://",
    "http://", "https://", "./", "../",
)


def _is_registry_npm_dep(version: str) -> bool:
    """False for explicitly local/git-sourced npm deps (`workspace:`,
    `file:`, a relative path, ...). A bare `*` or `latest` is NOT excluded
    here -- that's valid syntax for a real public package too, so it can't
    be used alone to detect a monorepo self-reference. See
    `local_package_names` in repo_scan.py for the precise version of that
    check, which cross-references against names the repo declares itself."""
    version = version.strip()
    if not version:
        return False
    return not version.startswith(_NON_REGISTRY_VERSION_PREFIXES)


def parse_package_json(content: str) -> list[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    packages = []
    for section in ("dependencies", "devDependencies"):
        for name, version in data.get(section, {}).items():
            if isinstance(version, str) and _is_registry_npm_dep(version):
                packages.append(name)
    return packages


def parse_package_json_own_name(content: str) -> str | None:
    """The package's own declared name, so callers can build a set of
    locally-defined package names across a monorepo (see repo_scan.py)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    name = data.get("name")
    return name if isinstance(name, str) else None


def parse_pyproject_own_name(content: str) -> str | None:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    name = data.get("project", {}).get("name")
    if name:
        return name
    return data.get("tool", {}).get("poetry", {}).get("name")


MANIFEST_PARSERS = {
    "requirements.txt": ("python", parse_requirements_txt),
    "pyproject.toml": ("python", parse_pyproject_toml),
    "setup.py": ("python", parse_setup_py),
    "package.json": ("javascript", parse_package_json),
}
