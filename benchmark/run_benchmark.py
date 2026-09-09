"""
Measures the scanner against the labelled corpus, offline.

Reports three things, kept separate because they are different claims:

1. **Classification** -- does a name correspond to a real distribution?
   Precision and recall over *any* finding the tool raises, broken down by
   case class so the dominant error class is visible rather than averaged
   away.
2. **Structural** -- does a project whose shape has previously caused false
   positives still come back clean?
3. **Risk ranking** -- do known-bad-but-real packages score as risky? Kept
   out of the precision figure: "is 40/100 correct?" has no ground truth,
   while "does the live lodash typosquat rank above LOW" does.

    python3 -m benchmark.run_benchmark
"""

import json
import tempfile
from pathlib import Path

from benchmark.corpus import (
    AMBIGUOUS,
    CASES,
    EXISTS,
    PHANTOM,
    PROJECT_CASES,
    RISK_CASES,
)
from import_resolver import ImportNameResolver
from risk import score_package, tier_rank
from scanner import repo_scan
from scanner.repo_scan import scan_path

SNAPSHOT_PATH = Path(__file__).parent / "snapshot.json"
REPORT_PATH = Path(__file__).parent.parent / "BENCHMARK.md"

UNRESOLVED = "unresolved"


def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text())


class ReplayRegistry:
    """Answers from the recorded snapshot instead of the network."""

    def __init__(self, snapshot: dict):
        self.metadata = snapshot["metadata"]

    def fetch(self, name: str, ecosystem: str) -> dict | None:
        return self.metadata.get(f"{ecosystem}::{name}")

    def exists(self, name: str, ecosystem: str) -> bool:
        record = self.fetch(name, ecosystem)
        # A name absent from the snapshot was never recorded because nothing
        # in the corpus expects it to exist.
        return bool(record and record["exists"])

    def resolver(self) -> ImportNameResolver:
        return ImportNameResolver(
            exists_probe=lambda name: self.exists(name, "python"),
            use_environment=False,
        )


def classify(case, replay: ReplayRegistry) -> tuple[str, str | None]:
    """(predicted label, distribution actually checked)."""
    name = case.name

    if case.as_import:
        resolution = replay.resolver().resolve(name)
        status = resolution["resolution_status"]
        if status == "ambiguous":
            return AMBIGUOUS, None
        if status == "unresolved":
            return UNRESOLVED, None
        name = resolution["distribution_name"]

    record = replay.fetch(name, case.ecosystem)
    if record is None:
        return UNRESOLVED, name
    return (EXISTS if record["exists"] else PHANTOM), name


def run_classification(replay: ReplayRegistry) -> dict:
    results = []
    for case in CASES:
        predicted, checked = classify(case, replay)
        results.append({
            "case": case, "predicted": predicted, "checked": checked,
            "correct": predicted == case.expected,
        })

    # A "positive" is the tool raising *any* finding about a name, not
    # specifically calling it phantom.
    #
    # An earlier version of this counted only PHANTOM predictions, and was
    # therefore blind to the failure this project cares most about: a real
    # package reported as UNRESOLVED is still a flag a developer has to chase
    # down. Reverting the cv2 and yaml mappings left precision sitting at
    # 100% while the tool wrongly flagged two perfectly ordinary libraries.
    flagged = {PHANTOM, UNRESOLVED, AMBIGUOUS}
    should_flag = {PHANTOM, AMBIGUOUS}

    true_positive = sum(
        1 for r in results
        if r["case"].expected in should_flag and r["predicted"] == r["case"].expected
    )
    false_positive = sum(
        1 for r in results
        if r["case"].expected not in should_flag and r["predicted"] in flagged
    )
    false_negative = sum(
        1 for r in results
        if r["case"].expected in should_flag and r["predicted"] != r["case"].expected
    )

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0

    return {
        "results": results,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "correct": sum(1 for r in results if r["correct"]),
        "total": len(results),
    }


def run_structural(replay: ReplayRegistry) -> list[dict]:
    original_exists = repo_scan.registry_exists
    original_sleep = repo_scan._REGISTRY_SLEEP
    repo_scan.registry_exists = replay.exists
    repo_scan._REGISTRY_SLEEP = 0

    try:
        outcomes = []
        for project in PROJECT_CASES:
            with tempfile.TemporaryDirectory() as directory:
                for rel_path, contents in project.files.items():
                    path = Path(directory) / rel_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(contents)

                report = scan_path(
                    directory,
                    include_imports=project.include_imports,
                    resolver=replay.resolver(),
                )

            found = len(report["phantom_packages"]) + len(report["unresolved_imports"])
            outcomes.append({
                "project": project,
                "found": found,
                "correct": found == project.expected_findings,
                "detail": (
                    [p["name"] for p in report["phantom_packages"]]
                    + [u["name"] for u in report["unresolved_imports"]]
                ),
            })
        return outcomes
    finally:
        repo_scan.registry_exists = original_exists
        repo_scan._REGISTRY_SLEEP = original_sleep


