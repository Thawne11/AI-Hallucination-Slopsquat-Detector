"""
Records the live registry's answers for every name in the corpus, once.

The benchmark has to be both grounded and deterministic, and those pull in
opposite directions: hitting PyPI and npm on every run would make the
numbers depend on the network, rate limits and whatever was published this
morning, while inventing the answers would measure the corpus against
itself. Recording real answers once and replaying them settles it.

Run this only when the corpus changes, and review the diff -- a snapshot
that changes unexpectedly means the world changed, which is itself worth
knowing. Requires network:

    python3 -m benchmark.record_snapshot
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from benchmark.corpus import CASES, snapshot_keys
from import_resolver import ImportNameResolver
from registry import distribution_exists, fetch_metadata

SNAPSHOT_PATH = Path(__file__).parent / "snapshot.json"


def key(name: str, ecosystem: str) -> str:
    return f"{ecosystem}::{name}"


def main():
    metadata = {}
    for name, ecosystem in snapshot_keys():
        print(f"  fetching {ecosystem}::{name}")
        metadata[key(name, ecosystem)] = fetch_metadata(name, ecosystem)

    # use_environment=False so the recorded resolutions describe the mapping
    # and the registry, not whatever happens to be installed on this machine.
    resolver = ImportNameResolver(
        exists_probe=distribution_exists, use_environment=False
    )

    resolutions = {}
    for case in CASES:
        if not case.as_import:
            continue
        resolution = resolver.resolve(case.name)
        resolutions[case.name] = resolution

        distribution = resolution.get("distribution_name")
        if distribution and key(distribution, case.ecosystem) not in metadata:
            print(f"  fetching resolved {case.ecosystem}::{distribution}")
            metadata[key(distribution, case.ecosystem)] = fetch_metadata(
                distribution, case.ecosystem
            )

    SNAPSHOT_PATH.write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "resolutions": resolutions,
    }, indent=2, sort_keys=True) + "\n")

    print(f"\nWrote {SNAPSHOT_PATH} "
          f"({len(metadata)} records, {len(resolutions)} resolutions)")


if __name__ == "__main__":
    main()
