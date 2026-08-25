"""
Tests for manifest parsing.

Several of these are regression tests for false positives that were found on
real repositories during the prevalence study -- each one is marked
REGRESSION and would fail if the corresponding fix were reverted.
"""

from scanner.manifest_parser import (
    parse_package_json,
    parse_package_json_own_name,
    parse_pyproject_own_name,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_setup_py,
)


class TestRequirementsTxt:
    def test_strips_version_specifiers(self):
        content = "requests==2.31.0\nflask>=2.0,<3.0\nurllib3~=1.26\n"
        assert parse_requirements_txt(content) == ["requests", "flask", "urllib3"]

    def test_skips_comments_and_blank_lines(self):
        content = "# a comment\n\nrequests\n\n# another\n"
        assert parse_requirements_txt(content) == ["requests"]

    def test_skips_non_registry_sources(self):
        content = (
            "-e .\n"
            "-r other-requirements.txt\n"
            "--index-url https://example.com/simple\n"
            "git+https://github.com/foo/bar.git\n"
            "https://example.com/pkg.tar.gz\n"
            "requests\n"
        )
        assert parse_requirements_txt(content) == ["requests"]

    def test_drops_environment_markers_and_extras(self):
        content = 'numpy[extra]~=1.24; python_version >= "3.8"\n'
        assert parse_requirements_txt(content) == ["numpy"]


class TestPyprojectToml:
    def test_pep621_dependencies(self):
        content = """
[project]
name = "demo"
dependencies = ["requests>=2.0", "click"]
"""
        assert parse_pyproject_toml(content) == ["requests", "click"]

    def test_pep621_optional_dependencies(self):
        content = """
[project]
name = "demo"
dependencies = ["requests"]
[project.optional-dependencies]
dev = ["pytest", "ruff"]
"""
        assert set(parse_pyproject_toml(content)) == {"requests", "pytest", "ruff"}

    def test_poetry_dependencies_exclude_python_itself(self):
        content = """
[tool.poetry]
name = "demo"
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.0"
"""
        assert parse_pyproject_toml(content) == ["requests"]

    def test_poetry_group_dependencies(self):
        content = """
[tool.poetry]
name = "demo"
[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""
        assert parse_pyproject_toml(content) == ["pytest"]

    def test_malformed_toml_returns_empty_rather_than_raising(self):
        assert parse_pyproject_toml("this is not [valid toml") == []

    def test_regression_poetry_path_deps_are_not_registry_deps(self):
        """REGRESSION: a Poetry dependency sourced from a local path is a
        sibling package in the same monorepo, not something PyPI would ever
        resolve by that name. Flagging it as phantom was a false positive
        found on rodaddy/open-brain (openbrain-memory)."""
        content = """
[tool.poetry]
name = "openbrain-provider"
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.0"
openbrain-memory = {path = "../openbrain-memory", develop = true}
"""
        assert parse_pyproject_toml(content) == ["requests"]

    def test_regression_poetry_git_and_url_deps_are_excluded(self):
        content = """
[tool.poetry]
name = "demo"
[tool.poetry.dependencies]
from-git = {git = "https://github.com/foo/bar.git"}
from-url = {url = "https://example.com/pkg.tar.gz"}
requests = "^2.0"
"""
        assert parse_pyproject_toml(content) == ["requests"]

    def test_regression_pep508_direct_reference_is_excluded(self):
        content = """
[project]
name = "demo"
dependencies = ["sibling @ file:///../sibling", "requests"]
"""
        assert parse_pyproject_toml(content) == ["requests"]


class TestSetupPy:
    def test_extracts_install_requires(self):
        content = 'setup(name="demo", install_requires=["boto3", "pandas>=1.0"])'
        assert parse_setup_py(content) == ["boto3", "pandas"]

    def test_no_install_requires_returns_empty(self):
        assert parse_setup_py('setup(name="demo")') == []


class TestPackageJson:
    def test_reads_dependencies_and_dev_dependencies(self):
        content = """
        {"dependencies": {"express": "^4.0"},
         "devDependencies": {"jest": "^29.0"}}
        """
        assert set(parse_package_json(content)) == {"express", "jest"}

    def test_malformed_json_returns_empty_rather_than_raising(self):
        assert parse_package_json("{not valid json") == []

    def test_regression_workspace_and_local_protocols_are_excluded(self):
        """REGRESSION: workspace:/file:/link:/relative-path dependencies are
        resolved locally by the workspace tooling and never fetched from the
        public npm registry, so checking them there produced false positives
        on several real monorepos."""
        content = """
        {"dependencies": {
            "@myorg/core": "workspace:*",
            "local-lib": "file:../local-lib",
            "linked": "link:../linked",
            "relative": "./vendor/thing",
            "express": "^4.0"
        }}
        """
        assert parse_package_json(content) == ["express"]

    def test_non_string_version_is_ignored(self):
        content = '{"dependencies": {"weird": {"nested": true}, "express": "^4.0"}}'
        assert parse_package_json(content) == ["express"]


class TestOwnNameParsers:
    def test_package_json_own_name(self):
        assert parse_package_json_own_name('{"name": "@myorg/web"}') == "@myorg/web"

    def test_package_json_own_name_missing(self):
        assert parse_package_json_own_name('{"dependencies": {}}') is None

    def test_pyproject_own_name_pep621(self):
        assert parse_pyproject_own_name('[project]\nname = "demo"') == "demo"

    def test_pyproject_own_name_poetry(self):
        assert parse_pyproject_own_name('[tool.poetry]\nname = "demo"') == "demo"
