"""
The registration-timing analysis.

Only the pure parts are tested: candidate generation, the date comparison and
the reporting. The registry calls are the same ones already covered in
test_registry.py, and re-testing them here would just be slower.
"""

import registration_timing as timing


class TestVariants:
    def test_separator_rewrites(self):
        produced = timing.variants("rate-limit-memory")

        assert "rate_limit_memory" in produced
        assert "rate.limit.memory" in produced
        assert "ratelimitmemory" in produced

    def test_digit_word_rewrites(self):
        """`js2pdf` and `jstopdf` are the same idea spelled two ways, and a
        squatter registers both."""
        produced = timing.variants("js2pdf")

        assert "jstopdf" in produced
        assert "jstwopdf" in produced

    def test_ecosystem_prefixes(self):
        produced = timing.variants("grpc-client")

        assert "node-grpc-client" in produced
        assert "python-grpc-client" in produced

    def test_scoped_names_are_flattened_for_prefixing(self):
        produced = timing.variants("@grpc/client")

        assert "node-grpc-client" in produced

    def test_the_original_is_never_returned(self):
        assert "js2pdf" not in timing.variants("js2pdf")

    def test_nothing_starts_with_a_separator(self):
        """A leading hyphen is not a registrable name and would waste a
        lookup."""
        for name in ["js2pdf", "@grpc/client", "rate-limit-memory"]:
            assert not any(v.startswith("-") for v in timing.variants(name))


class TestControlNames:
    def test_reproducible_for_a_fixed_seed(self):
        """The control set has to be stable, or the baseline moves every run
        and nothing can be compared across runs."""
        assert timing.control_names(20, set()) == timing.control_names(20, set())

    def test_respects_the_avoid_set(self):
        first = timing.control_names(20, set())

        second = timing.control_names(20, avoid=set(first))

        assert not set(first) & set(second)

    def test_produces_the_requested_count(self):
        assert len(timing.control_names(40, set())) == 40

    def test_names_look_like_package_names(self):
        for name in timing.control_names(30, set()):
            assert name and not name.startswith("-") and " " not in name


class TestRegisteredAfterModels:
    def test_a_recent_release_is_after(self):
        assert timing.registered_after_models(
            {"first_release": "2026-06-29T00:00:00Z"}
        ) is True

    def test_an_old_release_is_before(self):
        assert timing.registered_after_models(
            {"first_release": "2013-07-12T00:00:00Z"}
        ) is False

    def test_a_missing_date_is_unknown_not_false(self):
        """Absent evidence must not read as "predates the models", which
        would quietly discard the very cases the analysis is looking for."""
        assert timing.registered_after_models({"first_release": None}) is None

    def test_an_unparseable_date_is_unknown(self):
        assert timing.registered_after_models({"first_release": "not a date"}) is None


class TestRate:
    def test_counts_only_successful_lookups(self):
        """A registry that could not be reached is not a package that does
        not exist, and must not dilute the denominator."""
        results = [
            {"exists": True, "lookup_ok": True},
            {"exists": False, "lookup_ok": True},
            {"exists": None, "lookup_ok": False},
        ]

        existing, checked, percentage = timing.rate(results)

        assert (existing, checked) == (1, 2)
        assert percentage == 50.0

    def test_no_lookups_is_not_a_division_error(self):
        assert timing.rate([]) == (0, 0, 0.0)


class TestReport:
    def _by_set(self, hallucinated_hits=0):
        return {
            "hallucinated": [
                {"name": f"h{i}", "set": "hallucinated", "exists": i < hallucinated_hits,
                 "lookup_ok": True, "first_release": None}
                for i in range(10)
            ],
            "control": [
                {"name": f"c{i}", "set": "control", "exists": i < 11,
                 "lookup_ok": True, "first_release": "2015-01-01T00:00:00Z"}
                for i in range(120)
            ],
        }

    def test_states_that_a_null_result_is_not_evidence(self):
        report = timing.write_report(self._by_set())

        assert "not** a finding" in report or "not a finding" in report

    def test_reports_the_sample_size_needed(self):
        report = timing.write_report(self._by_set())

        assert "underpowered" in report
        assert "distinct hallucinated names" in report

    def test_publishes_the_control_baseline(self):
        report = timing.write_report(self._by_set())

        assert "9.2%" in report

    def test_lists_caveats_that_would_change_the_number(self):
        report = timing.write_report(self._by_set())

        assert "biased towards existing names" in report
        assert "training cutoffs" in report

    def test_says_so_when_nothing_is_registered(self):
        empty = {
            "hallucinated": [
                {"name": "h", "set": "hallucinated", "exists": False,
                 "lookup_ok": True, "first_release": None}
            ],
            "control": [],
        }

        assert "None of the hallucinated names" in timing.write_report(empty)
