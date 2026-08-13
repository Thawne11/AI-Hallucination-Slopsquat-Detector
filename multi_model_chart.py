"""
Renders the raw-vs-corrected PHR comparison for the multi-model pilot --
showing both numbers side by side is the point: the raw figure is inflated
by methodology artifacts (see README), and the gap between raw and
corrected is itself evidence of why the correction mattered.
"""

import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def phr_by_model(path: str) -> dict[str, float]:
    data = json.loads(Path(path).read_text())
    by_model = defaultdict(list)
    for r in data:
        by_model[r["model"]].append(r)
    return {
        model: sum(1 for r in results if r["hallucinated_packages"]) / len(results)
        for model, results in by_model.items()
    }


def main():
    raw = phr_by_model("multi_model_report.json")
    corrected = phr_by_model("multi_model_report_corrected.json")
    models = list(raw.keys())

    x = range(len(models))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    raw_bars = ax.bar([i - width / 2 for i in x], [raw[m] * 100 for m in models],
                       width, label="Raw (before correction)", color="#95a5a6")
    corrected_bars = ax.bar([i + width / 2 for i in x], [corrected[m] * 100 for m in models],
                             width, label="Corrected (after excluding artifacts)", color="#c0392b")

    ax.set_ylabel("Package Hallucination Rate (PHR)")
    ax.set_title("Hallucination Rate by Model: Raw vs. Corrected")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models)
    ax.legend()

    for bars in (raw_bars, corrected_bars):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     f"{bar.get_height():.1f}%", ha="center", fontsize=9)

    plt.tight_layout()
    plt.savefig("multi_model_chart.png", dpi=200)
    print("Wrote multi_model_chart.png (raw vs corrected)")


if __name__ == "__main__":
    main()
