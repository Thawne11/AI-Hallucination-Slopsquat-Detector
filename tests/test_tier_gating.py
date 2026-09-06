"""
Tier severity ordering, which --fail-on depends on.
"""

import pytest

from risk import GATEABLE_TIERS, TIER_ORDER, meets_threshold, tier_rank


class TestTierOrdering:
    def test_severity_increases_along_the_order(self):
        ranks = [tier_rank(tier) for tier in TIER_ORDER]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks)

    def test_phantom_outranks_every_scored_tier(self):
        """A name that resolves to nothing is the one case where installing
        it either breaks or fetches whatever gets registered there later, so
        it has to sit above CRITICAL rather than alongside it."""
        for tier in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            assert tier_rank("PHANTOM") > tier_rank(tier)

    def test_tier_names_are_case_insensitive(self):
        assert tier_rank("high") == tier_rank("HIGH")
        assert meets_threshold("CRITICAL", "high") is True

    def test_unknown_tier_ranks_lowest_rather_than_raising(self):
        assert tier_rank("nonsense") == 0

    def test_every_gateable_tier_is_a_real_tier(self):
        for tier in GATEABLE_TIERS:
            assert tier.upper() in TIER_ORDER

    def test_phantom_is_not_gateable(self):
        """PHANTOM is always a finding, so offering it as a --fail-on choice
        would imply it could be opted out of."""
        assert "phantom" not in GATEABLE_TIERS


class TestMeetsThreshold:
    @pytest.mark.parametrize("tier,threshold,expected", [
        ("CRITICAL", "high", True),
        ("HIGH", "high", True),
        ("MEDIUM", "high", False),
        ("LOW", "low", True),
        ("PHANTOM", "critical", True),
        ("MEDIUM", "low", True),
    ])
    def test_threshold_comparisons(self, tier, threshold, expected):
        assert meets_threshold(tier, threshold) is expected
