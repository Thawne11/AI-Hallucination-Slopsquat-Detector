"""
Reruns the detector methodology used by published slopsquatting research
(arXiv 2501.19012, "Importing Phantoms"): rerun each prompt N times and
measure two things instead of one:

- PHR (Package Hallucination Rate): fraction of reruns that contain at
  least one hallucinated package.
- RHR (Repeated Hallucination Rate): among hallucinated names that show up
  at all, what fraction of reruns they reappear in. High RHR is the real
  attacker-relevant signal -- a name that only shows up once isn't worth
  squatting, but one that shows up in 8 of 10 reruns is predictable enough
  to profitably pre-register.

Reads responses_rerun/<prompt_id>_<n>.txt for n = 1..SAMPLES_PER_PROMPT.
"""

import json
from collections import defaultdict
from pathlib import Path

from extractor import extract_code_blocks, extract_packages
from prompts import PROMPTS
from registry import exists

RESPONSES_DIR = Path("responses_rerun")
SAMPLES_PER_PROMPT = 5
RERUN_PROMPT_IDS = {"py-pdf-tables", "py-jwt-refresh", "js-websocket-reconnect"}


def main():
    prompts = [p for p in PROMPTS if p["id"] in RERUN_PROMPT_IDS]
    package_cache: dict[tuple[str, str], bool] = {}
    per_prompt_results = defaultdict(list)
    missing = []

    for prompt in prompts:
        for n in range(1, SAMPLES_PER_PROMPT + 1):
            response_path = RESPONSES_DIR / f"{prompt['id']}_{n}.txt"
            if not response_path.exists():
                missing.append(response_path.name)
                continue

            response_text = response_path.read_text()
            packages = set()
            for block in extract_code_blocks(response_text):
                packages |= extract_packages(block, prompt["language"])

            hallucinated = []
            for pkg in sorted(packages):
                cache_key = (prompt["language"], pkg)
                if cache_key not in package_cache:
                    package_cache[cache_key] = exists(pkg, prompt["language"])
                if not package_cache[cache_key]:
                    hallucinated.append(pkg)

            per_prompt_results[prompt["id"]].append({
                "sample": n,
                "packages_found": sorted(packages),
                "hallucinated_packages": hallucinated,
            })

    if missing:
        print("Missing response files (skipped):")
        for name in missing:
            print(f"  responses_rerun/{name}")
        print()

    report = {}
    for prompt_id, samples in per_prompt_results.items():
        n_samples = len(samples)
        n_with_hallucination = sum(1 for s in samples if s["hallucinated_packages"])
        phr = n_with_hallucination / n_samples if n_samples else 0.0

        name_counts = defaultdict(int)
        for s in samples:
            for pkg in set(s["hallucinated_packages"]):
                name_counts[pkg] += 1

        rhr_by_name = {
            name: count / n_samples for name, count in name_counts.items()
        }

        report[prompt_id] = {
            "samples_run": n_samples,
            "phr": phr,
            "hallucinated_names": name_counts,
            "rhr_by_name": rhr_by_name,
            "samples": samples,
        }

        print(f"{prompt_id}: PHR = {n_with_hallucination}/{n_samples} "
              f"({phr:.0%})")
        for name, count in name_counts.items():
            print(f"  '{name}' hallucinated in {count}/{n_samples} reruns "
                  f"(RHR = {rhr_by_name[name]:.0%})")

    with open("rerun_report.json", "w") as f:
        json.dump(report, f, indent=2)

    write_markdown_report(report)
    print("\nWrote rerun_report.json and rerun_report.md")


def write_markdown_report(report):
    lines = [
        "# Rerun Detection Report (PHR / RHR methodology)",
        "",
        "Methodology follows the published slopsquatting research: rerun each "
        "prompt multiple times and measure Package Hallucination Rate (PHR) "
        "and Repeated Hallucination Rate (RHR), rather than a single sample.",
        "",
    ]

    total_samples = sum(r["samples_run"] for r in report.values())
    total_with_hallucination = sum(
        sum(1 for s in r["samples"] if s["hallucinated_packages"])
        for r in report.values()
    )
    overall_phr = total_with_hallucination / total_samples if total_samples else 0

    lines.append(f"**Overall PHR: {total_with_hallucination}/{total_samples} "
                  f"({overall_phr:.0%})**")
    lines.append("")

    for prompt_id, r in report.items():
        lines.append(f"## {prompt_id}")
        lines.append(f"- PHR: {r['phr']:.0%} ({r['samples_run']} reruns)")
        if r["hallucinated_names"]:
            for name, count in r["hallucinated_names"].items():
                lines.append(
                    f"- `{name}`: appeared in {count}/{r['samples_run']} "
                    f"reruns (RHR = {r['rhr_by_name'][name]:.0%})"
                )
        else:
            lines.append("- No hallucinated packages across any rerun.")
        lines.append("")

    with open("rerun_report.md", "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
