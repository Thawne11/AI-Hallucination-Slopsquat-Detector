"""
Import reconciliation wired into the scanning pipeline, the CLI and the
exit-code contract.

The unit behaviour of the resolver lives in test_import_resolver.py. What
matters here is that it is actually *used* -- and that turning it on did not
weaken phantom detection, typosquat scoring, batch scanning or the codes CI
depends on.
"""

import json

import cli
import risk
from cli import EXIT_CLEAN, EXIT_FINDING
from import_resolver import ImportNameResolver
from scanner import repo_scan
from scanner.repo_scan import scan_path
from tests.test_repo_scan import build_tree


def offline_scan(monkeypatch, tmp_path, files, available, include_imports=True):
    build_tree(tmp_path, files)
    monkeypatch.setattr(
        repo_scan, "registry_exists", lambda name, eco: name in available
    )
    monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
    resolver = ImportNameResolver(
        exists_probe=lambda name: name in available, use_environment=False
    )
    return scan_path(str(tmp_path), include_imports=include_imports,
                     resolver=resolver)


class TestLegitimateImportsAreNoLongerFalsePositives:
    def test_well_known_mismatched_imports_are_clean(self, monkeypatch, tmp_path):
        """REGRESSION: cv2, yaml and friends were reported as phantom because
        the import name was checked against PyPI directly."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.py": "import cv2\nimport yaml\nimport sklearn\nfrom PIL import Image\n"},
            available={"opencv-python", "PyYAML", "scikit-learn", "Pillow"},
        )

        assert report["phantom_packages"] == []
        assert report["unresolved_imports"] == []

    def test_the_distribution_name_is_what_gets_checked(self, monkeypatch, tmp_path):
        """The registry must be asked about opencv-python, not cv2. If only
        the import name existed, this would still have to come back clean."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.py": "import cv2\n"},
            available={"opencv-python"},
        )

        assert report["phantom_packages"] == []