def run_risk_ranking(replay: ReplayRegistry) -> list[dict]:
    outcomes = []
    for name, ecosystem, kind, note in RISK_CASES:
        record = replay.fetch(name, ecosystem)
        entry = score_package(record) if record else None
        ranked = bool(entry and tier_rank(entry["tier"]) >= tier_rank("MEDIUM"))
        outcomes.append({
            "name": name, "kind": kind, "note": note,
            "tier": entry["tier"] if entry else "MISSING",
            "score": entry["score"] if entry else 0,
            "correct": ranked,
        })
    return outcomes


def summarize() -> dict:
    replay = ReplayRegistry(load_snapshot())
    return {
        "classification": run_classification(replay),
        "structural": run_structural(replay),
        "risk": run_risk_ranking(replay),
    }


def write_report(summary: dict) -> str:
    classification = summary["classification"]

    by_kind: dict[str, list] = {}
    for result in classification["results"]:
        by_kind.setdefault(result["case"].kind, []).append(result)

    lines = [
        "# Scanner accuracy benchmark",
        "",
        "Measured against `benchmark/corpus.py`, replaying registry answers "
        "recorded in `benchmark/snapshot.json`. Offline and deterministic.",
        "",
        "Every case class below exists because the scanner got that class "
        "wrong at some point during development.",
        "",
        "## Classification (does this name have a real distribution?)",
        "",
        f"- **Precision {classification['precision']:.0%}** -- "
        f"{classification['false_positive']} legitimate package(s) wrongly flagged",
        f"- **Recall {classification['recall']:.0%}** -- "
        f"{classification['false_negative']} name(s) that should have been flagged and were not",
        f"- {classification['correct']}/{classification['total']} cases classified correctly",
        "",
        "| Case class | Correct | Total |",
        "|---|---|---|",
    ]
    for kind, results in sorted(by_kind.items()):
        correct = sum(1 for r in results if r["correct"])
        lines.append(f"| {kind} | {correct} | {len(results)} |")

    mismatches = [r for r in classification["results"] if not r["correct"]]
    lines.append("")
    if mismatches:
        lines.append("### Misclassified")
        lines.append("")
        for result in mismatches:
            case = result["case"]
            lines.append(
                f"- `{case.name}` ({case.kind}): expected {case.expected}, "
                f"got {result['predicted']}"
            )
    else:
        lines.append("No misclassifications.")

    lines += ["", "## Structural (project shapes that caused false positives)", ""]
    lines.append("| Project | Findings | Expected | |")
    lines.append("|---|---|---|---|")
    for outcome in summary["structural"]:
        mark = "ok" if outcome["correct"] else "MISMATCH"
        lines.append(
            f"| {outcome['project'].name} | {outcome['found']} | "
            f"{outcome['project'].expected_findings} | {mark} |"
        )

    lines += ["", "## Risk ranking (real packages that should score as risky)", ""]
    lines.append("| Package | Tier | Score | |")
    lines.append("|---|---|---|---|")
    for outcome in summary["risk"]:
        mark = "ok" if outcome["correct"] else "MISMATCH"
        lines.append(
            f"| {outcome['name']} | {outcome['tier']} | {outcome['score']} | {mark} |"
        )

    lines += [
        "",
        "## What this does and does not measure",
        "",
        "The corpus is hand-labelled and small. It measures whether the "
        "scanner still handles the cases it is *known* to have got wrong, "
        "plus a sample of ordinary packages it must leave alone. It cannot "
        "measure error classes nobody has thought of yet -- which is exactly "
        "the category every one of these entries came from originally.",
        "",
        "Risk *scores* are not scored for correctness. There is no ground "
        "truth for \"is 40/100 the right number\", so only the ranking claim "
        "is checked: a known typosquat must land above LOW.",
        "",
    ]
    return "\n".join(lines)


def main():
    summary = summarize()
    report = write_report(summary)
    REPORT_PATH.write_text(report + "\n")

    classification = summary["classification"]
    print(f"classification : precision {classification['precision']:.0%}  "
          f"recall {classification['recall']:.0%}  "
          f"({classification['correct']}/{classification['total']} correct)")
    structural_ok = sum(1 for o in summary["structural"] if o["correct"])
    print(f"structural     : {structural_ok}/{len(summary['structural'])} projects correct")
    risk_ok = sum(1 for o in summary["risk"] if o["correct"])
    print(f"risk ranking   : {risk_ok}/{len(summary['risk'])} ranked as expected")
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
