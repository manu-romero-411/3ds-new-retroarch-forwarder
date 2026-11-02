"""The version comes from the git tag, never from a file edited by hand."""

from __future__ import annotations

import pytest

import forwarder3ds
from forwarder3ds.version import version_from_describe

# pylint: disable=missing-function-docstring


@pytest.mark.parametrize(
    ("described", "version"),
    [
        ("v0.2.3", "0.2.3"),
        ("v0.2.3\n", "0.2.3"),
        ("v1.0-0-gabc1234", "1.0"),
        ("v0.2.3-4-g1152c70", "0.2.3+git4.g1152c70"),
        ("not-a-version", None),
    ],
)
def test_version_from_describe(described: str, version: str | None) -> None:
    assert version_from_describe(described) == version


def test_package_has_a_version() -> None:
    assert isinstance(forwarder3ds.__version__, str) and forwarder3ds.__version__
