"""
The accuracy benchmark, and a guard on the benchmark itself.

A benchmark that cannot fail is worse than no benchmark: it manufactures
confidence. These tests pin the current numbers so a regression breaks CI,
and separately check that the metric is actually sensitive to the failure
this project cares most about.
"""

import pytest

import import_resolver
from benchmark import corpus
from benchmark import run_benchmark
from benchmark.run_benchmark import (
    ReplayRegistry,
    load_snapshot,
    run_classification,
    run_risk_ranking,
    run_structural,
    summarize,
    write_report,
)
from known_aliases import KNOWN_PYTHON_ALIASES


@pytest.fixture(scope="module")
def summary():
    return summarize()


class TestClassificationAccuracy:
    def test_no_legitimate_package_is_flagged(self, summary):
        """Precision. Every false positive here is a real library the tool
        would have sent somebody chasing."""
        classification = summary["classification"]
        wrongly_flagged = [
            r["case"].name for r in classification["results"]
            if r["case"].expected == corpus.EXISTS and r["predicted"] != corpus.EXISTS
        ]

        assert wrongly_flagged == []
        assert classification["precision"] == 1.0

    def test_no_invented_name_is_missed(self, summary):
        """Recall. Every false negative is an invented package the tool waved
        through."""
        classification = summary["classification"]
        missed = [
            r["case"].name for r in classification["results"]
            if r["case"].expected == corpus.PHANTOM and r["predicted"] != corpus.PHANTOM
        ]

        assert missed == []
        assert classification["recall"] == 1.0

    def test_every_case_class_is_fully_correct(self, summary):
        by_kind: dict[str, list] = {}
        for result in summary["classification"]["results"]:
            by_kind.setdefault(result["case"].kind, []).append(result)

        wrong = {
            kind: [r["case"].name for r in results if not r["correct"]]
            for kind, results in by_kind.items()
            if any(not r["correct"] for r in results)
        }

        assert wrong == {}

    def test_the_corpus_covers_every_known_failure_class(self):
        """Each of these exists because the scanner got it wrong once."""
        kinds = {case.kind for case in corpus.CASES}

        assert {
            "real_popular", "import_alias", "import_identity",
            "hallucinated", "invented_plausible", "ambiguous_import",
        } <= kinds

    def test_the_corpus_is_not_trivially_small(self):
        assert len(corpus.CASES) >= 40


class TestStructuralAccuracy:
    def test_every_project_shape_matches_expectations(self, summary):
        wrong = [
            (o["project"].name, o["detail"])
            for o in summary["structural"] if not o["correct"]
        ]

        assert wrong == []

    def test_structural_corpus_covers_the_fixed_false_positives(self):
        names = {project.name for project in corpus.PROJECT_CASES}

        assert {
            "test_fixtures", "monorepo_siblings", "grpc_stubs",
            "local_modules",
        } <= names


class TestRiskRanking:
    def test_known_typosquats_rank_above_low(self, summary):
        wrong = [o["name"] for o in summary["risk"] if not o["correct"]]

        assert wrong == []


class TestMetricSensitivity:
    """The benchmark's own guard.

    An earlier version counted only PHANTOM predictions as positives, so a
    real package reported as UNRESOLVED cost nothing -- precision stayed at
    100% while the tool wrongly flagged two ordinary libraries. These pin the
    corrected definition by breaking things on purpose and checking the
    numbers actually move.
    """

    def test_an_unresolved_real_package_counts_against_precision(self, monkeypatch):
        """Reverting the cv2 mapping leaves a real library unresolvable. That
        is a false positive and precision must say so."""
        monkeypatch.setattr(
            import_resolver, "KNOWN_PYTHON_ALIASES",
            {k: v for k, v in KNOWN_PYTHON_ALIASES.items() if k != "cv2"},
        )
        snapshot = load_snapshot()
        snapshot["metadata"].pop("python::cv2", None)

        classification = run_classification(ReplayRegistry(snapshot))

        assert classification["precision"] < 1.0
        assert classification["false_positive"] >= 1

    def test_a_missed_invented_name_counts_against_recall(self):
        snapshot = load_snapshot()
        # Pretend an invented name turned out to exist after all.
        snapshot["metadata"]["javascript::js2pdf"]["exists"] = True

        classification = run_classification(ReplayRegistry(snapshot))

        assert classification["recall"] < 1.0
        assert classification["false_negative"] >= 1

    def test_a_structural_regression_is_detected(self, monkeypatch):
        monkeypatch.setattr(run_benchmark, "PROJECT_CASES", [corpus.ProjectCase(
            "regressed", kind="structural", expected_findings=0,
            files={"requirements.txt": "auto-retry-httpx\n"},
            include_imports=False,
        )])

        outcomes = run_structural(ReplayRegistry(load_snapshot()))

        assert any(not o["correct"] for o in outcomes)

    def test_a_risk_ranking_regression_is_detected(self, monkeypatch):
        monkeypatch.setattr(run_benchmark, "RISK_CASES", [
            ("requests", "python", "typosquat", "an ordinary package cannot rank risky"),
        ])

        outcomes = run_risk_ranking(ReplayRegistry(load_snapshot()))

        assert any(not o["correct"] for o in outcomes)


class TestReport:
    def test_report_renders_with_the_headline_numbers(self, summary):
        report = write_report(summary)

        assert "Precision" in report and "Recall" in report
        assert "## Structural" in report
        assert "## Risk ranking" in report

    def test_report_states_what_it_cannot_measure(self, summary):
        """The corpus can only contain failure classes somebody has already
        thought of, which is precisely where every entry came from."""
        report = write_report(summary)

        assert "cannot measure error classes nobody has thought of" in report
