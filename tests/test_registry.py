"""
Tests for registry existence checking.

The HTTP layer is stubbed so the suite runs offline and deterministically --
no network dependency and no registry rate-limit flakiness.
"""

import pytest

import registry
from known_aliases import KNOWN_PYTHON_ALIASES

PYPI_PREFIX = "https://pypi.org/pypi/"
NPM_PREFIX = "https://registry.npmjs.org/"


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSession:
    """Answers 200 for names in `available`, 404 otherwise, and records every
    URL requested so tests can assert on lookup behaviour."""

    def __init__(self, available):
        self.available = set(available)
        self.requested_names = []

    @staticmethod
    def _name_from_url(url):
        if url.startswith(PYPI_PREFIX):
            return url[len(PYPI_PREFIX):].removesuffix("/json")
        if url.startswith(NPM_PREFIX):
            return url[len(NPM_PREFIX):]
        raise AssertionError(f"unexpected registry URL: {url}")

    def get(self, url, timeout=None):
        name = self._name_from_url(url)
        self.requested_names.append(name)
        return FakeResponse(200 if name in self.available else 404)


@pytest.fixture
def fake_registry(monkeypatch):
    def _install(available):
        session = FakeSession(available)
        monkeypatch.setattr(registry, "_SESSION", session)
        return session

    return _install


class TestPyPI:
    def test_existing_package(self, fake_registry):
        fake_registry({"requests"})
        assert registry.exists_on_pypi("requests") is True

    def test_missing_package(self, fake_registry):
        fake_registry(set())
        assert registry.exists_on_pypi("totally-fake-pkg-xyz123") is False

    def test_missing_package_does_not_trigger_an_alias_lookup(self, fake_registry):
        session = fake_registry(set())
        registry.exists_on_pypi("totally-fake-pkg-xyz123")
        assert session.requested_names == ["totally-fake-pkg-xyz123"]

    @pytest.mark.parametrize(
        "import_name,distribution_name", sorted(KNOWN_PYTHON_ALIASES.items())
    )
    def test_regression_import_name_resolves_via_distribution_name(
        self, fake_registry, import_name, distribution_name
    ):
        """REGRESSION: `import jwt` / `import paho` / `import saml2` are the
        correct import names for PyJWT / paho-mqtt / pysaml2. The bare import
        name does not resolve on PyPI, so a naive existence check reported
        these real, correctly-used packages as hallucinated -- which is what
        inflated the raw PHR in the multi-model pilot."""
        session = fake_registry({distribution_name})

        assert registry.exists_on_pypi(import_name) is True
        assert session.requested_names == [import_name, distribution_name]

    def test_alias_that_also_does_not_resolve_is_still_missing(self, fake_registry):
        fake_registry(set())
        assert registry.exists_on_pypi("jwt") is False


class TestNpm:
    def test_existing_package(self, fake_registry):
        fake_registry({"ws"})
        assert registry.exists_on_npm("ws") is True

    def test_missing_package(self, fake_registry):
        fake_registry(set())
        assert registry.exists_on_npm("@grpc/client") is False

    def test_python_aliases_do_not_apply_to_npm(self, fake_registry):
        """The alias table maps Python import names to PyPI distribution
        names; it must not leak into npm lookups."""
        session = fake_registry({"PyJWT"})

        assert registry.exists_on_npm("jwt") is False
        assert session.requested_names == ["jwt"]


class TestDispatch:
    def test_routes_by_language(self, fake_registry):
        fake_registry({"requests", "ws"})
        assert registry.exists("requests", "python") is True
        assert registry.exists("ws", "javascript") is True

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError):
            registry.exists("some-gem", "ruby")


class JsonResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class MetadataSession:
    """Serves canned registry records keyed by URL prefix."""

    def __init__(self, payloads):
        self.payloads = payloads

    def get(self, url, timeout=None):
        for prefix, payload in self.payloads.items():
            if url.startswith(prefix):
                return JsonResponse(200, payload)
        return JsonResponse(404)


class TestMetadata:
    def test_pypi_metadata_is_extracted_from_the_record(self, monkeypatch):
        monkeypatch.setattr(registry, "_SESSION", MetadataSession({
            PYPI_PREFIX: {
                "info": {
                    "summary": "Ordinary library",
                    "project_urls": {"Source": "https://github.com/org/pkg"},
                },
                "releases": {
                    "1.0": [{"upload_time_iso_8601": "2020-01-01T00:00:00Z"}],
                    "1.1": [{"upload_time_iso_8601": "2021-01-01T00:00:00Z"}],
                },
            }
        }))

        metadata = registry.fetch_metadata("pkg", "python")

        assert metadata["exists"] is True
        assert metadata["release_count"] == 2
        assert metadata["first_release"] == "2020-01-01T00:00:00Z"
        assert metadata["repository_url"] == "https://github.com/org/pkg"
        assert metadata["description"] == "Ordinary library"

    def test_pypi_download_and_maintainer_signals_are_unavailable(self, monkeypatch):
        """PyPI has no free download endpoint and its author fields are not a
        usable signal, so both must come back as None -- meaning "unknown",
        which the scorer treats as no evidence rather than bad evidence."""
        monkeypatch.setattr(registry, "_SESSION", MetadataSession({
            PYPI_PREFIX: {"info": {}, "releases": {}}
        }))

        metadata = registry.fetch_metadata("pkg", "python")

        assert metadata["weekly_downloads"] is None
        assert metadata["maintainer_count"] is None

    def test_npm_metadata_including_downloads(self, monkeypatch):
        monkeypatch.setattr(registry, "_SESSION", MetadataSession({
            NPM_PREFIX: {
                "time": {
                    "created": "2010-12-29T19:38:25.450Z",
                    "modified": "2024-01-01T00:00:00.000Z",
                    "1.0.0": "2011-01-01T00:00:00.000Z",
                    "2.0.0": "2012-01-01T00:00:00.000Z",
                },
                "repository": {"url": "git+https://github.com/org/pkg.git"},
                "description": "An ordinary node library",
                "maintainers": [{"name": "a"}, {"name": "b"}],
            },
            "https://api.npmjs.org/downloads": {"downloads": 4321},
        }))

        metadata = registry.fetch_metadata("pkg", "javascript")

        assert metadata["exists"] is True
        assert metadata["first_release"] == "2010-12-29T19:38:25.450Z"
        assert metadata["release_count"] == 2  # created/modified are not versions
        assert metadata["maintainer_count"] == 2
        assert metadata["weekly_downloads"] == 4321

    def test_missing_package_reports_not_existing_with_empty_signals(self, monkeypatch):
        monkeypatch.setattr(registry, "_SESSION", MetadataSession({}))

        metadata = registry.fetch_metadata("nope", "python")

        assert metadata["exists"] is False
        assert metadata["release_count"] is None
        assert metadata["repository_url"] is None

    def test_unavailable_download_endpoint_is_not_zero(self, monkeypatch):
        """A failed downloads lookup must be None, not 0 -- 0 would score as
        the most suspicious possible download count."""
        monkeypatch.setattr(registry, "_SESSION", MetadataSession({
            NPM_PREFIX: {"time": {"created": "2020-01-01T00:00:00.000Z"}},
        }))

        metadata = registry.fetch_metadata("pkg", "javascript")

        assert metadata["weekly_downloads"] is None

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError):
            registry.fetch_metadata("some-gem", "ruby")
