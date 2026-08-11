"""
AI Hallucination -> Supply Chain Risk: a "slopsquatting" detector.

Asks Claude to write code for a set of everyday coding tasks, extracts the
third-party packages it imports, and checks each one against the real PyPI /
npm registries. Packages that don't exist are exactly the names an attacker
could pre-register with malware, betting that someone will copy-paste
AI-generated code without checking (this is a real, documented attack class
known as "slopsquatting").

This tool only detects and reports. It never registers, publishes, or
touches the flagged package names on any registry.
"""

import json
import os
import time
from collections import defaultdict

from anthropic import Anthropic
from dotenv import load_dotenv

from extractor import extract_code_blocks, extract_packages
from prompts import PROMPTS
from registry import exists

load_dotenv()

MODEL = "claude-sonnet-5"
SAMPLES_PER_PROMPT = 3  # repeat each prompt to catch non-deterministic hallucinations
TEMPERATURE = 1.0


def generate_code(client: Anthropic, task: str) -> str:
    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        temperature=TEMPERATURE,
        messages=[{
            "role": "user",
            "content": f"{task} Only output the code in a single fenced code "
                       f"block, no explanation.",
        }],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def main():
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env / .env
    results = []
    package_cache: dict[tuple[str, str], bool] = {}

    for prompt in PROMPTS:
        print(f"\n=== {prompt['id']} ({prompt['language']}) ===")
        for sample_idx in range(SAMPLES_PER_PROMPT):
            response_text = generate_code(client, prompt["task"])
            code_blocks = extract_code_blocks(response_text)
            packages = set()
            for block in code_blocks:
                packages |= extract_packages(block, prompt["language"])

            hallucinated = []
            for pkg in sorted(packages):
                cache_key = (prompt["language"], pkg)
                if cache_key not in package_cache:
                    package_cache[cache_key] = exists(pkg, prompt["language"])
                    time.sleep(0.2)  # be polite to the registries
                if not package_cache[cache_key]:
                    hallucinated.append(pkg)

            print(f"  sample {sample_idx + 1}: {len(packages)} packages, "
                  f"{len(hallucinated)} hallucinated {hallucinated or ''}")

            results.append({
                "prompt_id": prompt["id"],
                "language": prompt["language"],
                "sample": sample_idx,
                "packages_found": sorted(packages),
                "hallucinated_packages": hallucinated,
                "raw_response": response_text,
            })

    with open("report.json", "w") as f:
        json.dump(results, f, indent=2)

    write_markdown_report(results)
    print("\nWrote report.json and report.md")


def write_markdown_report(results):
    by_prompt = defaultdict(list)
    for r in results:
        by_prompt[r["prompt_id"]].append(r)

    total_samples = len(results)
    samples_with_hallucination = sum(1 for r in results if r["hallucinated_packages"])
    all_hallucinated = sorted({
        pkg for r in results for pkg in r["hallucinated_packages"]
    })

    lines = [
        "# Slopsquatting Detection Report",
        "",
        f"- Model: `{MODEL}`",
        f"- Prompts: {len(by_prompt)}, samples per prompt: {SAMPLES_PER_PROMPT}, "
        f"total generations: {total_samples}",
        f"- Generations containing at least one hallucinated package: "
        f"{samples_with_hallucination}/{total_samples} "
        f"({samples_with_hallucination / total_samples:.0%})",
        f"- Unique hallucinated package names found: {len(all_hallucinated)}",
        "",
        "## Hallucinated packages by prompt",
        "",
    ]

    for prompt_id, samples in by_prompt.items():
        flagged = sorted({pkg for s in samples for pkg in s["hallucinated_packages"]})
        lines.append(f"### {prompt_id}")
        lines.append(f"- Hallucinated: {', '.join(flagged) if flagged else 'none'}")
        lines.append("")

    if all_hallucinated:
        lines.append("## All unique hallucinated package names")
        lines.append("")
        for pkg in all_hallucinated:
            lines.append(f"- `{pkg}`")

    with open("report.md", "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
