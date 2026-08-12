"""
slopsquat-scan: check a public repo's declared dependencies against the real
PyPI/npm registries, to catch phantom (hallucinated) packages that already
made it into a codebase.
"""

import argparse
import json
import sys
from pathlib import Path

from scanner.repo_scan import scan_repo


def cmd_scan(args):
    report = scan_repo(args.repo_url)
    print(json.dumps(report, indent=2))

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.out}", file=sys.stderr)

    if report["error"]:
        return 1
    return 1 if report["phantom_packages"] else 0


def cmd_batch(args):
    repos_file = Path(args.repos_file)
    repo_urls = [
        line.strip() for line in repos_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    any_phantom = False
    for repo_url in repo_urls:
        print(f"Scanning {repo_url} ...", file=sys.stderr)
        report = scan_repo(repo_url)

        safe_name = repo_url.rstrip("/").split("/")[-2:]
        safe_name = "_".join(safe_name).replace(".git", "")
        out_path = out_dir / f"{safe_name}.json"
        out_path.write_text(json.dumps(report, indent=2))

        if report["error"]:
            print(f"  error: {report['error']}", file=sys.stderr)
        else:
            print(
                f"  {report['packages_checked']} packages checked, "
                f"{len(report['phantom_packages'])} phantom",
                file=sys.stderr,
            )
            if report["phantom_packages"]:
                any_phantom = True

    return 1 if any_phantom else 0


def main():
    parser = argparse.ArgumentParser(
        prog="slopsquat-scan",
        description="Check a repo's declared dependencies for phantom (hallucinated) packages.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a single repo")
    scan_parser.add_argument("repo_url", help="e.g. https://github.com/org/repo")
    scan_parser.add_argument("--out", help="Path to write the JSON report to")
    scan_parser.set_defaults(func=cmd_scan)

    batch_parser = subparsers.add_parser("batch", help="Scan many repos from a file")
    batch_parser.add_argument("repos_file", help="Text file, one repo URL per line")
    batch_parser.add_argument(
        "--out-dir", default="scan_results",
        help="Directory to write one JSON report per repo (default: scan_results)",
    )
    batch_parser.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
