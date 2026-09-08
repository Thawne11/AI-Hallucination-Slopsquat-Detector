"""
Confidence: how much evidence a risk verdict rests on.

The property under test throughout is that confidence and risk move
independently. A confidence figure that tracked the score would be a second
name for the same number and would tell a user nothing.
"""

import cli
import risk
from risk import score_confidence, score_package


def metadata(ecosystem="javascript", exists=True, lookup_ok=True, **overrides):
    """A fully-populated registry record, minus whatever a test removes."""
    base = {
        "name": "example", "ecosystem": ecosystem,
        "exists": exists, "lookup_ok": lookup_ok,
        "first_release": "2015-01-01T00:00:00Z", "release_count": 120,
        "repository_url": "https://github.com/org/example",
        "description": "an ordinary library that does ordinary things",
        "maintainer_count": 4, "weekly_downloads": 900000,
    }
    base.update(overrides)
    return base


class TestEvidenceCompleteness:
    def test_complete_metadata_scores_full_confidence(self):
        assert score_confidence(metadata())["confidence"] == 100

    def test_each_missing_field_costs_its_documented_weight(self):
        for field, weight in [
            ("release_count", risk.EVIDENCE_WEIGHTS["release_history"]),
            ("weekly_downloads", risk.EVIDENCE_WEIGHTS["download_stats"]),
            ("maintainer_count", risk.EVIDENCE_WEIGHTS["maintainer_info"]),
            ("repository_url", risk.EVIDENCE_WEIGHTS["repository_info"]),
            ("description", risk.EVIDENCE_WEIGHTS["description"]),
        ]:
            result = score_confidence(metadata(**{field: None}))
            assert result["confidence"] == 100 - weight, field

    def test_weights_sum_to_one_hundred(self):
        """The scale is only meaningful if a fully-evidenced package can
        actually reach 100."""
        assert sum(risk.EVIDENCE_WEIGHTS.values()) == 100

    def test_pypi_scores_lower_because_it_publishes_less(self):
        """Not a penalty on Python packages -- there is genuinely less
        evidence available, and the number should say so."""
        result = score_confidence(metadata(
            ecosystem="python", weekly_downloads=None, maintainer_count=None,
        ))

        assert result["confidence"] == 70

    def test_evidence_lists_what_was_and_was_not_available(self):
        result = score_confidence(metadata(repository_url=None))
        by_name = {item["name"]: item for item in result["evidence"]}

        assert by_name["registry_lookup"]["available"] is True
        assert by_name["repository_info"]["available"] is False
        assert "no repository link" in by_name["repository_info"]["detail"]


class TestIndependenceFromRisk:
    def test_high_risk_can_have_low_confidence(self):
        entry = score_package(metadata(
            ecosystem="python", name="loadsh", first_release=None,
            release_count=None, repository_url=None, description=None,
            maintainer_count=None, weekly_downloads=None,
        ))

        assert entry["score"] > 0
        assert entry["confidence"] < 60

    def test_low_risk_can_have_high_confidence(self):
        entry = score_package(metadata())

        assert entry["score"] == 0
        assert entry["confidence"] == 100

    def test_confidence_is_not_a_copy_of_the_score(self):
        entry = score_package(metadata(ecosystem="python", name="loadsh",
                                       weekly_downloads=None,
                                       maintainer_count=None))

        assert entry["confidence"] != entry["score"]


class TestRegistryFailure:
    def test_unreachable_registry_is_not_a_phantom(self):
        """REGRESSION: every registry call used to raise on a network error,
        and an unhandled exception exits 1 -- the same code as a finding. A
        bad network day must never look like a security discovery."""
        entry = score_package(metadata(exists=None, lookup_ok=False))

        assert entry["tier"] == "UNVERIFIED"
        assert entry["exists"] is None
        assert entry["score"] == 0

    def test_unreachable_registry_reports_almost_no_confidence(self):
        entry = score_package(metadata(exists=None, lookup_ok=False))

        assert entry["confidence"] == 0

    def test_unverified_never_satisfies_a_gate(self):
        """`--fail-on low` is the loosest gate there is; absence of evidence
        must not clear even that one."""
        assert risk.meets_threshold("UNVERIFIED", "low") is False
        assert risk.meets_threshold("UNVERIFIED", "critical") is False


class TestPhantomConfidence:
    def test_a_definitive_absence_is_high_confidence(self):
        entry = score_package(metadata(exists=False))

        assert entry["tier"] == "PHANTOM"
        assert entry["confidence"] == risk.PHANTOM_CONFIDENCE

    def test_phantom_confidence_is_not_absolute(self):
        """Registries go briefly inconsistent, and an unclaimed name can be
        registered a minute after the check."""
        assert risk.PHANTOM_CONFIDENCE < 100

    def test_phantom_and_unverified_are_different_outcomes(self):
        absent = score_package(metadata(exists=False))
        unknown = score_package(metadata(exists=None, lookup_ok=False))

        assert absent["tier"] != unknown["tier"]
        assert absent["confidence"] > unknown["confidence"]


