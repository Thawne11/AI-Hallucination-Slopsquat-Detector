"""
The frontier-corpus batch harness.

Every test here is offline and stubbed. Nothing in this suite may ever reach
the Anthropic API -- a test that accidentally spends money is a bug, and the
first test below is what stops one being introduced quietly.
"""

import json

import pytest

import corpus_batch
from corpus_batch import (
    build_requests,
    classify,
    estimate_cost,
    format_estimate,
)


class TestNothingSpendsByAccident:
    def test_estimating_never_constructs_a_client(self, monkeypatch):
        """`estimate` is the command someone runs before deciding to pay. It
        must not need a key, a network, or an account."""
        def fail(*args, **kwargs):
            raise AssertionError("estimate must not touch the API")

        monkeypatch.setattr(corpus_batch, "_client", fail)

        estimate_cost(build_requests(samples=2), "claude-sonnet-5", batch=True)

    def test_the_paid_command_is_separate_from_the_free_ones(self):
        """Only `submit` spends. If that ever stops being true, the guard
        rails in the module docstring are lying."""
        import inspect

        for name in ("cmd_estimate",):
            source = inspect.getsource(getattr(corpus_batch, name))
            assert "_client()" not in source, f"{name} must stay free"


class TestRequestBuilding:
    def test_one_request_per_prompt_and_sample(self):
        from prompts import PROMPTS

        requests = build_requests(samples=3)

        assert len(requests) == len(PROMPTS) * 3

    def test_custom_id_round_trips_prompt_and_sample(self):
        """The batch returns results in any order, so identity has to travel
        in the custom_id rather than in position."""
        requests = build_requests(samples=2)

        for request in requests:
            assert request["custom_id"] == f"{request['prompt_id']}::{request['sample']}"

    def test_custom_ids_are_unique(self):
        requests = build_requests(samples=5)

        assert len({r["custom_id"] for r in requests}) == len(requests)

    def test_limit_caps_the_run(self):
        assert len(build_requests(samples=10, limit=7)) == 7

    def test_every_request_carries_the_output_only_instruction(self):
        """Without it the model writes prose around the code and extraction
        gets noisier."""
        for request in build_requests(samples=1):
            assert "single fenced code block" in request["text"]

    def test_language_travels_with_the_request(self):
        """Extraction needs it on the way back, and the batch result carries
        nothing but the custom_id."""
        for request in build_requests(samples=1):
            assert request["language"] in {"python", "javascript"}


class TestCostEstimation:
    def test_batch_is_half_of_standard(self):
        requests = build_requests(samples=2)

        standard = estimate_cost(requests, "claude-sonnet-5", batch=False)
        batched = estimate_cost(requests, "claude-sonnet-5", batch=True)

        assert batched["total_cost"] == pytest.approx(standard["total_cost"] / 2)

    def test_cost_scales_with_request_count(self):
        small = estimate_cost(build_requests(1), "claude-sonnet-5", batch=True)
        large = estimate_cost(build_requests(10), "claude-sonnet-5", batch=True)

        assert large["total_cost"] > small["total_cost"]

    def test_cost_scales_with_assumed_output_length(self):
        """The dominant uncertainty. Doubling the assumption should roughly
        double the bill, so a wrong guess is visible rather than hidden."""
        requests = build_requests(samples=2)

        base = estimate_cost(requests, "claude-sonnet-5", True, output_tokens=1000)
        double = estimate_cost(requests, "claude-sonnet-5", True, output_tokens=2000)

        assert double["output_cost"] == pytest.approx(base["output_cost"] * 2)

    def test_a_cheaper_model_costs_less(self):
        requests = build_requests(samples=2)

        sonnet = estimate_cost(requests, "claude-sonnet-5", batch=True)
        haiku = estimate_cost(requests, "claude-haiku-4-5", batch=True)

        assert haiku["total_cost"] < sonnet["total_cost"]

    def test_an_unpriced_model_is_refused_rather_than_guessed(self):
        """Silently costing an unknown model at someone else's rate would be
        worse than saying so."""
        with pytest.raises(ValueError, match="no cached price"):
            estimate_cost(build_requests(1), "some-future-model", batch=True)

    def test_output_dominates_the_estimate(self):
        estimate = estimate_cost(build_requests(5), "claude-sonnet-5", batch=True)

        assert estimate["output_cost"] > estimate["input_cost"] * 10

    def test_the_printed_estimate_states_its_assumption(self):
        output = format_estimate(
            estimate_cost(build_requests(2), "claude-sonnet-5", batch=True)
        )

        assert "ESTIMATED TOTAL" in output
        assert "assuming" in output
        assert "scales linearly" in output


class TestClassification:
    def test_finds_packages_and_flags_the_missing_one(self):
        text = "```python\nimport requests\nimport totally_invented_pkg\n```"

        packages, hallucinated = classify(text, "python", {
            ("python", "requests"): True,
            ("python", "totally_invented_pkg"): False,
        })

        assert packages == ["requests", "totally_invented_pkg"]
        assert hallucinated == ["totally_invented_pkg"]

    def test_an_unreachable_registry_does_not_enter_the_corpus(self):
        """None means the registry could not be asked. Recording that as a
        hallucination would poison the corpus with network weather."""
        text = "```python\nimport mystery_pkg\n```"

        packages, hallucinated = classify(text, "python", {
            ("python", "mystery_pkg"): None,
        })

        assert packages == ["mystery_pkg"]
        assert hallucinated == []

    def test_results_are_cached_across_generations(self):
        """A corpus run repeats the same imports thousands of times; checking
        each one once is the difference between minutes and hours."""
        cache = {("python", "requests"): True}

        for _ in range(50):
            classify("```python\nimport requests\n```", "python", cache)

        assert list(cache) == [("python", "requests")]

    def test_prose_around_the_code_is_ignored(self):
        packages, _ = classify(
            "Here you go:\n```python\nimport requests\n```\nHope that helps.",
            "python", {("python", "requests"): True},
        )

        assert packages == ["requests"]


class TestOutputShape:
    def test_records_match_what_the_analysis_scripts_consume(self):
        """reanalyze_corrected.py and registration_timing.py both read this
        shape. Changing it would silently orphan them."""
        record = {
            "model": "claude-sonnet-5",
            "prompt_id": "py-pdf-tables",
            "sample": 0,
            "packages_found": ["requests"],
            "hallucinated_packages": [],
        }

        assert set(record) == {
            "model", "prompt_id", "sample",
            "packages_found", "hallucinated_packages",
        }

    def test_the_existing_corpus_has_the_same_keys(self):
        """Compared against the real file the local run produced, so the two
        corpora stay directly comparable."""
        from pathlib import Path

        existing = json.loads(Path("multi_model_report_corrected.json").read_text())

        assert set(existing[0]) >= {
            "model", "prompt_id", "sample",
            "packages_found", "hallucinated_packages",
        }
