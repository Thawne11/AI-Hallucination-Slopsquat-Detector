"""
Tests for repo scanning.

`clone_repo` and the registry lookup are stubbed, so these run offline
against synthetic repo trees rather than cloning anything real.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scanner import repo_scan
from scanner.repo_scan import (
    find_manifest_files,
    looks_like_remote,
    scan,
    scan_path,
    scan_repo,
)


def build_tree(root, files):
    """Write {relative_path: contents} into `root`, creating parent dirs."""
    for rel_path, contents in files.items():
        path = Path(root) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)


@pytest.fixture
def fake_scan(monkeypatch):
    """Runs scan_repo against a synthetic repo tree with a stubbed registry."""

    def _run(files, available):
        def fake_clone(repo_url, dest_dir):
            build_tree(dest_dir, files)

        def fake_exists(package, ecosystem):
            return package in available

        monkeypatch.setattr(repo_scan, "clone_repo", fake_clone)
        monkeypatch.setattr(repo_scan, "registry_exists", fake_exists)
        monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
        return scan_repo("https://github.com/example/repo")

    return _run


class TestFindManifestFiles:
    def test_finds_manifests_at_any_depth(self, tmp_path):
        build_tree(tmp_path, {
            "requirements.txt": "requests\n",
            "package.json": "{}",
            "src/pyproject.toml": "[project]\nname='x'",
        })

        found = {os.path.relpath(p, tmp_path) for p in find_manifest_files(tmp_path)}

        assert found == {"requirements.txt", "package.json", "src/pyproject.toml"}

    def test_regression_skips_test_and_fixture_directories(self, tmp_path):
        """REGRESSION: python-poetry/poetry ships pyproject.toml fixtures with
        deliberately-fake dependency names to exercise its own resolver.
        Walking those produced 10 phantom-package false positives against a
        flagship, heavily-reviewed repo."""
        build_tree(tmp_path, {
            "pyproject.toml": "[project]\nname='real'",
            "tests/fixtures/invalid_pyproject/pyproject.toml": "[project]\nname='fake'",
            "test/pyproject.toml": "[project]\nname='fake'",
            "examples/package.json": "{}",
            "demo/package.json": "{}",
            "__mocks__/package.json": "{}",
        })

        found = {os.path.relpath(p, tmp_path) for p in find_manifest_files(tmp_path)}

        assert found == {"pyproject.toml"}

    def test_skips_vendored_and_build_directories(self, tmp_path):
        build_tree(tmp_path, {
            "package.json": "{}",
            "node_modules/left-pad/package.json": "{}",
            "venv/lib/pyproject.toml": "[project]\nname='x'",
            "dist/package.json": "{}",
        })

        found = {os.path.relpath(p, tmp_path) for p in find_manifest_files(tmp_path)}

        assert found == {"package.json"}


class TestScanRepo:
    def test_flags_a_genuinely_missing_package(self, fake_scan):
        report = fake_scan(
            files={"requirements.txt": "requests\ntotally-fake-pkg-xyz123\n"},
            available={"requests"},
        )

        assert report["error"] is None
        assert report["packages_checked"] == 2
        assert [p["name"] for p in report["phantom_packages"]] == [
            "totally-fake-pkg-xyz123"
        ]

    def test_clean_repo_reports_no_phantoms(self, fake_scan):
        report = fake_scan(
            files={"requirements.txt": "requests\nflask\n"},
            available={"requests", "flask"},
        )

        assert report["phantom_packages"] == []

    def test_regression_npm_monorepo_self_reference_is_not_a_phantom(self, fake_scan):
        """REGRESSION: in a monorepo, a package depending on a sibling package
        by name is resolved locally by the workspace tooling and will never
        exist on the public registry. Flagging it produced false positives on
        mnfst/manifest, recomposesh/recompose and aliasghar-me/dukkanify."""
        report = fake_scan(
            files={
                "package.json": json.dumps({
                    "name": "@myorg/root",
                    "dependencies": {"@myorg/core": "*", "express": "^4.0"},
                }),
                "packages/core/package.json": json.dumps({
                    "name": "@myorg/core",
                    "dependencies": {"lodash": "^4.0"},
                }),
            },
            available={"express", "lodash"},
        )

        assert report["phantom_packages"] == []

    def test_regression_python_monorepo_self_reference_is_not_a_phantom(self, fake_scan):
        """REGRESSION: the Python half of the same bug, found on
        rodaddy/open-brain (openbrain-memory)."""
        report = fake_scan(
            files={
                "python/openbrain-memory/pyproject.toml": (
                    '[project]\nname = "openbrain-memory"\ndependencies = ["requests"]\n'
                ),
                "python/openbrain-provider/pyproject.toml": (
                    '[project]\nname = "openbrain-provider"\n'
                    'dependencies = ["openbrain-memory", "requests"]\n'
                ),
            },
            available={"requests"},
        )

        assert report["phantom_packages"] == []

    def test_a_sibling_lookalike_that_is_not_declared_locally_is_still_flagged(
        self, fake_scan
    ):
        """The self-reference exemption must be driven by names the repo
        actually declares -- not by any name that merely looks internal."""
        report = fake_scan(
            files={
                "package.json": json.dumps({
                    "name": "@myorg/root",
                    "dependencies": {"@myorg/not-a-real-sibling": "^1.0"},
                }),
            },
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == [
            "@myorg/not-a-real-sibling"
        ]

    def test_deduplicates_repeated_packages_across_manifests(self, fake_scan):
        report = fake_scan(
            files={
                "requirements.txt": "requests\n",
                "src/requirements.txt": "requests\n",
            },
            available={"requests"},
        )

        assert report["packages_checked"] == 1

    def test_clone_failure_is_reported_rather_than_raised(self, monkeypatch):
        def failing_clone(repo_url, dest_dir):
            raise subprocess.CalledProcessError(128, "git clone")

        monkeypatch.setattr(repo_scan, "clone_repo", failing_clone)

        report = scan_repo("https://github.com/example/does-not-exist")

        assert report["error"] is not None
        assert report["phantom_packages"] == []


class TestTargetDetection:
    @pytest.mark.parametrize("target", [
        "https://github.com/org/repo",
        "http://example.com/repo.git",
        "git://example.com/repo.git",
        "ssh://git@example.com/repo.git",
        "git@github.com:org/repo.git",
    ])
    def test_remote_targets(self, target):
        assert looks_like_remote(target) is True

    @pytest.mark.parametrize("target", [".", "./project", "../project", "/abs/path", "project"])
    def test_local_targets(self, target):
        assert looks_like_remote(target) is False


class TestScanPath:
    """Scanning a working copy on disk -- the case that matters most, since
    the risk lands before anything is committed or pushed."""

    @pytest.fixture
    def local_scan(self, monkeypatch):
        def _run(tmp_path, files, available):
            build_tree(tmp_path, files)
            monkeypatch.setattr(
                repo_scan, "registry_exists", lambda name, eco: name in available
            )
            monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
            return scan_path(str(tmp_path))

        return _run

    def test_scans_a_directory_without_cloning(self, tmp_path, local_scan, monkeypatch):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("scan_path must not clone anything")

        monkeypatch.setattr(repo_scan, "clone_repo", fail_if_called)

        report = local_scan(
            tmp_path,
            files={"requirements.txt": "requests\ntotally-fake-pkg-xyz123\n"},
            available={"requests"},
        )

        assert report["error"] is None
        assert report["target"] == str(tmp_path)
        assert [p["name"] for p in report["phantom_packages"]] == [
            "totally-fake-pkg-xyz123"
        ]

    def test_clean_directory(self, tmp_path, local_scan):
        report = local_scan(
            tmp_path,
            files={"requirements.txt": "requests\n"},
            available={"requests"},
        )

        assert report["phantom_packages"] == []

    def test_applies_the_same_monorepo_exemption_as_a_cloned_repo(
        self, tmp_path, local_scan
    ):
        report = local_scan(
            tmp_path,
            files={
                "package.json": json.dumps({
                    "name": "@myorg/root",
                    "dependencies": {"@myorg/core": "*", "express": "^4.0"},
                }),
                "packages/core/package.json": json.dumps({"name": "@myorg/core"}),
            },
            available={"express"},
        )

        assert report["phantom_packages"] == []

    def test_missing_directory_is_reported_rather_than_raised(self, tmp_path):
        report = scan_path(str(tmp_path / "does-not-exist"))

        assert report["error"] is not None
        assert report["phantom_packages"] == []

    def test_a_file_is_not_a_valid_target(self, tmp_path):
        file_path = tmp_path / "requirements.txt"
        file_path.write_text("requests\n")

        assert scan_path(str(file_path))["error"] is not None


class TestScanDispatch:
    def test_routes_remote_targets_to_clone(self, monkeypatch):
        monkeypatch.setattr(repo_scan, "scan_repo", lambda t, r=False: {"routed": "remote"})
        monkeypatch.setattr(repo_scan, "scan_path", lambda t, r=False: {"routed": "local"})

        assert scan("https://github.com/org/repo") == {"routed": "remote"}

    def test_routes_local_targets_to_disk(self, monkeypatch):
        monkeypatch.setattr(repo_scan, "scan_repo", lambda t, r=False: {"routed": "remote"})
        monkeypatch.setattr(repo_scan, "scan_path", lambda t, r=False: {"routed": "local"})

        assert scan("./project") == {"routed": "local"}
