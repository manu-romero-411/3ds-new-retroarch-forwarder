"""packaging/targets.py: parsing the distribution release lists."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# pylint: disable=missing-function-docstring

_SPEC = importlib.util.spec_from_file_location(
    "targets", Path(__file__).resolve().parent.parent / "packaging" / "targets.py"
)
assert _SPEC and _SPEC.loader
targets = importlib.util.module_from_spec(_SPEC)
sys.modules["targets"] = targets  # dataclasses look their module up
_SPEC.loader.exec_module(targets)

DEBIAN = """Origin: Debian
Label: Debian
Suite: stable
Version: 13.2
Codename: trixie
Date: Sat, 08 Nov 2026 10:00:00 UTC
Description: Debian 13.2 Released 08 November 2026
MD5Sum:
 0ed6d4c8891eb86358b94bb35d9e4da4  1484322 contrib/Contents-all
"""

UBUNTU = """Dist: focal
Name: Focal Fossa
Version: 20.04.6 LTS
Date: Thu, 23 April 2020 22:34:00 UTC
Supported: 0
Description: This is the 20.04 release

Dist: jammy
Name: Jammy Jellyfish
Version: 22.04.5 LTS
Supported: 1

Dist: noble
Name: Noble Numbat
Version: 24.04.3 LTS
Supported: 1

Dist: plucky
Name: Plucky Puffin
Version: 25.04
Supported: 0

Dist: questing
Name: Questing Quokka
Version: 25.10
Supported: 1

Dist: resolute
Name: Resolute Raccoon
Version: 26.04 LTS
Supported: 1
"""

BODHI = {
    "releases": [
        {"name": "F42", "version": "42", "id_prefix": "FEDORA", "state": "current"},
        {"name": "F43", "version": "43", "id_prefix": "FEDORA", "state": "current"},
        {"name": "F44", "version": "44", "id_prefix": "FEDORA", "state": "current"},
        {"name": "F44C", "version": "44", "id_prefix": "FEDORA-CONTAINER", "state": "current"},
        {"name": "F44F", "version": "44", "id_prefix": "FEDORA-FLATPAK", "state": "current"},
        {"name": "EPEL-10", "version": "10", "id_prefix": "FEDORA-EPEL", "state": "current"},
        {"name": "F45", "version": "45", "id_prefix": "FEDORA", "state": "pending"},
    ]
}


def test_debian_stable() -> None:
    distro = targets.parse_debian_release(DEBIAN)
    assert (distro.image, distro.suffix, distro.format) == ("debian:13", "debian13", "deb")


def test_ubuntu_two_newest_supported_lts() -> None:
    distros = targets.parse_ubuntu_meta_release(UBUNTU)
    assert [d.version for d in distros] == ["26.04", "24.04"]
    assert distros[1].image == "ubuntu:24.04"


def test_fedora_two_newest_current() -> None:
    distros = targets.parse_bodhi_releases(BODHI)
    assert [d.suffix for d in distros] == ["fc44", "fc43"]
    assert distros[0].format == "rpm"


def test_matrix_covers_both_architectures() -> None:
    def fake_fetch(url: str) -> str:
        if "debian" in url:
            return DEBIAN
        if "ubuntu" in url:
            return UBUNTU
        return json.dumps(BODHI)

    matrix = targets.expand(targets.discover(fake_fetch))
    assert len(matrix) == 10
    assert {t.runner for t in matrix if t.arch == "arm64"} == {"ubuntu-24.04-arm"}
    assert "ubuntu24.04-arm64" in {t.name for t in matrix}


def test_too_few_releases() -> None:
    with pytest.raises(ValueError):
        targets.parse_bodhi_releases({"releases": []})
