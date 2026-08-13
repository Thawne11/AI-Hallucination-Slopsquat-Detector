"""
Runs the PHR/RHR methodology (see rerun_analyze.py) across multiple models,
generating code directly via providers.py instead of staging manually-pasted
response files -- local models can be called programmatically, so the whole
pipeline runs unattended.
"""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from extractor import extract_code_blocks, extract_packages
from prompts import PROMPTS
from providers import generate
from registry import exists

MODELS = [
    ("ollama", "qwen2.5-coder:7b"),
    ("ollama", "llama3.2:3b"),
]
SAMPLES_PER_PROMPT = 10


def run_pilot(models, prompts, samples_per_prompt):
    package_cache: dict[tuple[str, str], bool] = {}
    results = []

    for provider, model in models:
        print(f"\n=== Model: {model} ===")
        for prompt in prompts:
            hallucinated_in_prompt = 0
            for sample_idx in range(samples_per_prompt):
                task_text = (
                    f"{prompt['task']} Only output the code in a single "
                    f"fenced code block, no explanation."
                )
                try:
                    response_text = generate(provider, task_text, model)
                except Exception as e:
                    print(f"  [{prompt['id']} #{sample_idx + 1}] generation failed: {e}")
                    continue

                packages = set()
                for block in extract_code_blocks(response_text):
                    packages |= extract_packages(block, prompt["language"])

                hallucinated = []
                for pkg in sorted(packages):
                    key = (prompt["language"], pkg)
                    if key not in package_cache:
                        package_cache[key] = exists(pkg, prompt["language"])
                        time.sleep(0.1)
                    if not package_cache[key]:
                        hallucinated.append(pkg)

                results.append({
                    "model": model,
                    "prompt_id": prompt["id"],
                    "sample": sample_idx,
                    "packages_found": sorted(packages),
                    "hallucinated_packages": hallucinated,
                })

                if hallucinated:
                    hallucinated_in_prompt += 1
                    print(f"  [{prompt['id']} #{sample_idx + 1}] "
                          f"HALLUCINATED: {hallucinated}")

            print(f"  {prompt['id']}: {hallucinated_in_prompt}/{samples_per_prompt} "
                  f"samples hallucinated")

    return results


def summarize(results):
    by_model = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)

    summary = {}
    for model, model_results in by_model.items():
        total = len(model_results)
        with_hallucination = sum(1 for r in model_results if r["hallucinated_packages"])
        phr = with_hallucination / total if total else 0.0

        by_prompt = defaultdict(list)
        for r in model_results:
            by_prompt[r["prompt_id"]].append(r)

        name_counts = defaultdict(int)
        name_samples = defaultdict(int)
        for prompt_id, samples in by_prompt.items():
            n = len(samples)
            counts = defaultdict(int)
            for s in samples:
                for pkg in set(s["hallucinated_packages"]):
                    counts[pkg] += 1
            for pkg, count in counts.items():
                name_counts[(prompt_id, pkg)] = count
                name_samples[(prompt_id, pkg)] = n

        summary[model] = {
            "total_samples": total,
            "samples_with_hallucination": with_hallucination,
            "phr": phr,
            "rhr_by_name": {
                f"{prompt_id}::{pkg}": count / name_samples[(prompt_id, pkg)]
                for (prompt_id, pkg), count in name_counts.items()
            },
        }
    return summary


def write_report(summary):
    lines = [
        "# Multi-Model PHR/RHR Pilot",
        "",
        "Local open-weight models, generated directly via Ollama (no manual "
        "copy-paste), following the same PHR/RHR methodology as "
        "rerun_analyze.py.",
        "",
        "| Model | Samples | With hallucination | PHR |",
        "|---|---|---|---|",
    ]
    for model, s in summary.items():
        lines.append(
            f"| {model} | {s['total_samples']} | "
            f"{s['samples_with_hallucination']} | {s['phr']:.1%} |"
        )
    lines.append("")

    for model, s in summary.items():
        lines.append(f"## {model}")
        if s["rhr_by_name"]:
            for name, rhr in s["rhr_by_name"].items():
                lines.append(f"- `{name}`: RHR = {rhr:.0%}")
        else:
            lines.append("- No hallucinated packages found.")
        lines.append("")

    Path("multi_model_report.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                         help="Quick smoke test: 2 prompts x 2 reruns x first model only")
    args = parser.parse_args()

    if args.smoke:
        models = MODELS[:1]
        prompts = PROMPTS[:2]
        samples = 2
    else:
        models = MODELS
        prompts = PROMPTS
        samples = SAMPLES_PER_PROMPT

    results = run_pilot(models, prompts, samples)

    with open("multi_model_report.json", "w") as f:
        json.dump(results, f, indent=2)

    summary = summarize(results)
    write_report(summary)

    print("\nWrote multi_model_report.json, multi_model_report.md")
    print("Run reanalyze_corrected.py then multi_model_chart.py for the "
          "corrected numbers and chart.")
    for model, s in summary.items():
        print(f"{model}: PHR = {s['phr']:.1%} "
              f"({s['samples_with_hallucination']}/{s['total_samples']})")


if __name__ == "__main__":
    main()
