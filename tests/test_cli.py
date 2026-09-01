"""
Tests for CLI presentation and exit codes.

Exit codes are the contract CI integrations depend on, so they are pinned
here: clean, phantom-found and scan-failed must stay distinguishable.
"""

import cli
from cli import EXIT_CLEAN, EXIT_PHANTOM_FOUND, EXIT_SCAN_ERROR


def make_report(target="/some/project", phantoms=(), error=None, checked=3, manifests=1):
    return {
        "target": target,
        "manifest_files": ["requirements.txt"] * manifests,
        "packages_checked": checked,
        "phantom_packages": list(phantoms),
        "error": error,
    }


class TestExitCodes:
    def test_clean_scan(self):
        assert cli.exit_code_for(make_report()) == EXIT_CLEAN

    def test_phantom_found(self):
        report = make_report(phantoms=[
            {"name": "js2pdf", "ecosystem": "javascript", "found_in": "package.json"}
        ])
        assert cli.exit_code_for(report) == EXIT_PHANTOM_FOUND

    def test_scan_error_is_distinct_from_a_finding(self):
        """A failed scan and a genuine finding must not collapse to the same
        code, or a CI step cannot tell "your dependencies are bad" from
        "the scanner could not run"."""
        assert cli.exit_code_for(make_report(error="not a directory: /nope")) == EXIT_SCAN_ERROR
        assert EXIT_SCAN_ERROR != EXIT_PHANTOM_FOUND


class TestReportFormatting:
    def test_clean_report_says_so(self):
        output = cli.format_report(make_report())
        assert "No phantom dependencies found." in output

    def test_lists_each_phantom_with_ecosystem_and_location(self):
        report = make_report(phantoms=[
            {"name": "js2pdf", "ecosystem": "javascript", "found_in": "package.json"},
            {"name": "samllib", "ecosystem": "python", "found_in": "requirements.txt"},
        ])

        output = cli.format_report(report)

        assert "2 phantom dependencies:" in output
        assert "js2pdf" in output and "javascript" in output and "package.json" in output
        assert "samllib" in output and "python" in output and "requirements.txt" in output

    def test_singular_wording_for_one_finding(self):
        report = make_report(phantoms=[
            {"name": "js2pdf", "ecosystem": "javascript", "found_in": "package.json"}
        ])
        assert "1 phantom dependency:" in cli.format_report(report)

    def test_error_report_surfaces_the_reason(self):
        output = cli.format_report(make_report(error="not a directory: /nope"))
        assert "not a directory: /nope" in output


class TestReportFilename:
    def test_remote_url_uses_owner_and_repo(self):
        assert cli.report_filename("https://github.com/psf/requests") == "psf_requests"

    def test_remote_url_strips_git_suffix_and_trailing_slash(self):
        assert cli.report_filename("https://github.com/psf/requests.git/") == "psf_requests"

    def test_local_path_uses_directory_name(self, tmp_path):
        project = tmp_path / "my-project"
        project.mkdir()
        assert cli.report_filename(str(project)) == "my-project"

    def test_relative_current_directory_resolves_to_a_real_name(self):
        assert cli.report_filename(".") not in ("", ".")
