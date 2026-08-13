import requests

from known_aliases import KNOWN_PYTHON_ALIASES

_SESSION = requests.Session()
_TIMEOUT = 10


def _pypi_status(package: str) -> int:
    resp = _SESSION.get(f"https://pypi.org/pypi/{package}/json", timeout=_TIMEOUT)
    return resp.status_code


def exists_on_pypi(package: str) -> bool:
    if _pypi_status(package) == 200:
        return True
    # The bare import name isn't on PyPI under that exact name -- check
    # whether it's a known case where the importable name differs from the
    # distribution name (e.g. `import jwt` -> distributed as `PyJWT`)
    # before concluding it's hallucinated.
    alias = KNOWN_PYTHON_ALIASES.get(package)
    if alias:
        return _pypi_status(alias) == 200
    return False


def exists_on_npm(package: str) -> bool:
    resp = _SESSION.get(f"https://registry.npmjs.org/{package}", timeout=_TIMEOUT)
    return resp.status_code == 200


def exists(package: str, language: str) -> bool:
    if language == "python":
        return exists_on_pypi(package)
    if language == "javascript":
        return exists_on_npm(package)
    raise ValueError(f"unsupported language: {language}")
