"""
Scanning imports in source, not just dependencies declared in a manifest.

The case this exists for: a working copy right after AI-generated code was
pasted in, where the invented name is imported but has not been added to
requirements.txt yet. Manifest-only scanning reported that project clean.
"""

import json

import pytest

from scanner import repo_scan
from scanner.repo_scan import (
    find_source_files,
    local_python_modules,
    scan_path,
)
from tests.test_repo_scan import build_tree


@pytest.fixture
def import_scan(monkeypatch):
    def _run(tmp_path, files, available, include_imports=True):
        build_tree(tmp_path, files)
        monkeypatch.setattr(
            repo_scan, "registry_exists", lambda name, eco: name in available
        )
        monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
        return scan_path(str(tmp_path), include_imports=include_imports)

    return _run


class TestFindSourceFiles:
    def test_finds_python_and_javascript_sources(self, tmp_path):
        build_tree(tmp_path, {
            "main.py": "", "app.js": "", "mod.ts": "", "component.tsx": "",
            "notes.md": "", "data.json": "",
        })

        found = {p.rsplit("/", 1)[-1]: eco for p, eco in find_source_files(str(tmp_path))}

        assert found == {
            "main.py": "python", "app.js": "javascript",
            "mod.ts": "javascript", "component.tsx": "javascript",
        }

    def test_respects_the_same_skip_directories_as_manifests(self, tmp_path):
        build_tree(tmp_path, {
            "main.py": "",
            "tests/test_thing.py": "",
            "node_modules/pkg/index.js": "",
            "venv/lib/mod.py": "",
        })

        found = [p for p, _ in find_source_files(str(tmp_path))]

        assert len(found) == 1
        assert found[0].endswith("main.py")


class TestLocalPythonModules:
    def test_collects_module_and_package_names(self, tmp_path):
        """A package contributes its directory name, not `__init__`."""
        build_tree(tmp_path, {
            "helpers.py": "", "app/__init__.py": "", "app/routes.py": "",
        })

        assert local_python_modules(str(tmp_path)) == {"helpers", "app", "routes"}


class TestImportScanning:
    def test_catches_a_hallucinated_import_absent_from_the_manifest(
        self, tmp_path, import_scan
    ):
        """REGRESSION: this project reported clean before --include-imports
        existed, which is the exact scenario the tool is for."""
        report = import_scan(
            tmp_path,
            files={
                "main.py": "import requests\nimport auto_retry_httpx\n",
                "requirements.txt": "requests\n",
            },
            available={"requests"},
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["auto_retry_httpx"]
        assert report["phantom_packages"][0]["origin"] == "import"

    def test_imports_are_not_scanned_unless_asked(self, tmp_path, import_scan):
        """Opt-in, so turning this on cannot silently change an existing
        pipeline's result."""
        report = import_scan(
            tmp_path,
            files={"main.py": "import auto_retry_httpx\n", "requirements.txt": "requests\n"},
            available={"requests"},
            include_imports=False,
        )

        assert report["phantom_packages"] == []

    def test_a_manifest_finding_is_still_labelled_as_such(self, tmp_path, import_scan):
        report = import_scan(
            tmp_path,
            files={"requirements.txt": "totally-fake-pkg\n"},
            available=set(),
        )

        assert report["phantom_packages"][0]["origin"] == "manifest"

    def test_local_modules_are_not_treated_as_dependencies(self, tmp_path, import_scan):
        """Python resolves a bare import against the local directory, so an
        internal module is not a registry dependency. Without this the
        feature would flag every file in the project."""
        report = import_scan(
            tmp_path,
            files={
                "main.py": "import helpers\nimport app\nfrom app import routes\n",
                "helpers.py": "",
                "app/__init__.py": "",
            },
            available=set(),
        )

        assert report["phantom_packages"] == []

    def test_stdlib_and_relative_imports_are_ignored(self, tmp_path, import_scan):
        report = import_scan(
            tmp_path,
            files={"main.py": "import os\nimport json\nfrom . import sibling\n"},
            available=set(),
        )

        assert report["phantom_packages"] == []

    def test_the_same_name_imported_twice_is_one_finding(self, tmp_path, import_scan):
        report = import_scan(
            tmp_path,
            files={
                "a.py": "import auto_retry_httpx\n",
                "b.py": "import auto_retry_httpx\n",
            },
            available=set(),
        )

        assert len(report["phantom_packages"]) == 1

    def test_javascript_imports_are_checked_too(self, tmp_path, import_scan):
        report = import_scan(
            tmp_path,
            files={"index.js": "const x = require('ws-reconnect-pro');\n"},
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["ws-reconnect-pro"]

    def test_a_local_javascript_file_does_not_suppress_a_package_name(
        self, tmp_path, import_scan
    ):
        """Node does not resolve bare specifiers locally -- a local file must
        be required as './foo' -- so a same-named file must not hide a real
        package reference the way it legitimately does in Python."""
        report = import_scan(
            tmp_path,
            files={
                "index.js": "const x = require('ws-reconnect-pro');\n",
                "ws-reconnect-pro.js": "",
            },
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["ws-reconnect-pro"]

    def test_source_file_count_is_reported(self, tmp_path, import_scan):
        report = import_scan(
            tmp_path,
            files={"a.py": "", "b.py": "", "c.js": ""},
            available=set(),
        )

        assert report["source_files"] == 3

    def test_a_declared_and_imported_dependency_is_only_checked_once(
        self, tmp_path, import_scan
    ):
        report = import_scan(
            tmp_path,
            files={"main.py": "import requests\n", "requirements.txt": "requests\n"},
            available={"requests"},
        )

        assert report["packages_checked"] == 1
