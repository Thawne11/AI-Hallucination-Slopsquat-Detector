"""
Reconciles a Python import name with the distribution name you install.

`import cv2` installs as `opencv-python`; `import yaml` installs as
`PyYAML`. Checking an import name directly against PyPI therefore asks the
wrong question, and answering it produces two different mistakes: calling a
real library hallucinated, or -- for names like `bs4` and `sklearn` that
happen to have shim distributions published under them -- appearing correct
for a reason that has nothing to do with correctness.

This layer sits between import extraction and the registry lookup:

    source imports -> resolve() -> distribution name -> registry -> risk

It deliberately does NOT decide whether anything is malicious. It answers
one narrow question -- "what would you install to get this module?" -- and
hands the answer to the machinery that already exists.

Python only. npm has no module/distribution split: an import specifier
there is the package name, so JavaScript needs no reconciliation.

Security posture
----------------
The resolver is conservative by construction. It never imports or installs
a target package to find out what it provides; the environment layer reads
installed distribution *metadata* only. Fuzzy name similarity is never used
as evidence of identity -- that belongs to typosquat detection in risk.py,
which answers the opposite question ("is this name suspiciously close to a
popular one?") and must not be confused with authoritative resolution.

Most importantly, an import this layer cannot map is reported as
UNRESOLVED, never as nonexistent. "We could not determine the distribution"
and "no such distribution exists" are different claims, and only the second
is evidence of a hallucinated package.
"""

import re
from importlib import metadata

from known_aliases import AMBIGUOUS_PYTHON_IMPORTS, KNOWN_PYTHON_ALIASES

VERIFIED = "verified"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"

SOURCE_MAPPING = "mapping"
SOURCE_ENVIRONMENT = "environment"
SOURCE_REGISTRY = "registry"


def normalize(name: str) -> str:
    """PEP 503 normalization: the form PyPI itself compares names in.

    Safe because it is a documented equivalence (`My_Package`, `my-package`
    and `my.package` are the same project to PyPI), unlike fuzzy matching,
    which is a guess and is kept well away from this module.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _result(import_name, distribution_name=None, status=UNRESOLVED,
            confidence=0.0, source=None, candidates=None,
            registry_checked=False) -> dict:
    return {
        "import_name": import_name,
        "distribution_name": distribution_name,
        "resolution_status": status,
        "resolution_confidence": confidence,
        "resolution_source": source,
        "candidates": candidates or [],
        # Whether a registry gave a definitive answer for this name. Without
        # it, "not found" is indistinguishable from "could not ask", and the
        # scanner would report offline runs as discoveries.
        "registry_checked": registry_checked,
    }


def _environment_distributions(import_name: str) -> list[str]:
    """Distributions in the *running* environment providing this module.

    Reads installed dist-info metadata. It does not import the package, so
    no third-party code is executed to answer the question.
    """
    try:
        mapping = metadata.packages_distributions()
    except Exception:
        return []
    return sorted(mapping.get(import_name, []))


class ImportNameResolver:
    """Resolves import names to distribution names, with caching.

    `exists_probe(name) -> bool | None` checks whether a distribution name
    exists. Returning None means "could not determine" (offline, timeout),
    which is kept distinct from False. Injectable so the resolver can run
    fully offline in tests.
    """

    def __init__(self, exists_probe=None, use_environment: bool = True):
        self._exists_probe = exists_probe
        self._use_environment = use_environment
        self._cache: dict[str, dict] = {}
        self.probe_calls = 0

    def resolve(self, import_name: str) -> dict:
        if import_name in self._cache:
            return self._cache[import_name]

        result = self._resolve_uncached(import_name)
        self._cache[import_name] = result
        return result

    def resolve_all(self, import_names) -> dict[str, dict]:
        """Resolve many names, each looked up at most once."""
        return {name: self.resolve(name) for name in import_names}

    def _resolve_uncached(self, import_name: str) -> dict:
        # Layer 0: names known to be provided by several distributions must
        # stay ambiguous. Choosing one would mean scoring a package the
        # developer may not be using.
        candidates = AMBIGUOUS_PYTHON_IMPORTS.get(import_name)
        if candidates:
            return _result(
                import_name, status=AMBIGUOUS, candidates=sorted(candidates),
                source=SOURCE_MAPPING,
            )

        # Layer 1: curated mapping.
        mapped = KNOWN_PYTHON_ALIASES.get(import_name)
        if mapped:
            return _result(
                import_name, distribution_name=mapped, status=VERIFIED,
                confidence=1.0, source=SOURCE_MAPPING,
            )

        # Layer 2: what the running environment says, if the package happens
        # to be installed here.
        if self._use_environment:
            installed = _environment_distributions(import_name)
            if len(installed) == 1:
                return _result(
                    import_name, distribution_name=installed[0],
                    status=VERIFIED, confidence=1.0,
                    source=SOURCE_ENVIRONMENT,
                )
            if len(installed) > 1:
                return _result(
                    import_name, status=AMBIGUOUS, candidates=installed,
                    source=SOURCE_ENVIRONMENT,
                )

        # Layer 3: ask the registry whether a distribution of this name
        # exists. Strong evidence, but not proof that the distribution
        # provides this module, hence confidence below 1.
        if self._exists_probe is not None:
            self.probe_calls += 1
            exists = self._exists_probe(import_name)
            if exists is True:
                return _result(
                    import_name, distribution_name=import_name,
                    status=VERIFIED, confidence=0.9, source=SOURCE_REGISTRY,
                    registry_checked=True,
                )
            if exists is False:
                # Definitively absent under its own name. Still UNRESOLVED,
                # not "nonexistent": some other distribution could provide
                # this module. The caller decides what to do with that,
                # knowing the registry was actually consulted.
                return _result(import_name, registry_checked=True)

        # Layer 4: no evidence either way.
        return _result(import_name)


_DEFAULT_RESOLVER: ImportNameResolver | None = None


def default_resolver() -> ImportNameResolver:
    """Process-wide resolver, so its cache survives across a whole scan."""
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        from registry import distribution_exists

        _DEFAULT_RESOLVER = ImportNameResolver(exists_probe=distribution_exists)
    return _DEFAULT_RESOLVER


def resolve(import_name: str) -> dict:
    return default_resolver().resolve(import_name)
