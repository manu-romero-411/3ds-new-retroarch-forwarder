#!/usr/bin/env python3
"""Work out which distributions the release packages are built for.

Run by the release workflow on every tag, so new releases of the
distributions are picked up without editing anything:

* Debian: the current *stable* release;
* Ubuntu: the two newest LTS releases that are still supported;
* Fedora: the two newest stable releases;

each for ``amd64`` and ``arm64``. Prints a table and, under GitHub Actions,
writes the build matrix (JSON) to ``$GITHUB_OUTPUT`` as ``matrix``.

    python3 packaging/targets.py [--json]

Sources: Debian's ``dists/stable/Release``, Ubuntu's ``meta-release`` and
Fedora's Bodhi API. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass

DEBIAN_RELEASE_URL = "https://deb.debian.org/debian/dists/stable/Release"
UBUNTU_META_URL = "https://changelogs.ubuntu.com/meta-release"
FEDORA_RELEASES_URL = "https://bodhi.fedoraproject.org/releases/?state=current&rows_per_page=100"
UBUNTU_LTS_COUNT = 2
FEDORA_COUNT = 2
#: (Debian architecture, GitHub runner) pairs; the runner's own architecture builds.
ARCHITECTURES = (("amd64", "ubuntu-24.04"), ("arm64", "ubuntu-24.04-arm"))
_RETRIES = 3
_TIMEOUT = 30


@dataclass(frozen=True)
class Distro:
    """One distribution release."""

    family: str  # debian, ubuntu, fedora
    version: str  # 13, 24.04, 43
    image: str  # container image to build and test in
    suffix: str  # tag in the package version / file name
    format: str  # deb or rpm


@dataclass(frozen=True)
class Target:
    """One package to build: a distribution release on one architecture."""

    family: str
    version: str
    image: str
    suffix: str
    format: str
    arch: str
    runner: str
    name: str


def parse_debian_release(text: str) -> Distro:
    """The stable release from a Debian ``Release`` file."""
    fields = dict(
        line.split(":", 1) for line in text.splitlines() if ":" in line and not line[0].isspace()
    )
    version = fields.get("Version", "").strip()
    major = version.split(".")[0]
    if not major.isdigit():
        raise ValueError(f"No stable version in the Debian Release file (got {version!r})")
    return Distro("debian", major, f"debian:{major}", f"debian{major}", "deb")


def parse_ubuntu_meta_release(text: str, count: int = UBUNTU_LTS_COUNT) -> list[Distro]:
    """The ``count`` newest supported LTS releases from Ubuntu's ``meta-release``."""
    versions: set[str] = set()
    for block in re.split(r"\n\s*\n", text.strip()):
        fields = dict(
            (key.strip(), value.strip())
            for key, _sep, value in (line.partition(":") for line in block.splitlines())
        )
        match = re.match(r"(\d+\.\d+)(?:\.\d+)?\s+LTS$", fields.get("Version", ""))
        if match and fields.get("Supported") == "1":
            versions.add(match.group(1))
    newest = sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")), reverse=True)
    if len(newest) < count:
        raise ValueError(f"Found {len(newest)} supported Ubuntu LTS releases, expected {count}")
    return [Distro("ubuntu", v, f"ubuntu:{v}", f"ubuntu{v}", "deb") for v in newest[:count]]


def parse_bodhi_releases(payload: dict, count: int = FEDORA_COUNT) -> list[Distro]:
    """The ``count`` newest stable Fedora releases from Bodhi's ``/releases/``."""
    versions = {
        int(release["version"])
        for release in payload.get("releases", [])
        if release.get("id_prefix") == "FEDORA"
        and re.fullmatch(r"F\d+", release.get("name", ""))
        and release.get("state") == "current"
        and str(release.get("version", "")).isdigit()
    }
    newest = sorted(versions, reverse=True)
    if len(newest) < count:
        raise ValueError(f"Found {len(newest)} current Fedora releases, expected {count}")
    return [Distro("fedora", str(v), f"fedora:{v}", f"fc{v}", "rpm") for v in newest[:count]]


def expand(distros: list[Distro]) -> list[Target]:
    """Every distribution on every architecture."""
    return [
        Target(**asdict(distro), arch=arch, runner=runner, name=f"{distro.suffix}-{arch}")
        for distro in distros
        for arch, runner in ARCHITECTURES
    ]


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "3ds-forwarder-release"})
    for attempt in range(1, _RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                return response.read().decode("utf-8", errors="replace")
        except OSError as exc:
            if attempt == _RETRIES:
                raise RuntimeError(f"Cannot fetch {url}: {exc}") from exc
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def discover(fetch: Callable[[str], str] = _fetch) -> list[Distro]:
    """Query the three sources."""
    distros = [parse_debian_release(fetch(DEBIAN_RELEASE_URL))]
    distros += parse_ubuntu_meta_release(fetch(UBUNTU_META_URL))
    distros += parse_bodhi_releases(json.loads(fetch(FEDORA_RELEASES_URL)))
    return distros


def main(argv: list[str] | None = None) -> int:
    """Print the targets and export the matrix for GitHub Actions."""
    parser = argparse.ArgumentParser(description="List the release package targets.")
    parser.add_argument("--json", action="store_true", help="print the matrix as JSON only")
    args = parser.parse_args(argv)
    try:
        targets = expand(discover())
    except (RuntimeError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    matrix = json.dumps({"include": [asdict(target) for target in targets]})
    if args.json:
        print(matrix)
    else:
        for target in targets:
            print(f"{target.name:<22} {target.format}  {target.image:<14} on {target.runner}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"matrix={matrix}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
