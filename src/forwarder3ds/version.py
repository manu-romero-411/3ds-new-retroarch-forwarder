"""The program's version, taken from the git tag (``v1.2.3`` gives ``1.2.3``).

Nobody writes it by hand. In order of preference it comes from:

1. ``forwarder3ds/_version.py``, generated at build time: by setuptools-scm
   for ``pip install`` (also from a GitHub source archive, through
   ``.git_archival.txt``) and by ``packaging/common.sh`` for the .deb/.rpm;
2. ``git describe`` when running straight from a checkout;
3. ``0.0.0+unknown`` otherwise.
"""

from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path

UNKNOWN_VERSION = "0.0.0+unknown"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DESCRIBE = re.compile(r"^v?(?P<base>\d+(?:\.\d+)*)(?:-(?P<ahead>\d+)-g(?P<sha>[0-9a-f]+))?$")


def version_from_describe(described: str) -> str | None:
    """``v1.2.3`` → ``1.2.3``; ``v1.2.3-4-gabc123`` → ``1.2.3+git4.gabc123``."""
    match = _DESCRIBE.match(described.strip())
    if match is None:
        return None
    if match["ahead"] is None or match["ahead"] == "0":
        return match["base"]
    return f"{match['base']}+git{match['ahead']}.g{match['sha']}"


def _from_generated_file() -> str | None:
    try:
        module = importlib.import_module("forwarder3ds._version")
    except ImportError:
        return None
    value = getattr(module, "__version__", None)
    return value if isinstance(value, str) and value else None


def _from_git() -> str | None:
    if not (_REPO_ROOT / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "describe", "--tags", "--match", "v[0-9]*"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return version_from_describe(result.stdout) if result.returncode == 0 else None


def detect_version() -> str:
    """The version of this copy of the program (see the module docstring)."""
    return _from_generated_file() or _from_git() or UNKNOWN_VERSION
