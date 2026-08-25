import sys
from pathlib import Path

# The top-level modules (extractor, registry, prompts, ...) live at the repo
# root rather than in a package, so make sure the root is importable from the
# tests regardless of pytest's import mode.
sys.path.insert(0, str(Path(__file__).parent))
