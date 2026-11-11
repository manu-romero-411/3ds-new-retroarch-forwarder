"""Projects: one saved game setup each, like NSUI's project library.

A project remembers everything that goes into one game CIA except the ROM
itself, which stays where the user keeps it (the project stores its path).
Each project is a folder under :func:`projects_dir`::

    <id>/project.json      names, console, core, Title ID, injection options
    <id>/icon.png          optional artwork, copied in when chosen
    <id>/banner.png
    <id>/audio.<ext>
    <id>/bezel.png

:class:`ProjectStore` lists, saves, deletes, exports (``.zip``) and imports
them; :meth:`Project.request` turns one into a
:class:`~forwarder3ds.builder.injector.GameRequest`.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from forwarder3ds.core import paths
from forwarder3ds.core.game_config import ScreenSettings, normalize_remap
from forwarder3ds.core.logs import get_logger

_log = get_logger("projects")

PROJECT_FILE = "project.json"
PROJECT_EXTENSION = ".3dsproj.zip"
_FORMAT = 1


class Asset(str, Enum):
    """Files a project can carry, by their stem in the project folder."""

    ICON = "icon"
    BANNER = "banner"
    AUDIO = "audio"
    BEZEL = "bezel"


class BannerStyle(str, Enum):
    """Where the banner image comes from."""

    #: SteamGridDB hero with the game's logo over it.
    STEAMGRIDDB = "steamgriddb"
    #: The title screen from libretro's thumbnails.
    TITLE_SCREEN = "title"
    #: A gameplay screenshot from libretro's thumbnails.
    SNAPSHOT = "snapshot"
    #: An image file chosen by the user.
    FILE = "file"


def projects_dir() -> Path:
    """Where projects are kept."""
    return paths.data_dir() / "projects"


@dataclass
class Project:  # pylint: disable=too-many-instance-attributes
    """One game: what the editor shows and the builder needs."""

    id: str
    rom: str
    console: str
    core: str = ""
    folder: str = ""
    long_name: str = ""
    short_name: str = ""
    publisher: str = ""
    #: The game as the libretro database names it (empty: not matched).
    db_name: str = ""
    developer: str = ""
    year: str = ""
    #: Fixed Unique ID; ``None`` lets the builder derive one.
    unique_id: int | None = None
    #: The Unique ID of the last CIA built from this project: rebuilding
    #: under it replaces that CIA even after the names changed.
    built_id: int | None = None
    hide_from_activity_log: bool = False
    banner_style: BannerStyle = BannerStyle.STEAMGRIDDB
    screen: ScreenSettings = field(default_factory=ScreenSettings)
    core_options: dict[str, str] = field(default_factory=dict)
    remap: dict[str, str] = field(default_factory=dict)
    #: The last CIA built from this project.
    output: str = ""
    modified: float = 0.0
    #: The folder the project lives in (not saved).
    directory: Path | None = field(default=None, compare=False, repr=False)

    @property
    def rom_path(self) -> Path:
        """The ROM, where the user keeps it."""
        return Path(self.rom)

    @property
    def title(self) -> str:
        """What the library lists the project as."""
        return self.long_name or self.rom_path.stem

    def asset(self, kind: Asset) -> Path | None:
        """The project's copy of ``kind``, if it has one."""
        if self.directory is None:
            return None
        return next(iter(sorted(self.directory.glob(f"{kind.value}.*"))), None)

    def to_json(self) -> dict[str, object]:
        """The contents of ``project.json``."""
        return {
            "format": _FORMAT,
            "id": self.id,
            "rom": self.rom,
            "console": self.console,
            "core": self.core,
            "folder": self.folder,
            "long_name": self.long_name,
            "short_name": self.short_name,
            "publisher": self.publisher,
            "db_name": self.db_name,
            "developer": self.developer,
            "year": self.year,
            "unique_id": self.unique_id,
            "built_id": self.built_id,
            "hide_from_activity_log": self.hide_from_activity_log,
            "banner_style": self.banner_style.value,
            "screen": self.screen.to_json(),
            "core_options": dict(self.core_options),
            "remap": dict(self.remap),
            "output": self.output,
            "modified": self.modified,
        }

    @classmethod
    def from_json(cls, data: dict[str, object], directory: Path | None = None) -> Project:
        """Read :meth:`to_json` output; raises ``ValueError`` if it is not a project."""
        if not isinstance(data, dict) or not data.get("id") or not data.get("rom"):
            raise ValueError("not a project file")

        def text(key: str) -> str:
            value = data.get(key, "")
            return value if isinstance(value, str) else ""

        def strings(key: str) -> dict[str, str]:
            value = data.get(key)
            if not isinstance(value, dict):
                return {}
            return {str(k): str(v) for k, v in value.items()}

        unique_id = data.get("unique_id")
        built_id = data.get("built_id")
        try:
            banner_style = BannerStyle(data.get("banner_style", BannerStyle.STEAMGRIDDB.value))
        except ValueError:
            banner_style = BannerStyle.STEAMGRIDDB
        modified = data.get("modified", 0.0)
        return cls(
            id=text("id"),
            rom=text("rom"),
            console=text("console"),
            core=text("core"),
            folder=text("folder"),
            long_name=text("long_name"),
            short_name=text("short_name"),
            publisher=text("publisher"),
            db_name=text("db_name"),
            developer=text("developer"),
            year=text("year"),
            unique_id=unique_id if isinstance(unique_id, int) else None,
            built_id=built_id if isinstance(built_id, int) else None,
            hide_from_activity_log=bool(data.get("hide_from_activity_log", False)),
            banner_style=banner_style,
            screen=ScreenSettings.from_json(data.get("screen")),
            core_options=strings("core_options"),
            remap=normalize_remap(strings("remap")),
            output=text("output"),
            modified=float(modified) if isinstance(modified, (int, float)) else 0.0,
            directory=directory,
        )