class TestPhantomDetectionSurvives:
    def test_a_manifest_dependency_is_still_phantom(self, monkeypatch, tmp_path):
        """Manifests list distribution names already, so they are checked
        literally -- reconciliation must not touch them."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"requirements.txt": "totally-fake-pkg\n"},
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["totally-fake-pkg"]

    def test_a_manifest_entry_is_not_run_through_the_alias_map(self, monkeypatch, tmp_path):
        """`cv2` in requirements.txt means the distribution literally called
        cv2. Rewriting it to opencv-python would answer about a package the
        developer did not ask for."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"requirements.txt": "cv2\n"},
            available={"opencv-python"},
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["cv2"]

    def test_a_resolved_distribution_that_does_not_exist_is_phantom(
        self, monkeypatch, tmp_path
    ):
        """If the mapping points at a distribution that has since been
        removed, that is a real finding about a real distribution name."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.py": "import cv2\n"},
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["opencv-python"]
        assert report["phantom_packages"][0]["resolution"]["import_name"] == "cv2"

    def test_an_invented_import_still_surfaces(self, monkeypatch, tmp_path):
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.py": "import auto_retry_httpx\n"},
            available=set(),
        )

        assert [u["name"] for u in report["unresolved_imports"]] == ["auto_retry_httpx"]


class TestJavaScriptIsUnaffected:
    def test_npm_specifiers_are_checked_directly(self, monkeypatch, tmp_path):
        """npm has no module/distribution split, so there is nothing to
        reconcile and behaviour must be unchanged."""
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.js": "const x = require('js2pdf');\n"},
            available=set(),
        )

        assert [p["name"] for p in report["phantom_packages"]] == ["js2pdf"]
        assert report["unresolved_imports"] == []


class TestTyposquatDetectionIsIndependent:
    def test_scoring_still_flags_a_near_miss(self):
        """Reconciliation and typosquat detection answer opposite questions
        and must not be entangled: one asks what a name installs, the other
        asks whether a name is suspiciously close to a popular one."""
        entry = risk.score_package({
            "name": "loadsh", "ecosystem": "javascript", "exists": True,
            "first_release": None, "release_count": None,
            "repository_url": None, "description": None,
            "maintainer_count": None, "weekly_downloads": None,
        })

        reasons = " ".join(s["reason"] for s in entry["signals"])
        assert "lodash" in reasons

    def test_a_resolved_import_still_gets_scored(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            repo_scan, "fetch_metadata",
            lambda name, eco: {
                "name": name, "ecosystem": eco, "exists": True,
                "first_release": None, "release_count": None,
                "repository_url": None, "description": None,
                "maintainer_count": None, "weekly_downloads": None,
            },
        )
        monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
        build_tree(tmp_path, {"app.py": "import cv2\n"})
        resolver = ImportNameResolver(exists_probe=lambda n: True,
                                      use_environment=False)

        report = scan_path(str(tmp_path), with_risk=True, include_imports=True,
                           resolver=resolver)

        assert [entry["name"] for entry in report["risk"]] == ["opencv-python"]


class TestCaching:
    def test_one_import_across_many_files_resolves_once(self, monkeypatch, tmp_path):
        build_tree(tmp_path, {
            "a.py": "import ghost_pkg\n",
            "b.py": "import ghost_pkg\n",
            "c.py": "import ghost_pkg\n",
        })
        monkeypatch.setattr(repo_scan, "registry_exists", lambda n, e: False)
        monkeypatch.setattr(repo_scan, "_REGISTRY_SLEEP", 0)
        resolver = ImportNameResolver(exists_probe=lambda n: False,
                                      use_environment=False)

        scan_path(str(tmp_path), include_imports=True, resolver=resolver)

        assert resolver.probe_calls == 1


class TestReportShape:
    def test_json_round_trips_with_resolution_attached(self, monkeypatch, tmp_path):
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"app.py": "import auto_retry_httpx\n"},
            available=set(),
        )

        restored = json.loads(json.dumps(report))
        resolution = restored["unresolved_imports"][0]["resolution"]

        assert resolution["import_name"] == "auto_retry_httpx"
        assert resolution["resolution_status"] == "unresolved"
        assert resolution["distribution_name"] is None

    def test_existing_report_keys_are_preserved(self, monkeypatch, tmp_path):
        report = offline_scan(
            monkeypatch, tmp_path,
            files={"requirements.txt": "requests\n"},
            available={"requests"},
        )

        missing = [
            key for key in ("target", "manifest_files", "packages_checked",
                            "phantom_packages", "risk", "error")
            if key not in report
        ]
        assert not missing, f"report lost pre-existing keys: {missing}"


class TestExitCodes:
    def test_an_unresolved_import_is_a_finding(self):
        """An invented import lands here, so exiting 0 would gut the check
        even though the wording is deliberately cautious."""
        report = {"error": None, "phantom_packages": [], "risk": [],
                  "unresolved_imports": [{"name": "ghost_pkg"}]}

        assert cli.exit_code_for(report) == EXIT_FINDING

    def test_a_clean_scan_is_still_clean(self):
        report = {"error": None, "phantom_packages": [], "risk": [],
                  "unresolved_imports": []}

        assert cli.exit_code_for(report) == EXIT_CLEAN

    def test_reports_without_the_new_key_still_work(self):
        """Older report JSON on disk predates unresolved_imports."""
        report = {"error": None, "phantom_packages": [], "risk": []}

        assert cli.exit_code_for(report) == EXIT_CLEAN


class TestCliFormatting:
    def test_unresolved_section_avoids_calling_it_nonexistent(self):
        report = {"unresolved_imports": [{
            "name": "ghost_pkg", "ecosystem": "python", "found_in": "app.py",
            "resolution": {
                "import_name": "ghost_pkg", "distribution_name": None,
                "resolution_status": "unresolved", "resolution_confidence": 0.0,
                "resolution_source": None, "candidates": [],
                "registry_checked": True,
            },
        }]}

        output = cli.format_unresolved_section(report)

        assert "ghost_pkg" in output
        assert "Not classified as phantom" in output

    def test_offline_and_absent_are_worded_differently(self):
        def section(registry_checked):
            return cli.format_unresolved_section({"unresolved_imports": [{
                "name": "ghost_pkg", "ecosystem": "python", "found_in": "app.py",
                "resolution": {
                    "import_name": "ghost_pkg", "distribution_name": None,
                    "resolution_status": "unresolved",
                    "resolution_confidence": 0.0, "resolution_source": None,
                    "candidates": [], "registry_checked": registry_checked,
                },
            }]})

        assert "no distribution of that name" in section(True)
        assert "could not be consulted" in section(False)

    def test_ambiguous_lists_every_candidate(self):
        output = cli.format_unresolved_section({"unresolved_imports": [{
            "name": "slugify", "ecosystem": "python", "found_in": "app.py",
            "resolution": {
                "import_name": "slugify", "distribution_name": None,
                "resolution_status": "ambiguous", "resolution_confidence": 0.0,
                "resolution_source": "mapping",
                "candidates": ["python-slugify", "awesome-slugify"],
                "registry_checked": False,
            },
        }]})

        assert "python-slugify" in output and "awesome-slugify" in output

    def test_no_section_when_everything_resolved(self):
        assert cli.format_unresolved_section({"unresolved_imports": []}) == ""

    def test_resolution_display_names_the_source_layer(self):
        output = cli.format_resolution({
            "import_name": "cv2", "distribution_name": "opencv-python",
            "resolution_status": "verified", "resolution_confidence": 1.0,
            "resolution_source": "mapping", "candidates": [],
            "registry_checked": False,
        })

        assert "cv2" in output and "opencv-python" in output
        assert "VERIFIED" in output and "mapping" in output

    def test_unresolved_display_states_it_is_not_phantom(self):
        output = cli.format_resolution({
            "import_name": "ghost_pkg", "distribution_name": None,
            "resolution_status": "unresolved", "resolution_confidence": 0.0,
            "resolution_source": None, "candidates": [],
            "registry_checked": True,
        })

        assert "UNKNOWN" in output
        assert "NOT automatically classified as PHANTOM" in output

    def test_phantom_line_shows_the_import_it_came_from(self):
        output = cli.format_report({
            "target": ".", "manifest_files": [], "source_files": 1,
            "packages_checked": 1, "error": None,
            "phantom_packages": [{
                "name": "opencv-python", "ecosystem": "python",
                "found_in": "app.py", "origin": "import",
                "resolution": {"import_name": "cv2"},
            }],
        })

        assert "opencv-python" in output
        assert "import: cv2" in output


class TestBatchScanning:
    def test_batch_still_writes_one_report_per_target(self, monkeypatch, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "requirements.txt").write_text("requests\n")

        targets = tmp_path / "targets.txt"
        targets.write_text(f"{project}\n")
        out_dir = tmp_path / "out"

        monkeypatch.setattr(cli, "scan", lambda target, **kw: {
            "target": target, "manifest_files": [], "packages_checked": 1,
            "phantom_packages": [], "unresolved_imports": [], "risk": [],
            "error": None,
        })

        args = type("Args", (), {
            "targets_file": str(targets), "out_dir": str(out_dir),
        })()

        assert cli.cmd_batch(args) == EXIT_CLEAN
        assert len(list(out_dir.glob("*.json"))) == 1
