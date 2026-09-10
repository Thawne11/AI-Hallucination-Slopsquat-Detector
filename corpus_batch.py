"""
Generate a hallucination corpus from a frontier model, through the Batch API.

Why this exists: every empirical finding in this project rests on two small
local models that almost nobody ships code with. The names that actually get
squatted come from the models developers really use. This closes that gap.

Why batch: a straight 50% discount, and nothing about building a corpus is
latency-sensitive. Most batches finish inside an hour.

Nothing here spends money by accident. The commands split along that line:

    estimate   free, offline, no API key -- what would this cost?
    submit     SPENDS MONEY -- creates the batch
    status     free -- has it finished?
    collect    free -- fetch results, extract packages, check the registry

Start with `estimate`, then `submit --limit 10` for a few cents to prove the
pipeline end to end, then the real run.

Output matches the shape reanalyze_corrected.py and registration_timing.py
already consume, so no downstream analysis changes.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from extractor import extract_code_blocks, extract_packages
from prompts import PROMPTS
from registry import exists

STATE_PATH = Path("corpus_batch_state.json")
OUTPUT_PATH = Path("frontier_corpus.json")
RAW_PATH = Path("frontier_corpus_raw.json")

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_SAMPLES = 10
MAX_OUTPUT_TOKENS = 4096
REGISTRY_SLEEP = 0.1

# Cached 2026-06-24, USD per million tokens. Verify against
# https://www.anthropic.com/pricing before relying on an estimate -- these
# are a convenience, not a quote.
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
BATCH_DISCOUNT = 0.5

# Output tokens dominate the bill and can only be estimated before the fact.
# Measured from the local runs: generated code samples ran 100-150 lines.
ASSUMED_OUTPUT_TOKENS = 1000

INSTRUCTION = (
    " Only output the code in a single fenced code block, no explanation."
)


def build_requests(samples: int, limit: int | None = None) -> list[dict]:
    """One request per (prompt, sample). custom_id carries both back."""
    requests = []
    for prompt in PROMPTS:
        for sample in range(samples):
            requests.append({
                "custom_id": f"{prompt['id']}::{sample}",
                "prompt_id": prompt["id"],
                "language": prompt["language"],
                "sample": sample,
                "text": prompt["task"] + INSTRUCTION,
            })
    return requests[:limit] if limit else requests


def estimate_tokens(text: str) -> int:
    """Rough character-based estimate, deliberately not an API call.

    `estimate` has to work with no key and no network, so this trades a
    little accuracy for costing nothing. Input tokens are a rounding error
    here anyway -- output dominates.
    """
    return max(1, len(text) // 4)


def estimate_cost(requests: list[dict], model: str, batch: bool,
                  output_tokens: int = ASSUMED_OUTPUT_TOKENS) -> dict:
    if model not in PRICING:
        raise ValueError(
            f"no cached price for {model}; known: {', '.join(sorted(PRICING))}"
        )

    input_rate, output_rate = PRICING[model]
    input_tokens = sum(estimate_tokens(r["text"]) for r in requests)
    total_output = len(requests) * output_tokens

    multiplier = BATCH_DISCOUNT if batch else 1.0
    input_cost = input_tokens / 1_000_000 * input_rate * multiplier
    output_cost = total_output / 1_000_000 * output_rate * multiplier

    return {
        "model": model,
        "batch": batch,
        "requests": len(requests),
        "input_tokens": input_tokens,
        "output_tokens": total_output,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
        "assumed_output_tokens_each": output_tokens,
    }


def format_estimate(estimate: dict) -> str:
    lines = [
        f"Model:            {estimate['model']}",
        f"Requests:         {estimate['requests']:,}",
        f"Pricing:          {'Batch API (50% off)' if estimate['batch'] else 'standard'}",
        "",
        f"Input tokens:     {estimate['input_tokens']:,}  "
        f"(${estimate['input_cost']:.2f})",
        f"Output tokens:    {estimate['output_tokens']:,}  "
        f"(${estimate['output_cost']:.2f})  "
        f"assuming {estimate['assumed_output_tokens_each']:,} each",
        "",
        f"ESTIMATED TOTAL:  ${estimate['total_cost']:.2f}",
        "",
        "Output tokens dominate and can only be guessed before the fact. If "
        "generations run longer than assumed, cost scales linearly -- which "
        "you would see in a small --limit run first.",
    ]
    return "\n".join(lines)


def _client():
    import anthropic

    return anthropic.Anthropic()


def cmd_estimate(args):
    requests = build_requests(args.samples, args.limit)
    print(format_estimate(
        estimate_cost(requests, args.model, batch=not args.no_batch,
                      output_tokens=args.output_tokens)
    ))
    return 0


def cmd_submit(args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = build_requests(args.samples, args.limit)
    estimate = estimate_cost(requests, args.model, batch=True,
                             output_tokens=args.output_tokens)

    print(format_estimate(estimate))
    print()
    if not args.yes:
        answer = input("This will spend money. Type 'yes' to submit: ").strip()
        if answer.lower() != "yes":
            print("Not submitted.")
            return 1

    batch = _client().messages.batches.create(requests=[
        Request(
            custom_id=r["custom_id"],
            params=MessageCreateParamsNonStreaming(
                model=args.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=[{"role": "user", "content": r["text"]}],
            ),
        )
        for r in requests
    ])

    STATE_PATH.write_text(json.dumps({
        "batch_id": batch.id,
        "model": args.model,
        "samples": args.samples,
        "limit": args.limit,
        "requests": {r["custom_id"]: r for r in requests},
        "estimate": estimate,
    }, indent=2) + "\n")

    print(f"\nSubmitted batch {batch.id} ({batch.processing_status})")
    print(f"State written to {STATE_PATH}")
    print("Check with: python3 corpus_batch.py status")
    return 0


def _load_state() -> dict:
    if not STATE_PATH.exists():
        print(f"No {STATE_PATH}. Submit a batch first.", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(STATE_PATH.read_text())


def cmd_status(args):
    state = _load_state()
    batch = _client().messages.batches.retrieve(state["batch_id"])
    counts = batch.request_counts

    print(f"Batch:      {batch.id}")
    print(f"Status:     {batch.processing_status}")
    print(f"Succeeded:  {counts.succeeded}")
    print(f"Errored:    {counts.errored}")
    print(f"Processing: {counts.processing}")

    if batch.processing_status == "ended":
        print("\nReady. Collect with: python3 corpus_batch.py collect")
    return 0


def classify(text: str, language: str, cache: dict) -> tuple[list[str], list[str]]:
    """Packages found in a generation, and which of them do not exist.

    Deliberately the same primitives the local pipeline uses, so the output
    is directly comparable and the existing analysis scripts consume it
    unchanged.
    """
    packages = set()
    for block in extract_code_blocks(text):
        packages |= extract_packages(block, language)

    hallucinated = []
    for name in sorted(packages):
        key = (language, name)
        if key not in cache:
            cache[key] = exists(name, language)
            time.sleep(REGISTRY_SLEEP)
        # None means the registry could not be reached; that is not evidence
        # of absence and must not enter the corpus as a hallucination.
        if cache[key] is False:
            hallucinated.append(name)
    return sorted(packages), hallucinated


def cmd_collect(args):
    state = _load_state()
    client = _client()

    batch = client.messages.batches.retrieve(state["batch_id"])
    if batch.processing_status != "ended":
        print(f"Batch is {batch.processing_status}, not ended. Wait and retry.",
              file=sys.stderr)
        return 2

    generations = {}
    errors = []
    for result in client.messages.batches.results(state["batch_id"]):
        if result.result.type == "succeeded":
            message = result.result.message
            generations[result.custom_id] = "".join(
                block.text for block in message.content if block.type == "text"
            )
        else:
            errors.append({"custom_id": result.custom_id,
                           "type": result.result.type})

    RAW_PATH.write_text(json.dumps(generations, indent=2, sort_keys=True) + "\n")
    print(f"Collected {len(generations)} generations ({len(errors)} failed)")

    cache: dict[tuple[str, str], bool | None] = {}
    records = []
    for custom_id, text in sorted(generations.items()):
        request = state["requests"][custom_id]
        packages, hallucinated = classify(text, request["language"], cache)
        records.append({
            "model": state["model"],
            "prompt_id": request["prompt_id"],
            "sample": request["sample"],
            "packages_found": packages,
            "hallucinated_packages": hallucinated,
        })
        if hallucinated:
            print(f"  [{request['prompt_id']} #{request['sample'] + 1}] "
                  f"HALLUCINATED: {hallucinated}")

    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n")

    distinct = {n for r in records for n in r["hallucinated_packages"]}
    with_hallucination = sum(1 for r in records if r["hallucinated_packages"])

    print(f"\nPHR: {with_hallucination}/{len(records)} "
          f"({with_hallucination / len(records):.1%})" if records else "\nNo records")
    print(f"Distinct hallucinated names: {len(distinct)}")
    print(f"\nWrote {OUTPUT_PATH} and {RAW_PATH}")
    if errors:
        print(f"{len(errors)} request(s) failed; see the batch in the console.")
    return 0


def main():
    # Shared flags live on a parent parser so they work *after* the
    # subcommand, which is where anyone would naturally type them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"model to generate with (default: {DEFAULT_MODEL})",
    )
    common.add_argument(
        "--samples", type=int, default=DEFAULT_SAMPLES,
        help=f"generations per prompt (default: {DEFAULT_SAMPLES})",
    )
    common.add_argument(
        "--limit", type=int,
        help="cap total requests -- use a small value for a cheap smoke test",
    )
    common.add_argument(
        "--output-tokens", type=int, default=ASSUMED_OUTPUT_TOKENS,
        help="assumed output tokens per generation, for costing",
    )

    parser = argparse.ArgumentParser(
        prog="corpus_batch",
        description="Generate a hallucination corpus from a frontier model.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate_parser = subparsers.add_parser(
        "estimate", parents=[common],
        help="What would this cost? Free, offline, no API key.")
    estimate_parser.add_argument(
        "--no-batch", action="store_true",
        help="price at standard rates instead of the Batch API discount",
    )
    estimate_parser.set_defaults(func=cmd_estimate)

    submit_parser = subparsers.add_parser(
        "submit", parents=[common], help="SPENDS MONEY: create the batch")
    submit_parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt")
    submit_parser.set_defaults(func=cmd_submit)

    subparsers.add_parser(
        "status", parents=[common], help="Has the batch finished?"
    ).set_defaults(func=cmd_status)
    subparsers.add_parser(
        "collect", parents=[common], help="Fetch results and build the corpus"
    ).set_defaults(func=cmd_collect)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
