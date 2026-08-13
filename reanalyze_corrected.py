"""
Reanalyzes multi_model_report.json with two corrections found after
manually reviewing the raw pilot results (see README "Cross-model
comparison" for the discovery story):

1. Names ending in _pb2 / _pb2_grpc are locally-generated gRPC stub
   modules, not registry packages -- now excluded going forward in
   extractor.py, applied retroactively here since raw response text wasn't
   saved (only the already-extracted package lists were).
2. Known import-name/distribution-name mismatches (jwt, paho, saml2) are
   now resolved via known_aliases.py in registry.py -- re-checking
   existence with the corrected, alias-aware logic.

One additional manual exclusion: `your_service` (python, py-grpc-client,
llama3.2:3b sample 3) is the same class of artifact as the _pb2 cases -- a
locally-invented placeholder gRPC service module name -- but doesn't match
the suffix pattern, so it's excluded here explicitly rather than pretending
an automated rule caught it.
"""

import json
from collections import defaultdict
from pathlib import Path

from prompts import PROMPTS
from registry import exists

LANGUAGE_BY_PROMPT = {p["id"]: p["language"] for p in PROMPTS}

MANUAL_EXCLUSIONS = {("python", "your_service")}


def is_local_stub(name: str) -> bool:
    return name.endswith(("_pb2", "_pb2_grpc"))


def reclassify(packages_found, language, cache):
    hallucinated = []
    for name in packages_found:
        if language == "python" and is_local_stub(name):
            continue
        if (language, name) in MANUAL_EXCLUSIONS:
            continue
        key = (language, name)
        if key not in cache:
            cache[key] = exists(name, language)
        if not cache[key]:
            hallucinated.append(name)
    return hallucinated


def main():
    raw = json.loads(Path("multi_model_report.json").read_text())
    cache: dict[tuple[str, str], bool] = {}

    corrected = []
    for r in raw:
        language = LANGUAGE_BY_PROMPT[r["prompt_id"]]
        hallucinated = reclassify(r["packages_found"], language, cache)
        corrected.append({**r, "hallucinated_packages": hallucinated})

    by_model = defaultdict(list)
    for r in corrected:
        by_model[r["model"]].append(r)

    print("Corrected PHR (after excluding local-stub and known-alias artifacts):")
    for model, results in by_model.items():
        total = len(results)
        with_h = sum(1 for r in results if r["hallucinated_packages"])
        print(f"  {model}: {with_h}/{total} ({with_h / total:.1%})")
        for r in results:
            if r["hallucinated_packages"]:
                print(f"    [{r['prompt_id']} #{r['sample'] + 1}] {r['hallucinated_packages']}")

    Path("multi_model_report_corrected.json").write_text(json.dumps(corrected, indent=2))
    print("\nWrote multi_model_report_corrected.json")


if __name__ == "__main__":
    main()
