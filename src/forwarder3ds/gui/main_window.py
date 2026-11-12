"""Main window: the project library plus one tab per open project.

Layout::

    ┌ toolbar: New project · Import… · Generate CIA · Settings ─────────┐
    │ [Library] [Game A ×] [Game B ×]                                    │
    │   library: search, projects by console, batch actions              │
    │   project: NSUI-style editor (see ProjectEditor)                   │
    ├ Activity: status · busy indicator · log ──────────────────────────┤
    └ status bar: toolchain state ──────────────────────────────────────┘

Projects save themselves as they are edited, so there is nothing to lose
when a tab or the window closes. *Generate CIA* builds the current project
(asking where to save it), or every project ticked in the library (into
the output folder of the settings), one after the other.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QToolBar,
    QWidget,
)

from forwarder3ds import __version__
from forwarder3ds.builder.injector import default_cia_filename, ensure_cia_extension
from forwarder3ds.core import paths
from forwarder3ds.core.logs import TagFormatter, get_logger
from forwarder3ds.core.names import save_folder_name, suggest_title
from forwarder3ds.core.projects import PROJECT_EXTENSION, Asset, Project
from forwarder3ds.core.settings import Settings, save_settings
from forwarder3ds.ctr.cia import CiaReadError, read_game_cia
from forwarder3ds.gui.bridge import BuildWorker, QtLogHandler
from forwarder3ds.gui.context import AppContext
from forwarder3ds.gui.dialogs.cia_file_dialogs import choose_cia_to_save
from forwarder3ds.gui.dialogs.settings_dialog import PAGE_TOOLCHAIN, SettingsDialog
from forwarder3ds.gui.library_page import LibraryPage
from forwarder3ds.gui.project_editor import ProjectEditor
from forwarder3ds.gui.widgets.activity import ActivityPanel

_log = get_logger("gui")
APP_TITLE = "3DS RetroArch Injector"


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """Library, project tabs, settings and the build queue."""

    def __init__(self, context: AppContext | None = None) -> None:
        super().__init__()
        self.resize(1280, 820)
        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self._context = context or AppContext()
        self._worker: BuildWorker | None = None
        self._queue: list[tuple[Project, Path]] = []
        self._results: list[str] = []
        self._last_rom_dir = Path.home()

        self._library = LibraryPage(self._context)
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._library, self.tr("Library"))
        self._tabs.tabBar().setTabButton(0, self._tabs.tabBar().ButtonPosition.RightSide, None)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self._tabs)

        self._activity = ActivityPanel()
        self._toolchain_label = QLabel()
        self._toolchain_label.linkActivated.connect(
            lambda _link: self._open_settings(PAGE_TOOLCHAIN)
        )
        self._actions: list[QAction] = []
        self._log_handler = QtLogHandler()
        self._log_handler.setFormatter(TagFormatter(colour=False))
        self._log_handler.emitter.record.connect(self._activity.append_log)
        get_logger().addHandler(self._log_handler)

        self._build_toolbar()
        self._build_activity_dock()
        self.statusBar().addPermanentWidget(self._toolchain_label)
        self._library.new_requested.connect(self._new_project)
        self._library.import_requested.connect(self._import)
        self._library.open_requested.connect(self._open_projects)
        self._library.delete_requested.connect(self._delete_projects)
        self._library.export_requested.connect(self._export_projects)
        self._library.generate_requested.connect(self._generate_batch)
        self._restore_layout()
        self._show_toolchain_state()

    # ── Construction ─────────────────────────────────────────────────────

    def _action(
        self, text: str, theme: str, fallback: QStyle.StandardPixmap, shortcut: QKeySequence
    ) -> QAction:
        icon = QIcon.fromTheme(theme, self.style().standardIcon(fallback))
        action = QAction(icon, text, self)
        action.setShortcut(shortcut)
        native = shortcut.toString(QKeySequence.SequenceFormat.NativeText)
        action.setToolTip(f"{text.rstrip('…')} ({native})")
        return action

    def _build_toolbar(self) -> None:
        pixmap = QStyle.StandardPixmap
        new = self._action(
            self.tr("New project…"), "document-new", pixmap.SP_FileIcon, QKeySequence("Ctrl+N")
        )
        import_ = self._action(
            self.tr("Import…"), "document-open", pixmap.SP_DialogOpenButton, QKeySequence("Ctrl+O")
        )
        save = self._action(
            self.tr("Save project"),
            "document-save",
            pixmap.SP_DialogSaveButton,
            QKeySequence(QKeySequence.StandardKey.Save),
        )
        generate = self._action(
            self.tr("Generate CIA"),
            "run-build",
            pixmap.SP_MediaPlay,
            QKeySequence("Ctrl+B"),
        )
        settings = self._action(
            self.tr("Settings"),
            "configure",
            pixmap.SP_FileDialogDetailedView,
            QKeySequence(QKeySequence.StandardKey.Preferences),
        )
        new.triggered.connect(self._new_project)
        import_.triggered.connect(self._import)
        save.triggered.connect(self._save_current)
        generate.triggered.connect(self._generate_current)
        settings.triggered.connect(lambda _checked=False: self._open_settings())
        self._actions = [new, import_, save, generate, settings]

        toolbar = QToolBar(self.tr("Main"))
        toolbar.setObjectName("main-toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(new)
        toolbar.addAction(import_)
        toolbar.addSeparator()
        toolbar.addAction(save)
        toolbar.addAction(generate)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(settings)
        self.addToolBar(toolbar)

    def _build_activity_dock(self) -> None:
        dock = QDockWidget(self.tr("Activity"), self)
        dock.setObjectName("activity")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(self._activity)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [140], Qt.Orientation.Vertical)

    # ── Settings ─────────────────────────────────────────────────────────

    def _open_settings(self, page: int = 0) -> None:
        dialog = SettingsDialog(self._context.settings, self, page=page)
        dialog.applied.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self, settings: Settings) -> None:
        self._context.settings = settings
        try:
            save_settings(settings)
        except OSError as exc:
            _log.error("Cannot save the settings: %s", exc)
        self._context.reload()
        for editor in self._editors():
            editor.refresh_context()
        self._library.refresh()
        self._show_toolchain_state()

    def _show_toolchain_state(self) -> None:
        tools = self._context.tools
        if tools is not None and tools.complete:
            self._toolchain_label.setText(self.tr("Toolchain ready"))
        else:
            missing = ", ".join(tools.missing) if tools else "?"
            self._toolchain_label.setText(
                self.tr('<a href="#">Toolchain incomplete: {missing}</a>').format(missing=missing)
            )

    # ── Tabs ─────────────────────────────────────────────────────────────

    def _save_current(self) -> None:
        """Save the open project (every open one from the library), without building."""
        editor = self._tabs.currentWidget()
        editors = [editor] if isinstance(editor, ProjectEditor) else self._editors()
        for each in editors:
            each.save()
        if editors:
            names = ", ".join(each.project.title for each in editors[:3])
            self.statusBar().showMessage(self.tr("Saved: {names}").format(names=names), 4000)

    def _editors(self) -> list[ProjectEditor]:
        return [
            widget
            for index in range(self._tabs.count())
            if isinstance(widget := self._tabs.widget(index), ProjectEditor)
        ]

    def _editor_for(self, project_id: str) -> ProjectEditor | None:
        return next((e for e in self._editors() if e.project.id == project_id), None)

    def _open_projects(self, projects: list[Project]) -> None:
        for project in projects:
            editor = self._editor_for(project.id)
            if editor is None:
                editor = ProjectEditor(self._context, project)
                editor.saved.connect(lambda e=editor: self._on_project_saved(e))
                self._tabs.addTab(editor, project.title)
            self._tabs.setCurrentWidget(editor)

    def _on_project_saved(self, editor: ProjectEditor) -> None:
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._tabs.setTabText(index, editor.project.title)
        self._library.refresh()

    def _close_tab(self, index: int) -> None:
        editor = self._tabs.widget(index)
        if isinstance(editor, ProjectEditor):
            editor.save()
            self._tabs.removeTab(index)
            editor.deleteLater()

    # ── New / import / export / delete ───────────────────────────────────

    def _rom_filter(self) -> str:
        systems = self._context.systems
        extensions = sorted({ext for system in systems or [] for ext in system.extensions})
        patterns = " ".join(f"*.{ext}" for ext in [*extensions, "zip"])
        return self.tr("ROMs ({patterns});;All files (*)").format(patterns=patterns)

    def _new_project(self) -> None:
        path_text, _filter = QFileDialog.getOpenFileName(
            self, self.tr("Choose the ROM"), str(self._last_rom_dir), self._rom_filter()
        )
        if not path_text:
            return
        rom = Path(path_text)
        self._last_rom_dir = rom.parent
        console = self._ask_console(rom)
        if not console:
            return
        system = self._context.systems.get(console) if self._context.systems else None
        title = suggest_title(rom.name)
        project = self._context.store.create(
            rom,
            console,
            core=system.core if system else "",
            long_name=title,
            folder=save_folder_name(title),
        )
        _log.info("New project “%s” (%s)", project.title, console)
        self._library.refresh()
        self._open_projects([project])

    def _ask_console(self, rom: Path) -> str:
        systems = self._context.systems
        if systems is None:
            return ""
        guessed = systems.guess(rom)
        if guessed is not None:
            return guessed.console
        candidates = systems.candidates(rom) or sorted(systems, key=lambda s: s.name.casefold())
        names = [f"{system.name} ({system.console})" for system in candidates]
        if not names:
            return ""
        choice, ok = QInputDialog.getItem(
            self,
            self.tr("Console"),
            self.tr("Which console is '{name}' for?").format(name=rom.name),
            names,
            0,
            False,
        )
        return candidates[names.index(choice)].console if ok else ""

    def _import(self) -> None:
        path_text, _filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Import"),
            str(self._context.settings.general.output_path),
            self.tr("Projects or game CIAs (*{ext} *.zip *.cia);;All files (*)").format(
                ext=PROJECT_EXTENSION
            ),
        )
        if not path_text:
            return
        path = Path(path_text)
        try:
            if path.suffix.lower() == ".cia":
                projects = [self._import_cia(path)]
            else:
                projects = self._context.store.import_archive(path)
        except (OSError, ValueError, CiaReadError) as exc:
            _log.error("Cannot import %s: %s", path.name, exc)
            QMessageBox.critical(self, APP_TITLE, str(exc))
            return
        _log.info("Imported %d project(s) from %s", len(projects), path.name)
        self._library.refresh()
        self._open_projects(projects)

    def _import_cia(self, path: Path) -> Project:
        """A new project from a game CIA built by this tool (its ROM is copied out)."""
        loaded = read_game_cia(path)
        store = self._context.store
        project = store.create(
            Path(loaded.rom_name),
            loaded.console,
            core=loaded.core,
            folder=loaded.folder,
            long_name=loaded.long_name,
            short_name=loaded.short_name,
            publisher=loaded.manufacturer,
            unique_id=loaded.unique_id,
            built_id=loaded.unique_id,
            output=str(path),
            core_options=dict(loaded.core_options),
            remap=dict(loaded.remap),
        )
        if loaded.screen is not None:
            project.screen = loaded.screen
        assert project.directory is not None
        project.rom = str(loaded.extract_rom(project.directory / "rom"))
        with tempfile.TemporaryDirectory(prefix="3ds-injector-import-") as scratch:
            assets = loaded.write_assets(Path(scratch))
            for kind, source in (
                (Asset.ICON, assets.icon),
                (Asset.BANNER, assets.banner),
                (Asset.AUDIO, assets.audio),
                (Asset.BEZEL, assets.bezel),
            ):
                if source is not None:
                    store.set_asset(project, kind, source)
        store.save(project)
        for warning in loaded.warnings:
            _log.warning("%s", warning)
        return project

    def _export_projects(self, projects: list[Project]) -> None:
        if not projects:
            return
        name = save_folder_name(projects[0].title) if len(projects) == 1 else "projects"
        path_text, _filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Export projects"),
            str(Path.home() / f"{name}{PROJECT_EXTENSION}"),
            self.tr("Project exports (*{ext})").format(ext=PROJECT_EXTENSION),
        )
        if not path_text:
            return
        for editor in self._editors():
            editor.save()
        try:
            self._context.store.export(projects, Path(path_text))
        except OSError as exc:
            _log.error("Cannot export: %s", exc)
            QMessageBox.critical(self, APP_TITLE, str(exc))
            return
        _log.info("Exported %d project(s) to %s (ROMs not included)", len(projects), path_text)

    def _delete_projects(self, projects: list[Project]) -> None:
        if not projects:
            return
        names = "\n".join(f"• {project.title}" for project in projects[:10])
        more = "\n…" if len(projects) > 10 else ""
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            self.tr("Delete these projects? Their ROMs and CIAs are kept.\n\n{names}").format(
                names=names + more
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for project in projects:
            editor = self._editor_for(project.id)
            if editor is not None:
                self._tabs.removeTab(self._tabs.indexOf(editor))
                editor.deleteLater()
            self._context.store.delete(project)
        self._library.refresh()

    # ── Building ─────────────────────────────────────────────────────────

    def _generate_current(self) -> None:
        editor = self._tabs.currentWidget()
        if isinstance(editor, ProjectEditor):
            self._generate_one(editor)
        else:
            self._generate_batch(self._library.chosen())

    def _generate_one(self, editor: ProjectEditor) -> None:
        editor.save()
        if not self._check(editor):
            return
        project = editor.project
        start = Path(project.output).parent if project.output else self._output_dir()
        name = Path(project.output).name if project.output else default_cia_filename(project.title)
        output = choose_cia_to_save(self, start, name)
        if output is not None:
            self._start([(project, ensure_cia_extension(output))])

    def _generate_batch(self, projects: list[Project]) -> None:
        if not projects:
            return
        jobs, problems = [], []
        for project in projects:
            editor = self._editor_for(project.id)
            if editor is not None:
                editor.save()
                project = editor.project
            problem = self._context.problem(project)
            if problem:
                problems.append(f"• {project.title}: {problem}")
                continue
            output = self._output_dir() / default_cia_filename(project.title)
            jobs.append((project, output))
        if problems:
            QMessageBox.warning(
                self,
                APP_TITLE,
                self.tr("These projects cannot be built yet:\n\n{list}").format(
                    list="\n".join(problems)
                ),
            )
        if jobs:
            self._start(jobs)

    def _output_dir(self) -> Path:
        return self._context.settings.general.output_path

    def _check(self, editor: ProjectEditor) -> bool:
        problem = self._context.problem(editor.project)
        tools = self._context.tools
        if problem is None and (tools is None or not tools.complete):
            problem = self.tr(
                "The toolchain is incomplete (missing: {missing}). See Settings › Toolchain."
            ).format(missing=", ".join(tools.missing) if tools else "?")
        if problem:
            _log.warning("%s", problem)
            QMessageBox.warning(self, APP_TITLE, problem)
            return False
        return True

    def _set_busy(self, busy: bool, status: str = "") -> None:
        for action in self._actions:
            action.setEnabled(not busy)
        self._tabs.setEnabled(not busy)
        self._activity.set_busy(busy, status)

    def _start(self, jobs: list[tuple[Project, Path]]) -> None:
        tools = self._context.tools
        if tools is None or not tools.complete:
            self._check_toolchain_message()
            return
        self._queue = list(jobs)
        self._results = []
        self._next_build()

    def _check_toolchain_message(self) -> None:
        tools = self._context.tools
        missing = ", ".join(tools.missing) if tools else "?"
        QMessageBox.warning(
            self,
            APP_TITLE,
            self.tr("The toolchain is incomplete (missing: {missing}).").format(missing=missing),
        )

    def _next_build(self) -> None:
        if not self._queue:
            self._set_busy(False, self.tr("Done") if self._results else "")
            if len(self._results) > 1:
                QMessageBox.information(self, APP_TITLE, "\n".join(self._results))
            return
        project, output = self._queue.pop(0)
        try:
            self._context.refresh_card(project)
        except OSError as exc:
            _log.warning("Cannot draw the banner of “%s”: %s", project.title, exc)
        request = self._context.request(project, output)
        tools = self._context.tools
        if request is None or tools is None:
            self._results.append(f"✗ {project.title}: incomplete")
            self._next_build()
            return
        self._set_busy(True, self.tr("Building {name}…").format(name=project.title))
        _log.info("Building “%s” → %s", project.title, output)
        worker = BuildWorker(request, tools, self._context.settings.general.registry_path, self)
        worker.succeeded.connect(lambda unique_id, path, p=project: self._built(p, unique_id, path))
        worker.failed.connect(lambda message, p=project: self._failed(p, message))
        worker.finished.connect(self._next_build)
        self._worker = worker
        worker.start()

    def _built(self, project: Project, unique_id: int, output: Path) -> None:
        self._context.reload_registry()
        editor = self._editor_for(project.id)
        if editor is not None:
            editor.built(unique_id, output)
        else:
            project.unique_id = project.built_id = unique_id
            project.output = str(output)
            self._context.store.save(project)
        self._results.append(f"✔ {project.title} → {output.name}")
        self._activity.set_status(self.tr("Saved {name}").format(name=output.name))
        self._library.refresh()

    def _failed(self, project: Project, message: str) -> None:
        _log.error("%s: %s", project.title, message)
        self._results.append(f"✗ {project.title}: {message}")
        if not self._queue and len(self._results) == 1:
            QMessageBox.critical(self, APP_TITLE, message)

    # ── Layout persistence and closing ───────────────────────────────────

    @staticmethod
    def _ui_state() -> QSettings:
        return QSettings(str(paths.ui_state_file()), QSettings.Format.IniFormat)

    def _restore_layout(self) -> None:
        state = self._ui_state()
        for key, restore in (
            ("window/geometry", self.restoreGeometry),
            ("window/state", self.restoreState),
        ):
            value = state.value(key)
            if isinstance(value, QByteArray):
                restore(value)

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        """Refuse while building; save the open projects and the layout."""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, APP_TITLE, self.tr("A build is running. Wait for it to finish.")
            )
            event.ignore()
            return
        for editor in self._editors():
            editor.save()
        state = self._ui_state()
        state.setValue("window/geometry", self.saveGeometry())
        state.setValue("window/state", self.saveState())
        state.sync()
        get_logger().removeHandler(self._log_handler)
        super().closeEvent(event)