class ProjectStore:
    """The project library on disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or projects_dir()

    def list(self) -> list[Project]:
        """Every readable project, by title; unreadable ones are skipped with a warning."""
        found = []
        if not self.root.is_dir():
            return found
        for directory in sorted(self.root.iterdir()):
            if (directory / PROJECT_FILE).is_file():
                try:
                    found.append(self._read(directory))
                except (OSError, ValueError) as exc:
                    _log.warning("Skipping project %s: %s", directory.name, exc)
        return sorted(found, key=lambda project: project.title.casefold())

    def get(self, project_id: str) -> Project:
        """The project ``project_id``; raises ``OSError``/``ValueError`` if unreadable."""
        return self._read(self.root / project_id)

    @staticmethod
    def _read(directory: Path) -> Project:
        data = json.loads((directory / PROJECT_FILE).read_text(encoding="utf-8"))
        project = Project.from_json(data, directory)
        project.id = directory.name
        return project

    def create(self, rom: Path, console: str, **fields: object) -> Project:
        """A new, saved project for ``rom``."""
        project = Project(id=uuid.uuid4().hex[:12], rom=str(rom), console=console)
        for key, value in fields.items():
            setattr(project, key, value)
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        """Write ``project`` (its folder is created if needed)."""
        directory = self.root / project.id
        directory.mkdir(parents=True, exist_ok=True)
        project.directory = directory
        project.modified = time.time()
        data = json.dumps(project.to_json(), indent=2, ensure_ascii=False)
        temporary = directory / (PROJECT_FILE + ".tmp")
        temporary.write_text(data + "\n", encoding="utf-8")
        temporary.replace(directory / PROJECT_FILE)

    def delete(self, project: Project) -> None:
        """Remove ``project`` and its artwork (never the ROM)."""
        shutil.rmtree(self.root / project.id, ignore_errors=True)

    def set_asset(self, project: Project, kind: Asset, source: Path | bytes | None) -> Path | None:
        """Copy ``source`` into the project as ``kind`` (``None`` removes it).

        ``bytes`` are taken as PNG data. Returns the project's copy.
        """
        directory = self.root / project.id
        directory.mkdir(parents=True, exist_ok=True)
        project.directory = directory
        for old in directory.glob(f"{kind.value}.*"):
            old.unlink()
        if source is None:
            return None
        if isinstance(source, bytes):
            target = directory / f"{kind.value}.png"
            target.write_bytes(source)
        else:
            target = directory / f"{kind.value}{source.suffix.lower()}"
            shutil.copyfile(source, target)
        return target

    def export(self, projects: list[Project], destination: Path) -> None:
        """Write ``projects`` (settings and artwork, not ROMs) to one ``.zip``."""
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for project in projects:
                directory = self.root / project.id
                for item in sorted(directory.iterdir()):
                    if item.is_file() and not item.name.endswith(".tmp"):
                        archive.write(item, f"{project.id}/{item.name}")

    def import_archive(self, source: Path) -> list[Project]:
        """Add the projects of an :meth:`export` file; IDs already present get new ones."""
        imported: list[Project] = []
        with zipfile.ZipFile(source) as archive:
            groups: dict[str, list[zipfile.ZipInfo]] = {}
            for info in archive.infolist():
                parts = PurePosixPath(info.filename).parts
                if len(parts) == 2 and not info.is_dir() and parts[1] != "..":
                    groups.setdefault(parts[0], []).append(info)
            for members in groups.values():
                if not any(PurePosixPath(m.filename).name == PROJECT_FILE for m in members):
                    continue
                project_id = uuid.uuid4().hex[:12]
                directory = self.root / project_id
                directory.mkdir(parents=True)
                for member in members:
                    name = PurePosixPath(member.filename).name
                    (directory / name).write_bytes(archive.read(member))
                try:
                    imported.append(self._read(directory))
                except (OSError, ValueError):
                    shutil.rmtree(directory, ignore_errors=True)
                    continue
                self.save(imported[-1])
        return imported
