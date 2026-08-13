"""
Known cases where a Python module's importable name differs from its PyPI
distribution name. Discovered empirically -- each entry below was first
found because our own exists-check flagged it as "hallucinated," and manual
verification showed it was actually a real, correctly-used package under a
different distribution name on PyPI.

This list is inherently incomplete -- it only grows as new mismatches are
found in practice, not from any exhaustive source. See README "Known
import-name / distribution-name mismatches" for the discovery story behind
each entry.
"""

KNOWN_PYTHON_ALIASES = {
    "jwt": "PyJWT",
    "paho": "paho-mqtt",
    "saml2": "pysaml2",
}
