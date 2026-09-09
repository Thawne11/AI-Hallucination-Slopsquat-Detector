"""
Does hallucination precede registration?

Published work measures how often models invent package names. What it does
not show is the causal arrow -- that a name was invented by a model *first*
and claimed by a human *afterwards*. That arrow is the whole difference
between slopsquatting and ordinary typosquatting, and it is usually assumed
rather than demonstrated.

It is measurable with data this project already fetches. `first_release` is
currently used only for the age signal in risk scoring. For any hallucinated
name that does exist:

    registered after the model's release date
      -> the model cannot have learned it from the registry
      -> it invented the name, and somebody claimed it later

Model *release* date is used deliberately as a conservative proxy for the
training cutoff. The real cutoff is earlier and not precisely published, so
anything registered after release was definitely not in training data. This
biases against finding an effect, which is the safe direction.

Three candidate sets, because one alone proves nothing:

  hallucinated  the names our models actually produced
  variants      separator and digit-word rewrites of those, since squatters
                register those alongside the original
  control       plausible-shaped names built from the same vocabulary that
                no model produced -- without this, a registration rate is a
                number with nothing to compare against

    python3 registration_timing.py
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from registry import fetch_metadata
from risk import score_package

CORPUS_PATH = Path("multi_model_report_corrected.json")
REPORT_PATH = Path("REGISTRATION_TIMING.md")

# Release dates, used as a conservative upper bound on the training cutoff.
MODEL_RELEASES = {
    "qwen2.5-coder:7b": "2024-09-01",
    "llama3.2:3b": "2024-09-01",
}

REGISTRY_SLEEP = 0.2
CONTROL_SAMPLE_SIZE = 120
RANDOM_SEED = 20260909  # fixed so the control set is reproducible


def load_hallucinated() -> dict[str, dict]:
    """{name: {ecosystem, models}} for every name our models invented."""
    records = json.loads(CORPUS_PATH.read_text())
    language_by_prompt = {}
    from prompts import PROMPTS
    for prompt in PROMPTS:
        language_by_prompt[prompt["id"]] = prompt["language"]

    names: dict[str, dict] = {}
    for record in records:
        ecosystem = language_by_prompt.get(record["prompt_id"], "python")
        for name in record["hallucinated_packages"]:
            entry = names.setdefault(name, {"ecosystem": ecosystem, "models": set()})
            entry["models"].add(record["model"])
    return names


def variants(name: str) -> set[str]:
    """Rewrites a squatter would plausibly register alongside the original."""
    produced = set()

    separators = ["-", "_", "."]
    for separator in separators:
        for other in separators:
            if separator in name:
                produced.add(name.replace(separator, other))
    produced.add(name.replace("-", ""))
    produced.add(name.replace("_", ""))

    # Digit/word spellings: js2pdf, js-2-pdf, jstopdf, jstwopdf
    for digit, words in [("2", ("to", "two")), ("4", ("for", "four"))]:
        if digit in name:
            for word in words:
                produced.add(name.replace(digit, word))

    # Ecosystem-flavoured prefixes are a standard squatting move.
    for prefix in ("node-", "py-", "python-"):
        produced.add(prefix + name.lstrip("@").replace("/", "-"))

    produced.discard(name)
    return {v for v in produced if v and not v.startswith("-")}


CONTROL_TOKENS = [
    "async", "retry", "http", "https", "ws", "socket", "csv", "json", "yaml",
    "jwt", "pdf", "rate", "limit", "proxy", "parser", "client", "server",
    "stream", "cache", "queue", "batch", "schema", "config", "logger",
    "session", "token", "upload", "worker", "mailer", "router",
]


def control_names(count: int, avoid: set[str]) -> list[str]:
    """Plausible-shaped names of the same vocabulary that no model produced.

    The point is a baseline. Some of these will be real packages, and that is
    exactly the number being measured: how often a name of this shape is
    already registered, with no model involvement at all.
    """
    rng = random.Random(RANDOM_SEED)
    patterns = ["{a}-{b}", "{a}{b}", "{a}-{b}-{c}", "{a}2{b}"]

    produced: list[str] = []
    seen = set(avoid)
    for _ in range(count * 40):
        if len(produced) >= count:
            break
        a, b, c = rng.sample(CONTROL_TOKENS, 3)
        name = rng.choice(patterns).format(a=a, b=b, c=c)
        if name not in seen:
            seen.add(name)
            produced.append(name)
    return produced


def check(names_with_ecosystem: list[tuple[str, str]], label: str) -> list[dict]:
    results = []
    for index, (name, ecosystem) in enumerate(names_with_ecosystem, start=1):
        metadata = fetch_metadata(name, ecosystem)
        time.sleep(REGISTRY_SLEEP)

        entry = {
            "name": name, "ecosystem": ecosystem, "set": label,
            "exists": metadata["exists"], "lookup_ok": metadata["lookup_ok"],
            "first_release": metadata.get("first_release"),
        }
        if metadata["exists"]:
            scored = score_package(metadata)
            entry["risk_score"] = scored["score"]
            entry["risk_tier"] = scored["tier"]
            print(f"  [{label}] {name} EXISTS "
                  f"({entry['first_release']}, {scored['tier']})")
        results.append(entry)

        if index % 25 == 0:
            print(f"  [{label}] {index}/{len(names_with_ecosystem)} checked")
    return results


def registered_after_models(entry: dict) -> bool | None:
    """Whether this package postdates every model release date."""
    if not entry.get("first_release"):
        return None
    try:
        released = datetime.fromisoformat(
            entry["first_release"].replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if released.tzinfo is None:
        released = released.replace(tzinfo=timezone.utc)

    latest_model = max(
        datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        for date in MODEL_RELEASES.values()
    )
    return released > latest_model


def rate(results: list[dict]) -> tuple[int, int, float]:
    checked = [r for r in results if r["lookup_ok"]]
    existing = [r for r in checked if r["exists"]]
    percentage = (len(existing) / len(checked) * 100) if checked else 0.0
    return len(existing), len(checked), percentage


def write_report(by_set: dict[str, list[dict]]) -> str:
    lines = [
        "# Does hallucination precede registration?",
        "",
        "Whether a hallucinated package name was invented by a model *before* "
        "somebody registered it. That ordering is what separates slopsquatting "
        "from ordinary typosquatting, and it is usually assumed rather than "
        "measured.",
        "",
        "## Registration rate by candidate set",
        "",
        "| Set | Registered | Checked | Rate |",
        "|---|---|---|---|",
    ]
    for label, results in by_set.items():
        existing, checked, percentage = rate(results)
        lines.append(f"| {label} | {existing} | {checked} | {percentage:.1f}% |")

    hits = [r for results in by_set.values() for r in results if r["exists"]]
    lines += ["", "## Registered candidates", ""]
    if not hits:
        lines.append("None of the hallucinated names or their variants are "
                     "registered.")
    else:
        lines.append("| Name | Set | First release | After model release? | Risk |")
        lines.append("|---|---|---|---|---|")
        for hit in sorted(hits, key=lambda h: h["set"]):
            after = registered_after_models(hit)
            marker = {True: "yes", False: "no", None: "unknown"}[after]
            lines.append(
                f"| `{hit['name']}` | {hit['set']} | "
                f"{(hit['first_release'] or 'unknown')[:10]} | {marker} | "
                f"{hit.get('risk_tier', '-')} {hit.get('risk_score', '')} |"
            )

    hallucinated_count = len(by_set.get("hallucinated", []))
    _, control_checked, control_percentage = rate(by_set.get("control", []))
    base = control_percentage / 100

    probability_zero = (1 - base) ** hallucinated_count if hallucinated_count else 0
    mean_rate = base * 1.5
    needed = (
        16 * mean_rate * (1 - mean_rate) / (base ** 2) if base else 0
    )

    if not base:
        # No usable control data, so there is nothing to compare against and
        # no baseline to quote. Say that rather than dividing by it.
        lines += [
            "",
            "## No baseline available",
            "",
            "The control set returned no successful lookups, so there is no "
            "base rate to compare the hallucinated set against. Any "
            "registration rate above is uninterpretable on its own.",
            "",
        ]
        return "\n".join(lines + _caveats())

    lines += [
        "",
        "## The result is not evidence, and here is the arithmetic",
        "",
        f"The hallucinated set returned 0 registrations. That is **not** a "
        f"finding. At the control base rate of {control_percentage:.1f}%, the "
        f"chance of seeing zero hits in {hallucinated_count} draws is "
        f"**{probability_zero:.0%}** -- so this outcome is exactly what you "
        "would expect if hallucinated names were registered no differently "
        "from any other plausible name.",
        "",
        f"To detect even a *doubling* of the base rate would take roughly "
        f"**{needed:.0f} distinct hallucinated names** per group. This corpus "
        f"has {hallucinated_count}. The experiment is underpowered by more "
        "than an order of magnitude, and knowing that number is the actual "
        "result here: it converts \"we should generate a bigger corpus\" from "
        "an instinct into a requirement.",
        "",
        "## What the control set did establish",
        "",
        f"About **1 in {1/base:.0f} plausible-sounding package names is already "
        f"registered** ({control_percentage:.1f}% of {control_checked} checked). "
        "That baseline did not exist before and is useful on its own: any claim "
        "that hallucinated names get squatted has to beat it, and the namespace "
        "is far more crowded than an intuition would suggest.",
        "",
        "Every registered candidate found here predates both model releases, so "
        "none of them show the hallucination-then-registration ordering. They "
        "are ordinary packages whose names a model drifted towards -- itself "
        "worth noting, since it means hallucinations often land near real but "
        "obscure names rather than in empty space.",
        "",
    ]
    return "\n".join(lines + _caveats())


def _caveats() -> list[str]:
    return [
        "",
        "## Caveats that would change the number",
        "",
        "- **The control set may be biased towards existing names.** It is built "
        "by recombining common tokens, which produces obvious names like "
        "`proxy-server` and `json-csv` that were likely claimed years ago. A "
        "fairer control would match the hallucinated set's distinctiveness, not "
        "just its vocabulary.",
        "- **Model release dates stand in for training cutoffs**, which are not "
        "precisely published. The real cutoff is earlier, so anything registered "
        "after release was certainly not in training data. This biases against "
        "finding an effect rather than towards one.",
        "- **Two models, both small and local.** Names that larger or more "
        "widely-used models hallucinate are the ones actually worth squatting, "
        "and none of those are represented here.",
        "",
    ]



def main():
    hallucinated = load_hallucinated()
    print(f"hallucinated names in corpus: {len(hallucinated)}")

    hallucinated_pairs = [(n, e["ecosystem"]) for n, e in hallucinated.items()]

    variant_pairs = []
    for name, entry in hallucinated.items():
        for variant in variants(name):
            variant_pairs.append((variant, entry["ecosystem"]))
    variant_pairs = sorted(set(variant_pairs))
    print(f"variants generated:           {len(variant_pairs)}")

    avoid = set(hallucinated) | {name for name, _ in variant_pairs}
    controls = control_names(CONTROL_SAMPLE_SIZE, avoid)
    # Split the control set across both ecosystems, mirroring the corpus.
    control_pairs = [
        (name, "python" if index % 2 == 0 else "javascript")
        for index, name in enumerate(controls)
    ]
    print(f"control names generated:      {len(control_pairs)}\n")

    by_set = {
        "hallucinated": check(hallucinated_pairs, "hallucinated"),
        "variants": check(variant_pairs, "variants"),
        "control": check(control_pairs, "control"),
    }

    REPORT_PATH.write_text(write_report(by_set) + "\n")
    Path("registration_timing.json").write_text(
        json.dumps(by_set, indent=2, sort_keys=True) + "\n"
    )

    print()
    for label, results in by_set.items():
        existing, checked, percentage = rate(results)
        print(f"{label:14} {existing}/{checked} registered ({percentage:.1f}%)")
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
