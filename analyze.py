"""
Manual-mode version of run.py: instead of calling the Anthropic API, reads
responses you pasted by hand from the free Claude.ai chat into responses/*.txt
(one file per prompt id, see prompts.py) and runs the same slopsquatting
detection over them.
"""

import json
from collections import defaultdict
from pathlib import Path

from extractor import extract_code_blocks, extract_packages
from prompts import PROMPTS
from registry import exists

RESPONSES_DIR = Path("responses")


def main():
    results = []
    package_cache: dict[tuple[str, str], bool] = {}
    missing = []

    for prompt in PROMPTS:
        response_path = RESPONSES_DIR / f"{prompt['id']}.txt"
        if not response_path.exists():
            missing.append(response_path.name)
            continue

        response_text = response_path.read_text()
        code_blocks = extract_code_blocks(response_text)
        packages = set()
        for block in code_blocks:
            packages |= extract_packages(block, prompt["language"])

        hallucinated = []
        for pkg in sorted(packages):
            cache_key = (prompt["language"], pkg)
            if cache_key not in package_cache:
                package_cache[cache_key] = exists(pkg, prompt["language"])
            if not package_cache[cache_key]:
                hallucinated.append(pkg)

        print(f"{prompt['id']}: {len(packages)} packages, "
              f"{len(hallucinated)} hallucinated {hallucinated or ''}")

        results.append({
            "prompt_id": prompt["id"],
            "language": prompt["language"],
            "sample": 0,
            "packages_found": sorted(packages),
            "hallucinated_packages": hallucinated,
            "raw_response": response_text,
        })

    if missing:
        print("\nSkipped (no response file found):")
        for name in missing:
            print(f"  responses/{name}")

    if not results:
        print("\nNo responses found yet -- nothing to report.")
        return

    with open("report.json", "w") as f:
        json.dump(results, f, indent=2)

    write_markdown_report(results)
    print("\nWrote report.json and report.md")


def write_markdown_report(results):
    by_prompt = defaultdict(list)
    for r in results:
        by_prompt[r["prompt_id"]].append(r)

    total = len(results)
    with_hallucination = sum(1 for r in results if r["hallucinated_packages"])
    all_hallucinated = sorted({
        pkg for r in results for pkg in r["hallucinated_packages"]
    })

    lines = [
        "# Slopsquatting Detection Report (manual mode, via Claude.ai)",
        "",
        f"- Prompts analyzed: {total}",
        f"- Generations containing at least one hallucinated package: "
        f"{with_hallucination}/{total} ({with_hallucination / total:.0%})",
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
