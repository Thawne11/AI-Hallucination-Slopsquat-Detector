"""
slopsquat-scan: check a codebase's declared dependencies against the real
PyPI/npm registries, to catch phantom (hallucinated) packages.

Works on a working copy on disk or on a remote repo:

    slopsquat-scan scan .
    slopsquat-scan scan ./some/project
    slopsquat-scan scan https://github.com/org/repo

Exit codes are distinct so CI can tell the two failure kinds apart:
0 clean, 1 phantom dependency found, 2 the scan itself failed.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from registry import fetch_metadata
from risk import score_package
from scanner.repo_scan import looks_like_remote, scan

EXIT_CLEAN = 0
EXIT_PHANTOM_FOUND = 1
EXIT_SCAN_ERROR = 2

# Risk at or above this is worth surfacing in the summary. Below it, a package
# is unremarkable and listing it would bury the findings that matter.
RISK_REPORTING_THRESHOLD = 20


def report_filename(target: str) -> str:
    """A filesystem-safe report name for a scan target."""
    if looks_like_remote(target):
        parts = target.rstrip("/").split("/")[-2:]
        return "_".join(parts).replace(".git", "")
    return os.path.basename(os.path.abspath(target)) or "root"


def format_report(report: dict) -> str:
    if report["error"]:
        return f"Error scanning {report['target']}: {report['error']}"

    phantoms = report["phantom_packages"]
    lines = [
        f"Target:                {report['target']}",
        f"Manifests found:       {len(report['manifest_files'])}",
        f"Dependencies checked:  {report['packages_checked']}",
        "",
    ]

    if not phantoms:
        lines.append("No phantom dependencies found.")
        return "\n".join(lines)

    noun = "dependency" if len(phantoms) == 1 else "dependencies"
    lines.append(f"{len(phantoms)} phantom {noun}:")
    width = max(len(p["name"]) for p in phantoms)
    for phantom in phantoms:
        lines.append(
            f"  {phantom['name']:<{width}}  ({phantom['ecosystem']})  "
            f"{phantom['found_in']}"
        )
    lines.append("")
    lines.append(
        "These names are not on the registry. Verify each one before "
        "installing -- a name an LLM invented is exactly what a slopsquatting "
        "attacker registers."
    )
    return "\n".join(lines)


def format_risk_entry(entry: dict, indent: str = "  ") -> str:
    """One package's risk verdict, with the reason for every point awarded.

    The reasons are the point of the output. A bare number cannot be argued
    with or acted on; "3 days old, one release, no repository link" can.
    """
    lines = [
        f"{indent}{entry['name']}  [{entry['tier']} {entry['score']}/100]"
        f"  ({entry['ecosystem']})"
    ]
    for signal in entry["signals"]:
        lines.append(f"{indent}  - {signal['reason']}  (+{signal['points']})")
    if entry.get("unavailable_signals"):
        lines.append(
            f"{indent}  - not scored, unavailable for this registry: "
            + ", ".join(entry["unavailable_signals"])
        )
    return "\n".join(lines)


def format_risk_section(report: dict) -> str:
    notable = [
        entry for entry in report.get("risk", [])
        if entry["score"] >= RISK_REPORTING_THRESHOLD
    ]
    if not notable:
        return "\nRisk: nothing above the reporting threshold."

    lines = ["", f"Risk ({len(notable)} package(s) worth a look):"]
    lines.extend(format_risk_entry(entry) for entry in notable)
    lines.append("")
    lines.append(
        "Scores are heuristic triage, not proof of anything -- they rank what "
        "deserves a human look."
    )
    return "\n".join(lines)


def exit_code_for(report: dict) -> int:
    if report["error"]:
        return EXIT_SCAN_ERROR
    return EXIT_PHANTOM_FOUND if report["phantom_packages"] else EXIT_CLEAN


def cmd_check(args):
    """Score a single package name without needing a project to scan."""
    metadata = fetch_metadata(args.package, args.ecosystem)
    entry = score_package(metadata)

    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        print(format_risk_entry(entry, indent=""))

    if not entry["exists"]:
        return EXIT_PHANTOM_FOUND
    return EXIT_PHANTOM_FOUND if entry["score"] >= RISK_REPORTING_THRESHOLD else EXIT_CLEAN


def cmd_scan(args):
    report = scan(args.target, with_risk=args.risk)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
        if args.risk:
            print(format_risk_section(report))

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.out}", file=sys.stderr)

    return exit_code_for(report)


def cmd_batch(args):
    targets = [
        line.strip() for line in Path(args.targets_file).read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    worst = EXIT_CLEAN
    for target in targets:
        print(f"Scanning {target} ...", file=sys.stderr)
        report = scan(target)

        (out_dir / f"{report_filename(target)}.json").write_text(
            json.dumps(report, indent=2)
        )

        if report["error"]:
            print(f"  error: {report['error']}", file=sys.stderr)
        else:
            print(
                f"  {report['packages_checked']} packages checked, "
                f"{len(report['phantom_packages'])} phantom",
                file=sys.stderr,
            )
        worst = max(worst, exit_code_for(report))

    return worst


def main():
    parser = argparse.ArgumentParser(
        prog="slopsquat-scan",
        description=(
            "Check a codebase's declared dependencies for phantom "
            "(hallucinated) packages."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="Scan a local directory or a remote repo"
    )
    scan_parser.add_argument(
        "target",
        help="a local path (e.g. . or ./project) or a repo URL",
    )
    scan_parser.add_argument(
        "--json", action="store_true", help="Print the full JSON report instead of a summary"
    )
    scan_parser.add_argument(
        "--risk", action="store_true",
        help=(
            "Also score each dependency for slopsquat risk (age, downloads, "
            "repository, typosquat proximity). Slower: it reads each package's "
            "full registry record."
        ),
    )
    scan_parser.add_argument("--out", help="Also write the JSON report to this path")
    scan_parser.set_defaults(func=cmd_scan)

    check_parser = subparsers.add_parser(
        "check", help="Risk-score a single package name"
    )
    check_parser.add_argument("package", help="package name, e.g. requests")
    check_parser.add_argument(
        "--ecosystem", choices=["python", "javascript"], default="python",
        help="which registry to look it up on (default: python)",
    )
    check_parser.add_argument(
        "--json", action="store_true", help="Print the full JSON verdict"
    )
    check_parser.set_defaults(func=cmd_check)

    batch_parser = subparsers.add_parser(
        "batch", help="Scan many targets listed in a file"
    )
    batch_parser.add_argument(
        "targets_file", help="Text file, one local path or repo URL per line"
    )
    batch_parser.add_argument(
        "--out-dir", default="scan_results",
        help="Directory to write one JSON report per target (default: scan_results)",
    )
    batch_parser.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
