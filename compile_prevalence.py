"""
Aggregates per-repo JSON reports from `slopsquat-scan batch` into a
prevalence comparison between the baseline (control) and AI-assisted
repo groups.

Expects two directories, each full of one JSON report per scanned repo:
  scan_results/baseline/*.json
  scan_results/ai_assisted/*.json
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt

GROUPS = {
    "baseline": Path("scan_results/baseline"),
    "ai_assisted": Path("scan_results/ai_assisted"),
}


def report_target(report: dict) -> str:
    """Scan reports used to key the scanned thing as "repo_url"; it became
    "target" when scanning gained support for local directories. The reports
    committed from the prevalence study still use the old key."""
    return report.get("target", report.get("repo_url", "unknown"))


def load_group(dir_path: Path) -> list[dict]:
    if not dir_path.exists():
        return []
    reports = []
    for path in sorted(dir_path.glob("*.json")):
        reports.append(json.loads(path.read_text()))
    return reports


def summarize(reports: list[dict]) -> dict:
    successful = [r for r in reports if not r["error"]]
    failed = [r for r in reports if r["error"]]
    with_phantom = [r for r in successful if r["phantom_packages"]]

    total_phantom = sum(len(r["phantom_packages"]) for r in successful)
    total_checked = sum(r["packages_checked"] for r in successful)

    prevalence = (len(with_phantom) / len(successful) * 100) if successful else 0.0

    return {
        "total_repos": len(reports),
        "successful_scans": len(successful),
        "failed_scans": len(failed),
        "repos_with_phantom": len(with_phantom),
        "prevalence_pct": prevalence,
        "total_packages_checked": total_checked,
        "total_phantom_found": total_phantom,
        "phantom_details": [
            {"repo": report_target(r), **p}
            for r in successful for p in r["phantom_packages"]
        ],
        "failed_repos": [{"repo": report_target(r), "error": r["error"]} for r in failed],
    }


def write_report(summaries: dict[str, dict]):
    lines = [
        "# Slopsquatting Prevalence Study",
        "",
        "Real public repos scanned with `slopsquat-scan`, comparing a "
        "baseline (control) group against repos with real AI-assisted "
        "commits, to see whether phantom dependencies show up in the wild.",
        "",
        "| Group | Repos scanned | Successful | With phantom deps | Prevalence |",
        "|---|---|---|---|---|",
    ]
    for name, s in summaries.items():
        lines.append(
            f"| {name} | {s['total_repos']} | {s['successful_scans']} | "
            f"{s['repos_with_phantom']} | {s['prevalence_pct']:.1f}% |"
        )
    lines.append("")

    for name, s in summaries.items():
        lines.append(f"## {name}")
        lines.append(
            f"- {s['total_packages_checked']} unique declared dependencies checked "
            f"across {s['successful_scans']} successfully scanned repos"
        )
        lines.append(f"- {s['total_phantom_found']} phantom dependencies found")
        if s["phantom_details"]:
            lines.append("")
            for d in s["phantom_details"]:
                lines.append(f"  - `{d['name']}` ({d['ecosystem']}) in {d['repo']} -- {d['found_in']}")
        if s["failed_repos"]:
            lines.append("")
            lines.append(f"- {len(s['failed_repos'])} repo(s) failed to scan (clone error, skipped):")
            for f in s["failed_repos"]:
                lines.append(f"  - {f['repo']}: {f['error']}")
        lines.append("")

    Path("PREVALENCE_REPORT.md").write_text("\n".join(lines))


def write_chart(summaries: dict[str, dict]):
    names = list(summaries.keys())
    rates = [summaries[n]["prevalence_pct"] for n in names]

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(names, rates, color=["#2980b9", "#c0392b"])
    ax.set_ylabel("% of repos with >=1 phantom dependency")
    ax.set_title("Phantom Dependency Prevalence: Baseline vs. AI-Assisted Repos")
    ax.set_ylim(0, max(100, max(rates) + 10) if rates else 100)
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{rate:.1f}%", ha="center")

    plt.tight_layout()
    plt.savefig("prevalence_chart.png", dpi=200)


def main():
    summaries = {}
    for group_name, dir_path in GROUPS.items():
        reports = load_group(dir_path)
        summaries[group_name] = summarize(reports)
        print(f"{group_name}: {summaries[group_name]['repos_with_phantom']}/"
              f"{summaries[group_name]['successful_scans']} "
              f"({summaries[group_name]['prevalence_pct']:.1f}%) with phantom deps")

    write_report(summaries)
    write_chart(summaries)
    print("\nWrote PREVALENCE_REPORT.md and prevalence_chart.png")


if __name__ == "__main__":
    main()
