"""State shared by the library and every project tab.

One :class:`AppContext` lives as long as the main window: the settings,
the toolchain found with them, the console and core catalogs, the Title ID
registry and the project store. Widgets get it at construction and ask it,
never the disk, so a settings change reaches every open tab at once.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from forwarder3ds.artwork.banner_card import CardStyle, render_card_png
from forwarder3ds.artwork.bottom_screen import BottomScreenStyle
from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.injector import GameRequest, request_from_project
from forwarder3ds.builder.toolchain import Toolchain, find_toolchain
from forwarder3ds.core.core_options import CoreOptions, CoreOptionsError, load_core_options
from forwarder3ds.core.cores import DEFAULT_CORES_JSON, CoreCatalogError, CoreRegistry
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.names import save_folder_name
from forwarder3ds.core.projects import Asset, BannerStyle, Project, ProjectStore
from forwarder3ds.core.settings import Settings, load_settings
from forwarder3ds.core.systems import DEFAULT_SYSTEMS_JSON, SystemCatalog, SystemCatalogError
from forwarder3ds.core.title_id import (
    GAME_NAMESPACE,
    GAME_NAMESPACE_SIZE,
    TitleIdCollisionError,
    TitleIdRegistry,
    preview_unique_id,
)

_log = get_logger("gui")
#: Standalone emulators with a recipe (``emulators/``), known even before they are built.
STANDALONE_EMULATORS = frozenset({"snes9x_3ds"})


@dataclass
class AppContext:  # pylint: disable=too-many-instance-attributes
    """Settings, catalogs, toolchain, Title ID registry and projects."""

    settings: Settings = field(default_factory=load_settings)
    store: ProjectStore = field(default_factory=ProjectStore)
    tools: Toolchain | None = None
    systems: SystemCatalog | None = None
    cores: CoreRegistry | None = None
    registry: TitleIdRegistry | None = None
    _core_options: dict[str, CoreOptions | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Re-read everything that depends on the settings."""
        self.tools = find_toolchain(self.settings.toolchain)
        self._core_options.clear()
        try:
            self.systems = SystemCatalog.load(DEFAULT_SYSTEMS_JSON)
        except SystemCatalogError as exc:
            self.systems = None
            _log.error("%s", exc)
        try:
            self.cores = CoreRegistry.load(DEFAULT_CORES_JSON)
        except CoreCatalogError as exc:
            self.cores = None
            _log.error("%s", exc)
        self.reload_registry()

    def reload_registry(self) -> None:
        """Re-read the Title ID registry (after a build recorded an ID)."""
        path = self.settings.general.registry_path
        try:
            self.registry = TitleIdRegistry.load(path)
        except (OSError, ValueError) as exc:
            self.registry = None
            _log.error("Cannot read the Title ID registry %s: %s", path, exc)

    # ── Cores ────────────────────────────────────────────────────────────

    def available_cores(self) -> list[str]:
        """Cores with a built base."""
        return self.tools.available_cores() if self.tools else []

    def is_standalone(self, core: str) -> bool:
        """Whether ``core`` is a standalone emulator (RetroArch settings do not apply)."""
        if self.tools is None or core not in self.available_cores():
            return core in STANDALONE_EMULATORS
        try:
            return self.tools.base(core).standalone
        except BuildError:
            return False

    def core_options(self, core: str) -> CoreOptions | None:
        """The options of ``core``'s base, or ``None`` if it ships none."""
        if core not in self._core_options:
            options = None
            bases = self.tools.bases if self.tools else None
            header = bases / core / "core_options.h" if bases else None
            if header is not None and header.is_file():
                try:
                    options = load_core_options(header)
                except (OSError, CoreOptionsError) as exc:
                    _log.warning("Cannot read the %s core options: %s", core, exc)
            self._core_options[core] = options
        return self._core_options[core]

    def problem(self, project: Project) -> str | None:  # pylint: disable=too-many-return-statements
        """Why ``project`` cannot be built yet, or ``None``."""
        if not project.rom_path.is_file():
            return f"The ROM file is missing: {project.rom}"
        if not project.console:
            return "Choose the console."
        if project.core not in self.available_cores():
            return f"There is no RetroArch base for '{project.core}'. See Settings › Toolchain."
        if not project.long_name.strip():
            return "Enter the long name."
        if save_folder_name(project.folder) != project.folder:
            return "The save folder name has characters an SD card cannot hold."
        return self.preview_unique_id(project)[1]

    # ── Banner ───────────────────────────────────────────────────────────

    def card_style(self) -> CardStyle:
        """The default banner's colours and font, from the settings."""
        banner = self.settings.banner
        return CardStyle(banner.background, banner.text, banner.font)

    def render_card(self, project: Project) -> bytes:
        """``project``'s default banner (logo + console tag), as PNG data."""
        logo_path = project.asset(Asset.LOGO)
        try:
            logo = logo_path.read_bytes() if logo_path else None
        except OSError:
            logo = None
        return render_card_png(
            console=project.console,
            title=project.title,
            name=project.tag_name,
            year=project.tag_year,
            logo=logo,
            style=self.card_style(),
            icon=project.asset(Asset.TAG_ICON),
        )

    def refresh_card(self, project: Project) -> None:
        """Re-render ``project``'s banner if it uses the default one (settings may have changed)."""
        if project.banner_style is BannerStyle.CARD:
            self.store.set_asset(project, Asset.BANNER, self.render_card(project))

    # ── Title IDs ────────────────────────────────────────────────────────

    def request(self, project: Project, output: Path | None = None) -> GameRequest | None:
        """``project`` as a build request, or ``None`` while it is incomplete."""
        if not (project.rom and project.console and project.core):
            return None
        try:
            request = request_from_project(project, output or Path(), self.systems)
        except BuildError:
            return None
        request.bottom_screen = self.bottom_screen_style()
        return request

    def bottom_screen_style(self) -> BottomScreenStyle | None:
        """The touch screen picture's language and font (``None``: turned off)."""
        touch = self.settings.bottom_screen
        return BottomScreenStyle(touch.language, touch.font) if touch.enabled else None

    def preview_unique_id(self, project: Project) -> tuple[int | None, str | None]:
        """``(unique_id, None)``, ``(None, error)``, or ``(None, None)`` if incomplete."""
        request = self.request(project)
        if request is None or self.registry is None or self.cores is None:
            return None, None
        try:
            unique_id = preview_unique_id(
                request.identity(),
                self.cores.all_unique_ids(),
                self.registry,
                request.manual_unique_id,
                request.replace_existing_id,
            )
        except TitleIdCollisionError as exc:
            return None, str(exc)
        return unique_id, None

    def random_unique_id(self) -> int:
        """A game Unique ID no other title uses."""
        taken = set(self.registry.assigned_ids()) if self.registry else set()
        if self.cores is not None:
            taken |= set(self.cores.all_unique_ids())
        while True:
            candidate = GAME_NAMESPACE + random.randrange(GAME_NAMESPACE_SIZE)
            if candidate not in taken:
                return candidate
