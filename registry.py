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


# ---------------------------------------------------------------------------
# Metadata
#
# The existence check above already fetches the full registry record and then
# discards everything except the status code. The risk scoring in risk.py uses
# what was being thrown away.
#
# Every field is Optional, and None means "could not be determined" -- never
# "zero" or "bad". Scoring must not penalise a package for a signal this
# ecosystem does not publish.
# ---------------------------------------------------------------------------

def _empty_metadata(package: str, ecosystem: str, exists_flag: bool) -> dict:
    return {
        "name": package,
        "ecosystem": ecosystem,
        "exists": exists_flag,
        "first_release": None,
        "release_count": None,
        "repository_url": None,
        "description": None,
        "maintainer_count": None,
        "weekly_downloads": None,
    }


def _pypi_repository_url(info: dict) -> str | None:
    project_urls = info.get("project_urls") or {}
    for key, url in project_urls.items():
        if key.lower() in {"source", "repository", "source code", "homepage", "code"}:
            return url
    return info.get("home_page") or None


def fetch_pypi_metadata(package: str) -> dict:
    response = _SESSION.get(f"https://pypi.org/pypi/{package}/json", timeout=_TIMEOUT)
    if response.status_code != 200:
        return _empty_metadata(package, "python", exists_flag=False)

    payload = response.json()
    info = payload.get("info") or {}
    releases = payload.get("releases") or {}

    upload_times = [
        files[0].get("upload_time_iso_8601")
        for files in releases.values()
        if files and files[0].get("upload_time_iso_8601")
    ]

    metadata = _empty_metadata(package, "python", exists_flag=True)
    metadata.update({
        "first_release": min(upload_times) if upload_times else None,
        "release_count": len(releases) or None,
        "repository_url": _pypi_repository_url(info),
        "description": info.get("summary") or None,
        # PyPI's author fields are not a usable signal: `requests`, one of the
        # most-installed packages in existence, reports author=None because the
        # project moved that information into project_urls. Treating absence as
        # suspicious would flag well-maintained packages, so this stays None.
        "maintainer_count": None,
        # PyPI publishes no free download endpoint. pypistats.org rate-limits
        # aggressively (observed: HTTP 429 on a single unauthenticated call),
        # so this signal is simply unavailable for Python rather than guessed.
        "weekly_downloads": None,
    })
    return metadata


def fetch_npm_metadata(package: str) -> dict:
    response = _SESSION.get(f"https://registry.npmjs.org/{package}", timeout=_TIMEOUT)
    if response.status_code != 200:
        return _empty_metadata(package, "javascript", exists_flag=False)

    payload = response.json()
    times = payload.get("time") or {}
    version_times = {k: v for k, v in times.items() if k not in ("created", "modified")}
    repository = payload.get("repository")

    metadata = _empty_metadata(package, "javascript", exists_flag=True)
    metadata.update({
        "first_release": times.get("created"),
        "release_count": len(version_times) or None,
        "repository_url": (
            repository.get("url") if isinstance(repository, dict) else repository
        ),
        "description": payload.get("description") or None,
        "maintainer_count": len(payload.get("maintainers") or []),
        "weekly_downloads": fetch_npm_weekly_downloads(package),
    })
    return metadata


def fetch_npm_weekly_downloads(package: str) -> int | None:
    try:
        response = _SESSION.get(
            f"https://api.npmjs.org/downloads/point/last-week/{package}",
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        return response.json().get("downloads")
    except (requests.RequestException, ValueError):
        return None


def fetch_metadata(package: str, language: str) -> dict:
    if language == "python":
        return fetch_pypi_metadata(package)
    if language == "javascript":
        return fetch_npm_metadata(package)
    raise ValueError(f"unsupported language: {language}")
