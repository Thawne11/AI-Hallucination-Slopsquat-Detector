"""
Tests for import extraction from generated code.
"""

import pytest

from extractor import (
    extract_code_blocks,
    extract_js_packages,
    extract_packages,
    extract_python_packages,
)


class TestCodeBlockExtraction:
    def test_extracts_fenced_block(self):
        text = "Here you go:\n```python\nimport requests\n```\nHope that helps."
        assert extract_code_blocks(text) == ["import requests\n"]

    def test_extracts_multiple_blocks(self):
        text = "```python\nimport a\n```\ntext\n```js\nrequire('b')\n```"
        assert len(extract_code_blocks(text)) == 2

    def test_falls_back_to_whole_text_when_unfenced(self):
        text = "import requests"
        assert extract_code_blocks(text) == [text]


class TestPythonExtraction:
    def test_finds_third_party_imports(self):
        code = "import requests\nfrom flask import Flask\n"
        assert extract_python_packages(code) == {"requests", "flask"}

    def test_reduces_dotted_import_to_top_level(self):
        code = "import os.path\nimport boto3.session\n"
        assert extract_python_packages(code) == {"boto3"}

    def test_excludes_stdlib(self):
        code = "import os\nimport sys\nimport json\nimport requests\n"
        assert extract_python_packages(code) == {"requests"}

    def test_excludes_relative_imports(self):
        code = "from . import sibling\nfrom .models import Thing\nimport requests\n"
        assert extract_python_packages(code) == {"requests"}

    def test_excludes_likely_local_scaffolding(self):
        code = "from config import settings\nimport utils\nimport requests\n"
        assert extract_python_packages(code) == {"requests"}

    def test_syntax_error_returns_empty_rather_than_raising(self):
        assert extract_python_packages("this is not (valid python") == set()

    def test_regression_grpc_stub_modules_are_not_registry_packages(self):
        """REGRESSION: protoc generates `<service>_pb2` / `<service>_pb2_grpc`
        modules locally from a project's own .proto file. They are never
        published to PyPI under those names, so checking them against a
        public registry is a category error -- it inflated the raw PHR in the
        multi-model pilot before this filter existed."""
        code = (
            "import grpc\n"
            "import myservice_pb2\n"
            "import myservice_pb2_grpc\n"
        )
        assert extract_python_packages(code) == {"grpc"}


class TestJavaScriptExtraction:
    def test_finds_require_and_import(self):
        code = "const ws = require('ws');\nimport axios from 'axios';\n"
        assert extract_js_packages(code) == {"ws", "axios"}

    def test_keeps_scoped_package_name_intact(self):
        code = "const grpc = require('@grpc/grpc-js');"
        assert extract_js_packages(code) == {"@grpc/grpc-js"}

    def test_reduces_subpath_import_to_package_name(self):
        code = "const x = require('lodash/debounce');"
        assert extract_js_packages(code) == {"lodash"}

    def test_excludes_node_builtins(self):
        code = "const fs = require('fs');\nconst path = require('path');\nconst ws = require('ws');"
        assert extract_js_packages(code) == {"ws"}

    def test_excludes_node_prefixed_builtins(self):
        code = "const fs = require('node:fs/promises');\nconst ws = require('ws');"
        assert extract_js_packages(code) == {"ws"}

    def test_excludes_relative_imports(self):
        code = "const local = require('./helpers');\nimport x from '../lib/x';\nconst ws = require('ws');"
        assert extract_js_packages(code) == {"ws"}


class TestDispatch:
    def test_routes_by_language(self):
        assert extract_packages("import requests", "python") == {"requests"}
        assert extract_packages("require('ws')", "javascript") == {"ws"}

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError):
            extract_packages("puts 'hi'", "ruby")
