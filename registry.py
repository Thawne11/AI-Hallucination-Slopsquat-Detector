import requests

_SESSION = requests.Session()
_TIMEOUT = 10


def exists_on_pypi(package: str) -> bool:
    resp = _SESSION.get(f"https://pypi.org/pypi/{package}/json", timeout=_TIMEOUT)
    return resp.status_code == 200


def exists_on_npm(package: str) -> bool:
    resp = _SESSION.get(f"https://registry.npmjs.org/{package}", timeout=_TIMEOUT)
    return resp.status_code == 200


def exists(package: str, language: str) -> bool:
    if language == "python":
        return exists_on_pypi(package)
    if language == "javascript":
        return exists_on_npm(package)
    raise ValueError(f"unsupported language: {language}")
