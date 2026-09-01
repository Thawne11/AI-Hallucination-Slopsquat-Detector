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

from scanner.repo_scan import looks_like_remote, scan

EXIT_CLEAN = 0
EXIT_PHANTOM_FOUND = 1
EXIT_SCAN_ERROR = 2


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


def exit_code_for(report: dict) -> int:
    if report["error"]:
        return EXIT_SCAN_ERROR
    return EXIT_PHANTOM_FOUND if report["phantom_packages"] else EXIT_CLEAN


def cmd_scan(args):
    report = scan(args.target)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

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
    scan_parser.add_argument("--out", help="Also write the JSON report to this path")
    scan_parser.set_defaults(func=cmd_scan)

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
