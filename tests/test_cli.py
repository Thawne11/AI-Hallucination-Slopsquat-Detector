"""
Tests for CLI presentation and exit codes.

Exit codes are the contract CI integrations depend on, so they are pinned
here: clean, phantom-found and scan-failed must stay distinguishable.
"""

import cli
from cli import EXIT_CLEAN, EXIT_FINDING, EXIT_SCAN_ERROR


def make_report(target="/some/project", phantoms=(), error=None, checked=3,
                manifests=1, risk=()):
    return {
        "target": target,
        "manifest_files": ["requirements.txt"] * manifests,
        "packages_checked": checked,
        "phantom_packages": list(phantoms),
        "error": error,
        "risk": list(risk),
    }


def risk_entry(name, tier, score, ecosystem="python"):
    return {
        "name": name,
        "ecosystem": ecosystem,
        "tier": tier,
        "score": score,
        "exists": True,
        "signals": [],
    }


class TestExitCodes:
    def test_clean_scan(self):
        assert cli.exit_code_for(make_report()) == EXIT_CLEAN

    def test_phantom_found(self):
        report = make_report(phantoms=[
            {"name": "js2pdf", "ecosystem": "javascript", "found_in": "package.json"}
        ])
        assert cli.exit_code_for(report) == EXIT_FINDING

    def test_risk_findings_do_not_fail_a_build_unless_gated(self):
        """Without --fail-on the risk section stays informational, so adding
        scoring to an existing pipeline cannot start failing it silently."""
        report = make_report(risk=[risk_entry("loadsh", "CRITICAL", 90)])
        assert cli.exit_code_for(report, fail_on=None) == EXIT_CLEAN

    def test_fail_on_gates_at_the_requested_tier(self):
        """REGRESSION: scan --risk previously reported a package as HIGH or
        CRITICAL and still exited 0, so the scoring engine could not gate a
        pipeline at all."""
        report = make_report(risk=[risk_entry("loadsh", "HIGH", 60)])

        assert cli.exit_code_for(report, fail_on="high") == EXIT_FINDING
        assert cli.exit_code_for(report, fail_on="critical") == EXIT_CLEAN

    def test_fail_on_is_inclusive_of_the_named_tier(self):
        report = make_report(risk=[risk_entry("pkg", "MEDIUM", 30)])
        assert cli.exit_code_for(report, fail_on="medium") == EXIT_FINDING

    def test_a_phantom_fails_regardless_of_the_gate(self):
        """A name that resolves to nothing outranks any score-based tier, so
        even the loosest gate must not let it through."""
        report = make_report(
            phantoms=[{"name": "js2pdf", "ecosystem": "javascript",
                       "found_in": "package.json"}],
        )
        assert cli.exit_code_for(report, fail_on="critical") == EXIT_FINDING

    def test_scan_error_still_outranks_a_risk_finding(self):
        report = make_report(error="not a directory", risk=[risk_entry("p", "CRITICAL", 90)])
        assert cli.exit_code_for(report, fail_on="low") == EXIT_SCAN_ERROR

    def test_scan_error_is_distinct_from_a_finding(self):
        """A failed scan and a genuine finding must not collapse to the same
        code, or a CI step cannot tell "your dependencies are bad" from
        "the scanner could not run"."""
        assert cli.exit_code_for(make_report(error="not a directory: /nope")) == EXIT_SCAN_ERROR
        assert EXIT_SCAN_ERROR != EXIT_FINDING


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
