"""
Tests for the risk scoring engine.

The load-bearing invariant here is that an *unavailable* signal must never be
scored as a *bad* signal. npm publishes free download counts and PyPI does
not, so getting that wrong would quietly add points to every Python package
in every scan.
"""

from datetime import datetime, timedelta, timezone

import pytest

from risk import (
    MAX_SCORE,
    edit_distance,
    nearest_popular_package,
    score_package,
    tier_for,
)


def days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def metadata(**overrides):
    """A healthy, unremarkable package; override fields to make it suspicious."""
    base = {
        "name": "some-package",
        "ecosystem": "python",
        "exists": True,
        "first_release": days_ago(2000),
        "release_count": 40,
        "repository_url": "https://github.com/org/some-package",
        "description": "A perfectly ordinary library for doing things.",
        "maintainer_count": 4,
        "weekly_downloads": 500_000,
    }
    base.update(overrides)
    return base


def points_for(report, signal_name):
    for signal in report["signals"]:
        if signal["signal"] == signal_name:
            return signal["points"]
    return 0


class TestEditDistance:
    def test_identical(self):
        assert edit_distance("requests", "requests") == 0

    def test_substitution_insertion_deletion(self):
        assert edit_distance("requests", "reqvests") == 1
        assert edit_distance("express", "expres") == 1
        assert edit_distance("lodash", "lodashh") == 1

    @pytest.mark.parametrize("typo,real", [
        ("reqeusts", "requests"),
        ("loadsh", "lodash"),
        ("axios", "axois"),
    ])
    def test_transposition_counts_as_one_edit(self, typo, real):
        """Swapped adjacent characters are among the most common typosquat
        techniques. Plain Levenshtein charges them 2, which would drop the
        exact pattern this signal exists to catch into a weaker band."""
        assert edit_distance(typo, real) == 1

    def test_empty_strings(self):
        assert edit_distance("", "abc") == 3
        assert edit_distance("abc", "") == 3


class TestNearestPopularPackage:
    def test_finds_a_close_popular_name(self):
        assert nearest_popular_package("reqeusts", "python") == ("requests", 1)

    def test_a_popular_name_is_not_a_typosquat_of_another(self):
        """`requests` is one edit from `request`, but both are real and
        widely used. A package that is itself popular is never flagged."""
        assert nearest_popular_package("requests", "python") is None
        assert nearest_popular_package("request", "javascript") is None

    def test_unrelated_name_has_no_near_neighbour(self):
        assert nearest_popular_package("some-unrelated-library", "python") is None

    def test_scoped_npm_name_is_normalised(self):
        assert nearest_popular_package("@lodash", "javascript") is None

    def test_unknown_ecosystem_is_not_an_error(self):
        assert nearest_popular_package("anything", "rust") is None


class TestPhantomPackages:
    def test_missing_package_is_its_own_tier_at_max_score(self):
        report = score_package(metadata(name="auto-retry-httpx", exists=False))

        assert report["tier"] == "PHANTOM"
        assert report["score"] == MAX_SCORE
        assert report["exists"] is False

    def test_phantom_still_reports_typosquat_proximity(self):
        report = score_package(metadata(name="reqeusts", exists=False))

        reasons = " ".join(s["reason"] for s in report["signals"])
        assert "does not exist" in reasons
        assert "requests" in reasons


class TestMetadataSignals:
    def test_healthy_package_scores_zero(self):
        report = score_package(metadata())

        assert report["score"] == 0
        assert report["tier"] == "LOW"
        assert report["signals"] == []

    @pytest.mark.parametrize("age_days,expected", [(3, 30), (60, 20), (200, 10), (2000, 0)])
    def test_age_bands(self, age_days, expected):
        report = score_package(metadata(first_release=days_ago(age_days)))
        assert points_for(report, "age") == expected

    @pytest.mark.parametrize("releases,expected", [(1, 15), (3, 8), (40, 0)])
    def test_release_count_bands(self, releases, expected):
        report = score_package(metadata(release_count=releases))
        assert points_for(report, "releases") == expected

    def test_missing_repository_link(self):
        report = score_package(metadata(repository_url=None))
        assert points_for(report, "repository") == 15

    def test_missing_description(self):
        assert points_for(score_package(metadata(description=None)), "description") == 10

    def test_very_short_description(self):
        assert points_for(score_package(metadata(description="tool")), "description") == 5

    @pytest.mark.parametrize("maintainers,expected", [(0, 15), (1, 5), (4, 0)])
    def test_maintainer_bands(self, maintainers, expected):
        report = score_package(metadata(maintainer_count=maintainers))
        assert points_for(report, "maintainers") == expected

    @pytest.mark.parametrize("downloads,expected", [(3, 25), (400, 15), (5000, 5), (900_000, 0)])
    def test_download_bands(self, downloads, expected):
        report = score_package(metadata(weekly_downloads=downloads))
        assert points_for(report, "downloads") == expected

    def test_unparseable_release_date_is_treated_as_unavailable(self):
        report = score_package(metadata(first_release="not a date"))
        assert points_for(report, "age") == 0
        assert "age" in report["unavailable_signals"]


class TestUnavailableSignalsAreNotPenalties:
    def test_missing_signals_add_no_points(self):
        report = score_package(metadata(
            weekly_downloads=None, maintainer_count=None, release_count=None,
            first_release=None,
        ))

        assert report["score"] == 0
        assert report["tier"] == "LOW"

    def test_missing_signals_are_reported_as_unavailable(self):
        report = score_package(metadata(weekly_downloads=None, maintainer_count=None))

        assert set(report["unavailable_signals"]) == {"downloads", "maintainers"}

    def test_a_typical_pypi_package_is_not_penalised_for_registry_limits(self):
        """PyPI publishes neither download counts nor a usable maintainer
        field, so a perfectly healthy PyPI package must still score 0."""
        report = score_package(metadata(
            ecosystem="python", weekly_downloads=None, maintainer_count=None
        ))

        assert report["score"] == 0
        assert report["tier"] == "LOW"


class TestScoreAggregation:
    def test_points_accumulate_across_signals(self):
        report = score_package(metadata(
            first_release=days_ago(3), release_count=1, repository_url=None
        ))

        assert report["score"] == 30 + 15 + 15
        assert report["tier"] == "HIGH"

    def test_score_is_capped_at_the_maximum(self):
        report = score_package(metadata(
            name="reqeusts", first_release=days_ago(1), release_count=1,
            repository_url=None, description=None, maintainer_count=0,
            weekly_downloads=0,
        ))

        assert report["score"] == MAX_SCORE
        assert report["tier"] == "CRITICAL"

    def test_every_awarded_point_carries_a_reason(self):
        report = score_package(metadata(
            first_release=days_ago(3), release_count=1, repository_url=None
        ))

        assert report["signals"]
        for signal in report["signals"]:
            assert signal["reason"].strip()
            assert signal["points"] > 0


class TestTiers:
    @pytest.mark.parametrize("score,tier", [
        (0, "LOW"), (19, "LOW"), (20, "MEDIUM"), (49, "MEDIUM"),
        (50, "HIGH"), (79, "HIGH"), (80, "CRITICAL"), (100, "CRITICAL"),
    ])
    def test_thresholds(self, score, tier):
        assert tier_for(score) == tier
