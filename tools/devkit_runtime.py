"""Run devkitARM toolchain commands inside the project's Docker image.

``bannertool``, ``makerom`` and the devkitARM ``make`` rules only exist
inside the image built from this project's ``Dockerfile`` (tag
``DOCKER_IMAGE`` below) -- they are never expected on the host PATH. Every
call to one of those tools must go through :func:`run_devkit` instead of
``subprocess`` directly.

Two constraints fall out of running things in a container:

* Only paths under ``PROJECT_ROOT`` are visible inside the container (it is
  bind-mounted at ``/work``); anything under the host's system ``/tmp`` is
  not. Use :func:`devkit_tmp_dir` for scratch space instead of
  ``tempfile.TemporaryDirectory()`` directly, and :func:`to_container_path`
  to translate any absolute host path you hand to a container command.
* Without ``-u``, Docker runs the container's default user, which is root
  for ``devkitpro/devkitarm``-based images. Files created inside the
  container (CIAs, stub build artifacts, RomFS trees) would then end up
  owned by root on the host. :func:`run_devkit` always passes ``-u
  <uid>:<gid>`` for the current host user to avoid this.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTAINER_WORKDIR = "/work"
DOCKER_IMAGE = "3ds-forwarder-dev"

# All per-build scratch space must live under here, not the system temp
# directory, so it is visible inside the container through the project's
# own bind mount. Never committed (see .gitignore).
DEVKIT_TMP_ROOT = PROJECT_ROOT / ".devkit-tmp"


def devkit_tmp_dir() -> tempfile.TemporaryDirectory:
    """Return a ``TemporaryDirectory`` rooted under the project.

    Use this instead of a bare ``tempfile.TemporaryDirectory()`` for any
    scratch space whose contents a container command will read or write.
    """
    DEVKIT_TMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=DEVKIT_TMP_ROOT)


def to_container_path(host_path: Path) -> str:
    """Translate an absolute host path under PROJECT_ROOT to its container path.

    Raises ``ValueError`` if ``host_path`` is not under PROJECT_ROOT, since
    such a path would not exist inside the container's bind mount.
    """
    resolved = host_path.resolve()
    try:
        relative = resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"'{resolved}' is outside the project root ({PROJECT_ROOT}) and "
            "would not exist inside the devkit container. Copy it under "
            "the project first (see devkit_tmp_dir())."
        ) from exc
    return f"{CONTAINER_WORKDIR}/{relative.as_posix()}"


def ensure_devkit_image_exists() -> None:
    """Exit with a clear message if DOCKER_IMAGE was never built."""
    result = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: Docker image '{DOCKER_IMAGE}' not found. Build it "
            f"first with:\n    docker build -t {DOCKER_IMAGE} .",
            file=sys.stderr,
        )
        sys.exit(1)


def run_devkit(
    cmd: list[str],
    cwd: Path = PROJECT_ROOT,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run ``cmd`` inside DOCKER_IMAGE, as the current host user.

    ``cmd`` and ``cwd`` must only reference paths under PROJECT_ROOT --
    translate any absolute path with :func:`to_container_path` first.
    Runs as the host UID/GID so files the container creates are owned by
    the calling user on the host, not root.
    """
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-u",
        f"{os.getuid()}:{os.getgid()}",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{PROJECT_ROOT}:{CONTAINER_WORKDIR}",
        "-w",
        to_container_path(cwd),
        DOCKER_IMAGE,
        *cmd,
    ]
    return subprocess.run(docker_cmd, capture_output=capture_output, text=True, check=False)
