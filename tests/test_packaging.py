"""
Packaging consistency.

Guards a bug that an editable install actively hides: `registry.py` imports
`known_aliases`, but `known_aliases` was missing from `py-modules`, so the
built wheel shipped a `registry` module that raised ModuleNotFoundError on
import. Running anything as `python -c ...` from the repo root masked it --
the current directory is on sys.path there -- while the installed
`slopsquat-scan` console script, which does not get the repo root on
sys.path, was broken.
"""

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
SETUPTOOLS_CONFIG = PYPROJECT["tool"]["setuptools"]

DECLARED_MODULES = set(SETUPTOOLS_CONFIG["py-modules"])
DECLARED_PACKAGES = set(SETUPTOOLS_CONFIG["packages"])

# Stdlib modules that did not always exist, and the version that introduced
# them. Declaring a requires-python floor below one of these produces a
# package that installs happily and then fails at import -- the same failure
# shape as omitting a module from py-modules.
STDLIB_INTRODUCED_IN = {
    "tomllib": (3, 11),
}

# Every top-level .py file in the repo root is importable as a bare module
# name when running from the repo root, which is exactly what makes the
# missing-from-py-modules failure mode so easy to miss locally.
ROOT_LEVEL_MODULES = {path.stem for path in ROOT.glob("*.py")}


def top_level_imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def packaged_source_files():
    for module in sorted(DECLARED_MODULES):
        yield ROOT / f"{module}.py"
    for package in sorted(DECLARED_PACKAGES):
        yield from sorted((ROOT / package).rglob("*.py"))


def test_declared_modules_and_packages_exist():
    for module in DECLARED_MODULES:
        assert (ROOT / f"{module}.py").is_file(), f"py-modules lists missing {module}.py"
    for package in DECLARED_PACKAGES:
        assert (ROOT / package).is_dir(), f"packages lists missing {package}/"


def test_packaged_code_only_imports_local_modules_that_are_also_packaged():
    missing = []
    for source in packaged_source_files():
        for imported in top_level_imports(source):
            is_local = imported in ROOT_LEVEL_MODULES or imported in DECLARED_PACKAGES
            is_packaged = imported in DECLARED_MODULES or imported in DECLARED_PACKAGES
            if is_local and not is_packaged:
                missing.append(f"{source.relative_to(ROOT)} imports unpackaged '{imported}'")

    assert not missing, (
        "these local modules are imported by packaged code but are not "
        "themselves declared in pyproject.toml, so the built wheel would "
        "crash on import: " + "; ".join(missing)
    )


def declared_python_floor():
    requires = PYPROJECT["project"]["requires-python"]
    match = re.search(r">=\s*(\d+)\.(\d+)", requires)
    assert match, f"could not read a lower bound from requires-python={requires!r}"
    return int(match.group(1)), int(match.group(2))


def test_requires_python_floor_covers_stdlib_modules_actually_imported():
    floor = declared_python_floor()

    too_old = []
    for source in packaged_source_files():
        for imported in top_level_imports(source):
            introduced = STDLIB_INTRODUCED_IN.get(imported)
            if introduced and floor < introduced:
                too_old.append(
                    f"{source.relative_to(ROOT)} imports '{imported}' "
                    f"(needs {introduced[0]}.{introduced[1]})"
                )

    assert not too_old, (
        f"requires-python floor is {floor[0]}.{floor[1]}, which is below what "
        "the packaged code actually needs, so the package would install on an "
        "interpreter it cannot run on: " + "; ".join(too_old)
    )
