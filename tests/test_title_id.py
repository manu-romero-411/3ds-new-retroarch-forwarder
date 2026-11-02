"""Deterministic, collision-checked Title IDs."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from pathlib import Path

import pytest

from forwarder3ds.core.title_id import (
    FORWARDER_NAMESPACE,
    ForwarderIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    generate_title_id,
    preview_unique_id,
    title_id_to_unique_id,
    unique_id_to_title_id,
)

SAMPLE = ForwarderIdentity(
    name="Super Mario World",
    short_name="SMW",
    long_name="Super Mario World (SNES)",
    manufacturer="Nintendo",
    core="snes9x",
    rom_path="roms/snes/Super Mario World.sfc",
)
OTHER = ForwarderIdentity("Other", "OG", "Other Game", "Someone", "snes9x", "roms/snes/o.sfc")


def test_same_inputs_same_id(tmp_path: Path) -> None:
    registry = TitleIdRegistry(path=tmp_path / "registry.json")
    first = generate_title_id(SAMPLE, set(), registry)
    second = generate_title_id(SAMPLE, set(), registry)
    assert first == second
    assert first[0] & 0xF0000 == FORWARDER_NAMESPACE
    assert registry.preview(SAMPLE, set()) == first[0]
    assert TitleIdRegistry.load(registry.path).assigned_ids() == {first[0]}


def test_title_id_round_trip() -> None:
    assert title_id_to_unique_id(unique_id_to_title_id(0xF1234)) == 0xF1234
    assert unique_id_to_title_id(0xF1234) == 0x000400000F123400


def test_manual_id_taken_by_other_forwarder(tmp_path: Path) -> None:
    registry = TitleIdRegistry(path=tmp_path / "r.json")
    unique_id, _ = generate_title_id(SAMPLE, set(), registry)
    with pytest.raises(TitleIdCollisionError):
        registry.resolve_manual(OTHER, unique_id, set())


def test_replacing_keeps_the_id(tmp_path: Path) -> None:
    registry = TitleIdRegistry(path=tmp_path / "r.json")
    unique_id, _ = generate_title_id(SAMPLE, set(), registry)
    edited = ForwarderIdentity(**{**SAMPLE.__dict__, "short_name": "SMW2"})
    with pytest.raises(TitleIdCollisionError):
        preview_unique_id(edited, set(), registry, unique_id)
    kept, _ = generate_title_id(
        edited, set(), registry, manual_unique_id=unique_id, replace_existing=True
    )
    assert kept == unique_id
    assert len(registry.entries) == 1


def test_core_ids_stay_reserved(tmp_path: Path) -> None:
    registry = TitleIdRegistry(path=tmp_path / "r.json")
    with pytest.raises(TitleIdCollisionError):
        registry.validate_manual(SAMPLE, 0xBAC01, {0xBAC01}, replace_existing=True)


def test_collision_moves_to_a_free_id(tmp_path: Path) -> None:
    registry = TitleIdRegistry(path=tmp_path / "r.json")
    natural = registry.preview(SAMPLE, set())
    assert registry.preview(SAMPLE, {natural}) != natural


def test_malformed_registry(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError):
        TitleIdRegistry.load(path)
