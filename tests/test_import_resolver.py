"""
Import name -> distribution name reconciliation.

Every test here runs offline: the registry probe is injected and the
environment layer is switched off unless a test is specifically exercising
it, so results never depend on what happens to be pip-installed in the venv
running the suite.
"""

import pytest

import import_resolver
from import_resolver import (
    AMBIGUOUS,
    SOURCE_ENVIRONMENT,
    SOURCE_MAPPING,
    SOURCE_REGISTRY,
    UNRESOLVED,
    VERIFIED,
    ImportNameResolver,
    normalize,
)


def offline_resolver(available=(), use_environment=False):
    """A resolver whose registry probe answers from a fixed set."""
    known = set(available)
    return ImportNameResolver(
        exists_probe=lambda name: name in known,
        use_environment=use_environment,
    )


class TestCuratedMapping:
    @pytest.mark.parametrize("import_name,distribution", [
        ("cv2", "opencv-python"),
        ("sklearn", "scikit-learn"),
        ("PIL", "Pillow"),
        ("yaml", "PyYAML"),
        ("bs4", "beautifulsoup4"),
        ("Crypto", "pycryptodome"),
        ("dateutil", "python-dateutil"),
        ("dotenv", "python-dotenv"),
        ("jwt", "PyJWT"),
    ])
    def test_known_mismatches_resolve(self, import_name, distribution):
        result = offline_resolver().resolve(import_name)

        assert result["distribution_name"] == distribution
        assert result["resolution_status"] == VERIFIED
        assert result["resolution_source"] == SOURCE_MAPPING
        assert result["resolution_confidence"] == 1.0

    def test_identity_mapping(self):
        """`requests` installs as `requests`; the answer is still explicit."""
        result = offline_resolver().resolve("requests")

        assert result["distribution_name"] == "requests"
        assert result["resolution_status"] == VERIFIED

    def test_case_difference_is_resolved_to_the_published_spelling(self):
        assert offline_resolver().resolve("flask")["distribution_name"] == "Flask"
        assert offline_resolver().resolve("django")["distribution_name"] == "Django"

    def test_mapping_wins_over_the_registry_layer(self):
        """A curated answer must not be overridden by the mere existence of
        a distribution sharing the import name -- that is exactly how a
        squatter would hijack a well-known import."""
        resolver = offline_resolver(available={"cv2"})

        result = resolver.resolve("cv2")

        assert result["distribution_name"] == "opencv-python"
        assert result["resolution_source"] == SOURCE_MAPPING
        assert resolver.probe_calls == 0


class TestNormalization:
    def test_separators_are_equivalent(self):
        assert normalize("my_package") == normalize("my-package")
        assert normalize("my.package") == normalize("my-package")

    def test_case_is_folded(self):
        assert normalize("MyPackage") == normalize("mypackage")

    def test_runs_of_separators_collapse(self):
        assert normalize("a__b") == normalize("a-b")

    def test_distinct_names_stay_distinct(self):
        """Normalization is an equivalence PyPI itself defines. It must not
        blur genuinely different names together."""
        assert normalize("requests") != normalize("reqests")


class TestEnvironmentLayer:
    def test_installed_distribution_resolves(self, monkeypatch):
        monkeypatch.setattr(
            import_resolver, "_environment_distributions",
            lambda name: ["scikit-image"] if name == "skimage_x" else [],
        )
        resolver = offline_resolver(use_environment=True)

        result = resolver.resolve("skimage_x")

        assert result["distribution_name"] == "scikit-image"
        assert result["resolution_source"] == SOURCE_ENVIRONMENT
        assert result["resolution_status"] == VERIFIED

    def test_several_providers_are_ambiguous_not_a_guess(self, monkeypatch):
        monkeypatch.setattr(
            import_resolver, "_environment_distributions",
            lambda name: ["dist-a", "dist-b"],
        )

        result = offline_resolver(use_environment=True).resolve("shared")

        assert result["resolution_status"] == AMBIGUOUS
        assert result["candidates"] == ["dist-a", "dist-b"]
        assert result["distribution_name"] is None

    def test_environment_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(
            import_resolver, "_environment_distributions",
            lambda name: ["should-not-be-used"],
        )

        result = offline_resolver(use_environment=False).resolve("whatever")

        assert result["resolution_status"] == UNRESOLVED

    def test_broken_environment_metadata_does_not_crash_the_scan(self, monkeypatch):
        def explode():
            raise RuntimeError("corrupt dist-info")

        monkeypatch.setattr(
            import_resolver.metadata, "packages_distributions", explode
        )

        assert import_resolver._environment_distributions("anything") == []