class TestResolutionUncertainty:
    def test_unresolved_identity_lowers_confidence(self):
        """Doubt about *which* package is being judged undercuts the whole
        assessment, separately from how much metadata came back."""
        resolution = {"resolution_status": "unresolved", "resolution_source": None}

        confident = score_confidence(metadata())
        doubtful = score_confidence(metadata(), resolution)

        assert doubtful["confidence"] == (
            confident["confidence"] - risk.RESOLUTION_PENALTIES["unresolved"]
        )

    def test_ambiguous_identity_lowers_confidence(self):
        resolution = {"resolution_status": "ambiguous", "resolution_source": "mapping"}

        result = score_confidence(metadata(), resolution)

        assert result["confidence"] < 100
        assert result["confidence_note"]

    def test_registry_inferred_identity_costs_a_little(self):
        """A distribution of that name existing is weaker evidence than a
        curated mapping."""
        resolution = {"resolution_status": "verified", "resolution_source": "registry"}

        result = score_confidence(metadata(), resolution)

        assert result["confidence"] == 100 - risk.REGISTRY_IDENTITY_PENALTY

    def test_a_curated_mapping_costs_nothing(self):
        resolution = {"resolution_status": "verified", "resolution_source": "mapping"}

        assert score_confidence(metadata(), resolution)["confidence"] == 100

    def test_uncertain_identity_does_not_raise_the_risk_score(self):
        """Not knowing what a package is is not evidence that it is bad."""
        resolution = {"resolution_status": "unresolved", "resolution_source": None}

        assert (
            score_package(metadata(), resolution)["score"]
            == score_package(metadata())["score"]
        )


class TestBounds:
    def test_confidence_never_goes_negative(self):
        resolution = {"resolution_status": "unresolved", "resolution_source": None}

        result = score_confidence(
            metadata(exists=None, lookup_ok=False), resolution
        )

        assert result["confidence"] == 0

    def test_confidence_never_exceeds_one_hundred(self):
        assert score_confidence(metadata())["confidence"] <= 100


class TestScoreIntegrity:
    def test_displayed_factors_reconcile_with_the_score(self):
        """The explanation must not say one thing while the engine computed
        another."""
        entry = score_package(metadata(
            ecosystem="javascript", name="loadsh", release_count=1,
            repository_url=None, description=None, weekly_downloads=3,
        ))

        assert sum(s["points"] for s in entry["signals"]) == entry["score"]

    def test_a_capped_total_says_so_rather_than_disagreeing(self):
        entry = {
            "name": "x", "ecosystem": "javascript", "tier": "CRITICAL",
            "score": 100, "confidence": 80, "unavailable_signals": [],
            "evidence": [],
            "signals": [
                {"signal": "a", "points": 60, "reason": "one"},
                {"signal": "b", "points": 60, "reason": "two"},
            ],
        }

        output = cli.format_risk_entry(entry, indent="")

        assert "capped from 120" in output


class TestCliPresentation:
    def test_concise_output_omits_the_evidence_breakdown(self):
        entry = score_package(metadata(name="loadsh", release_count=1))

        assert "Evidence quality" not in cli.format_risk_entry(entry)

    def test_explain_shows_the_evidence_breakdown(self):
        entry = score_package(metadata(name="loadsh", release_count=1))

        output = cli.format_risk_entry(entry, explain=True)

        assert "Evidence quality" in output
        assert "registry answered" in output

    def test_confidence_appears_in_the_header(self):
        entry = score_package(metadata(name="loadsh", release_count=1))

        assert "confidence" in cli.format_risk_entry(entry)

    def test_unverified_section_states_the_scan_is_incomplete(self):
        output = cli.format_unverified_section({"unverified_packages": [
            {"name": "requests", "ecosystem": "python", "found_in": "requirements.txt"}
        ]})

        assert "registry unreachable" in output
        assert "not a finding" in output

    def test_no_unverified_section_when_everything_was_checked(self):
        assert cli.format_unverified_section({"unverified_packages": []}) == ""


class TestExitCodes:
    def test_an_incomplete_scan_is_a_scan_error_not_a_finding(self):
        """The distinction the exit codes exist for: "the scanner could not
        run" must stay separable from "your dependencies are bad"."""
        report = {"error": None, "phantom_packages": [], "risk": [],
                  "unresolved_imports": [],
                  "unverified_packages": [{"name": "requests"}]}

        assert cli.exit_code_for(report) == cli.EXIT_SCAN_ERROR

    def test_a_complete_clean_scan_is_still_clean(self):
        report = {"error": None, "phantom_packages": [], "risk": [],
                  "unresolved_imports": [], "unverified_packages": []}

        assert cli.exit_code_for(report) == cli.EXIT_CLEAN

    def test_reports_predating_the_new_key_still_work(self):
        report = {"error": None, "phantom_packages": [], "risk": []}

        assert cli.exit_code_for(report) == cli.EXIT_CLEAN
