import ast
import re
import sys

_STDLIB = set(sys.stdlib_module_names) | {"__future__"}

# Common local/generic names an LLM might import from a file it also wrote
# in the same snippet (e.g. "from config import settings"). These aren't
# hallucinated third-party packages, just self-referential scaffolding.
_LIKELY_LOCAL = {"config", "settings", "utils", "helpers", "app", "main"}

_CODE_BLOCK_RE = re.compile(r"```(?:python|py|javascript|js|ts)?\n(.*?)```", re.S)


def extract_code_blocks(response_text: str) -> list[str]:
    blocks = _CODE_BLOCK_RE.findall(response_text)
    return blocks if blocks else [response_text]


def extract_python_packages(code: str) -> set[str]:
    packages: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return packages

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                packages.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or node.module is None:
                continue  # relative import, not a third-party package
            packages.add(node.module.split(".")[0])

    return {
        p for p in packages
        if p not in _STDLIB and p not in _LIKELY_LOCAL and not p.startswith("_")
    }


_JS_REQUIRE_RE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")
_JS_IMPORT_RE = re.compile(r"import\s+(?:[\w*{}\s,]+\s+from\s+)?['\"]([^'\"]+)['\"]")

_NODE_BUILTINS = {
    "fs", "path", "http", "https", "url", "crypto", "os", "util", "events",
    "stream", "buffer", "child_process", "net", "dns", "readline", "zlib",
    "assert", "querystring", "tls", "cluster", "timers", "worker_threads",
}


def extract_js_packages(code: str) -> set[str]:
    specifiers = set(_JS_REQUIRE_RE.findall(code)) | set(_JS_IMPORT_RE.findall(code))
    packages = set()
    for spec in specifiers:
        if spec.startswith(".") or spec.startswith("node:"):
            continue  # relative import or explicit node builtin
        # scoped package (@org/name) -> keep as-is; otherwise take first segment
        if spec.startswith("@"):
            parts = spec.split("/")
            name = "/".join(parts[:2]) if len(parts) >= 2 else spec
        else:
            name = spec.split("/")[0]
        if name not in _NODE_BUILTINS:
            packages.add(name)
    return packages


def extract_packages(code: str, language: str) -> set[str]:
    if language == "python":
        return extract_python_packages(code)
    if language == "javascript":
        return extract_js_packages(code)
    raise ValueError(f"unsupported language: {language}")