class TestRegistryLayer:
    def test_a_name_that_exists_resolves_to_itself(self):
        result = offline_resolver(available={"httpx"}).resolve("httpx")

        assert result["distribution_name"] == "httpx"
        assert result["resolution_source"] == SOURCE_REGISTRY
        assert result["registry_checked"] is True

    def test_registry_identity_is_not_full_confidence(self):
        """A distribution sharing the import name is strong evidence, but not
        proof that it is what provides the module."""
        result = offline_resolver(available={"httpx"}).resolve("httpx")

        assert result["resolution_confidence"] < 1.0


class TestUnresolved:
    def test_absent_everywhere_is_unresolved_not_nonexistent(self):
        result = offline_resolver(available=set()).resolve("auto_retry_httpx")

        assert result["resolution_status"] == UNRESOLVED
        assert result["distribution_name"] is None
        assert result["registry_checked"] is True

    def test_offline_is_distinguishable_from_absent(self):
        """A probe returning None means "could not ask". Collapsing that into
        "not found" would turn every offline run into a pile of findings."""
        resolver = ImportNameResolver(
            exists_probe=lambda name: None, use_environment=False
        )

        result = resolver.resolve("anything")

        assert result["resolution_status"] == UNRESOLVED
        assert result["registry_checked"] is False

    def test_no_probe_at_all_is_still_safe(self):
        resolver = ImportNameResolver(exists_probe=None, use_environment=False)

        result = resolver.resolve("anything")

        assert result["resolution_status"] == UNRESOLVED
        assert result["registry_checked"] is False

    def test_a_near_miss_of_a_popular_name_is_never_resolved_to_it(self):
        """SECURITY: fuzzy similarity is evidence of a typosquat, never of
        identity. `reqests` must not quietly become `requests` -- that would
        launder the exact attack this project detects."""
        result = offline_resolver(available={"requests"}).resolve("reqests")

        assert result["resolution_status"] == UNRESOLVED
        assert result["distribution_name"] is None


class TestAmbiguity:
    def test_known_multi_provider_import(self):
        result = offline_resolver().resolve("slugify")

        assert result["resolution_status"] == AMBIGUOUS
        assert "python-slugify" in result["candidates"]
        assert "awesome-slugify" in result["candidates"]

    def test_ambiguous_never_yields_a_single_distribution(self):
        assert offline_resolver().resolve("slugify")["distribution_name"] is None

    def test_ambiguity_short_circuits_before_any_registry_call(self):
        resolver = offline_resolver(available={"slugify"})

        resolver.resolve("slugify")

        assert resolver.probe_calls == 0


class TestCaching:
    def test_repeated_resolution_probes_the_registry_once(self):
        resolver = offline_resolver(available={"httpx"})

        for _ in range(5):
            resolver.resolve("httpx")

        assert resolver.probe_calls == 1

    def test_duplicate_imports_resolve_once(self):
        resolver = offline_resolver(available=set())

        resolver.resolve_all(["ghost_pkg", "ghost_pkg", "ghost_pkg"])

        assert resolver.probe_calls == 1

    def test_cached_result_is_identical(self):
        resolver = offline_resolver(available={"httpx"})

        assert resolver.resolve("httpx") == resolver.resolve("httpx")

    def test_resolve_all_returns_one_entry_per_distinct_name(self):
        resolver = offline_resolver(available={"httpx"})

        results = resolver.resolve_all(["httpx", "httpx", "cv2"])

        assert set(results) == {"httpx", "cv2"}


class TestResultShape:
    def test_every_result_carries_the_documented_fields(self):
        result = offline_resolver().resolve("cv2")

        assert set(result) == {
            "import_name", "distribution_name", "resolution_status",
            "resolution_confidence", "resolution_source", "candidates",
            "registry_checked",
        }

    def test_import_name_is_always_preserved(self):
        for name in ["cv2", "slugify", "ghost_pkg"]:
            assert offline_resolver().resolve(name)["import_name"] == name
