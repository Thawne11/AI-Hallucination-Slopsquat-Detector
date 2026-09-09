"""
The labelled corpus the scanner is measured against.

Writing this list is half the point of the benchmark. Every case class below
exists because the scanner got that class wrong at some stage and it was
caught by somebody noticing an output looked odd. Enumerating them turns six
lucky catches into a standing check.

Ground truth is deliberately narrow and objective: does a name correspond to
a real, installable distribution? That is the claim the tool actually makes
and the one it has repeatedly got wrong. Risk *scores* are graded triage and
are measured separately -- forcing "is 40/100 correct?" into a binary would
be inventing a ground truth nobody can label.
"""

from dataclasses import dataclass, field

EXISTS = "exists"
PHANTOM = "phantom"
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Case:
    name: str
    ecosystem: str
    kind: str
    expected: str
    # True when `name` is a Python *import* name, which must be reconciled to
    # a distribution before the registry is asked anything.
    as_import: bool = False
    note: str = ""


@dataclass(frozen=True)
class ProjectCase:
    """A synthetic project whose structure has previously caused false
    positives. Ground truth is a count, because the claim under test is
    "this project contains nothing worth reporting"."""
    name: str
    files: dict
    expected_findings: int
    kind: str
    note: str = ""
    include_imports: bool = True


CASES = [
    # ---- ordinary, well-known packages: must never be flagged -------------
    *[Case(n, "python", "real_popular", EXISTS) for n in [
        "requests", "flask", "django", "numpy", "pandas", "click",
        "pytest", "urllib3", "certifi", "jinja2",
    ]],
    *[Case(n, "javascript", "real_popular", EXISTS) for n in [
        "express", "lodash", "axios", "chalk", "ws", "react",
        "typescript", "eslint",
    ]],

    # ---- import names whose distribution is spelled differently -----------
    # Six of these were reported as hallucinated at some point. Three others
    # only ever passed because a shim distribution happens to exist under the
    # import name, which is luck rather than correctness.
    *[Case(n, "python", "import_alias", EXISTS, as_import=True) for n in [
        "cv2", "yaml", "PIL", "sklearn", "bs4", "Crypto",
        "dateutil", "dotenv", "jwt", "paho", "saml2", "serial", "zmq",
    ]],

    # ---- import names that ARE the distribution name ----------------------
    *[Case(n, "python", "import_identity", EXISTS, as_import=True) for n in [
        "requests", "click", "httpx", "rich",
    ]],

    # ---- genuinely invented names, observed in real model output ---------
    # Every one of these was produced by a local model during the multi-model
    # pilot and verified absent from the registry by hand.
    *[Case(n, "python", "hallucinated", PHANTOM) for n in ["samllib"]],
    *[Case(n, "javascript", "hallucinated", PHANTOM) for n in [
        "rate-limit-memory", "rate-limiter-middleware", "ip2proxy",
        "ipaddr5", "@grpc/client", "json2htmlparser", "js2pdf",
        "@aws-sdk/client-graph-cql", "@aws-sdk/client-graphql",
    ]],

    # ---- invented names in the shape an LLM tends to produce -------------
    *[Case(n, "python", "invented_plausible", PHANTOM) for n in [
        "auto-retry-httpx", "async-retry-requests", "fastapi-jwt-refresh",
    ]],
    *[Case(n, "javascript", "invented_plausible", PHANTOM) for n in [
        "ws-reconnect-pro", "express-sliding-window",
    ]],

    # ---- an import name several distributions provide --------------------
    Case("slugify", "python", "ambiguous_import", AMBIGUOUS, as_import=True,
         note="python-slugify and awesome-slugify both ship a slugify module"),
]


# Names that exist but should score as risky. Kept apart from the
# classification corpus: this measures the risk engine's ranking, not whether
# a package is real, and the two answer different questions.
RISK_CASES = [
    ("loadsh", "javascript", "typosquat",
     "live npm typosquat of lodash, one edit away"),
]


PROJECT_CASES = [
    ProjectCase(
        "test_fixtures", kind="structural", expected_findings=0,
        note="a dependency resolver's own fixtures carry deliberately fake names",
        files={
            "requirements.txt": "requests\n",
            "tests/fixtures/invalid/pyproject.toml":
                '[project]\nname = "x"\ndependencies = ["totally-invented-fixture-dep"]\n',
        },
    ),
    ProjectCase(
        "monorepo_siblings", kind="structural", expected_findings=0,
        note="a workspace member depending on a sibling by name",
        files={
            "package.json": '{"name": "@myorg/root", "dependencies": '
                            '{"@myorg/core": "*", "express": "^4.0"}}',
            "packages/core/package.json": '{"name": "@myorg/core"}',
        },
    ),
    ProjectCase(
        "grpc_stubs", kind="structural", expected_findings=0,
        note="protoc-generated stubs are local files, not distributions",
        # Deliberately no `import grpc`: that name is itself an
        # import/distribution mismatch (grpcio), which belongs to the
        # import_alias class and would confuse what this case measures.
        files={"app.py": "import myservice_pb2\nimport myservice_pb2_grpc\n"},
    ),
    ProjectCase(
        "local_modules", kind="structural", expected_findings=0,
        note="Python resolves a bare import against the local directory",
        files={
            "app.py": "import helpers\nimport requests\nfrom pkg import thing\n",
            "helpers.py": "",
            "pkg/__init__.py": "",
        },
    ),
    ProjectCase(
        "stdlib_and_relative", kind="structural", expected_findings=0,
        note="neither is a third-party dependency",
        files={"app.py": "import os\nimport json\nfrom . import sibling\n"},
    ),
    ProjectCase(
        "manifest_is_literal", kind="structural", expected_findings=1,
        note="a requirements.txt line names a distribution and is checked as written",
        files={"requirements.txt": "auto-retry-httpx\n"},
        include_imports=False,
    ),
    ProjectCase(
        "invented_import", kind="structural", expected_findings=1,
        note="the case the tool exists for: pasted code, nothing declared yet",
        files={"app.py": "import requests\nimport auto_retry_httpx\n"},
    ),
]


def snapshot_keys() -> list[tuple[str, str]]:
    """Every (name, ecosystem) the benchmark will ask the registry about."""
    keys = {(case.name, case.ecosystem) for case in CASES}
    keys |= {(name, ecosystem) for name, ecosystem, _, _ in RISK_CASES}
    return sorted(keys)


def cases_by_kind() -> dict[str, list[Case]]:
    grouped: dict[str, list[Case]] = {}
    for case in CASES:
        grouped.setdefault(case.kind, []).append(case)
    return grouped
