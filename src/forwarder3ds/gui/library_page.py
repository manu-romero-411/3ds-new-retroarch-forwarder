"""The project library: every saved game, grouped by console.

Like NSUI's *Project Library*: a search box, one collapsible section per
console with its project count, check boxes for batch actions (generate
CIAs, export, delete) and *Open* for editing a project in its own tab.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.projects import Project
from forwarder3ds.core.title_id import unique_id_to_title_id
from forwarder3ds.gui.context import AppContext

_ID_ROLE = Qt.ItemDataRole.UserRole


class LibraryPage(QWidget):
    """Lists projects; the main window performs the actions."""

    open_requested = Signal(list)
    delete_requested = Signal(list)
    export_requested = Signal(list)
    generate_requested = Signal(list)
    new_requested = Signal()
    import_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._projects: dict[str, Project] = {}
        self._collapsed: set[str] = set()

        self._search = QLineEdit()
        self._search.setPlaceholderText(self.tr("Search"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        self._select_all = QCheckBox(self.tr("Select all"))
        self._select_all.toggled.connect(self._on_select_all)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([self.tr("Game"), self.tr("Core"), self.tr("Title ID")])
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.itemChanged.connect(self._update_buttons)
        self._tree.itemSelectionChanged.connect(self._update_buttons)
        self._tree.itemCollapsed.connect(lambda item: self._collapsed.add(item.text(0)))
        self._tree.itemExpanded.connect(lambda item: self._collapsed.discard(item.text(0)))

        self._new = QPushButton(self.tr("New project from ROM…"))
        self._import = QPushButton(self.tr("Import…"))
        self._import.setToolTip(self.tr("Add projects from an export file or a game CIA."))
        self._open = QPushButton(self.tr("Open"))
        self._delete = QPushButton(self.tr("Delete"))
        self._export = QPushButton(self.tr("Export…"))
        self._generate = QPushButton(self.tr("Generate CIA"))
        self._new.clicked.connect(self.new_requested)
        self._import.clicked.connect(self.import_requested)
        self._open.clicked.connect(lambda: self.open_requested.emit(self.chosen()))
        self._delete.clicked.connect(lambda: self.delete_requested.emit(self.chosen()))
        self._export.clicked.connect(lambda: self.export_requested.emit(self.chosen()))
        self._generate.clicked.connect(lambda: self.generate_requested.emit(self.chosen()))

        top = QHBoxLayout()
        top.addWidget(self._search, 1)
        top.addWidget(self._select_all)
        actions = QHBoxLayout()
        for button in (self._new, self._import):
            actions.addWidget(button)
        actions.addStretch(1)
        for button in (self._open, self._delete, self._export, self._generate):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._tree, 1)
        layout.addLayout(actions)
        self.refresh()

    # ── Contents ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read the store and redraw, keeping checks and collapsed sections."""
        checked = {project.id for project in self.checked()}
        self._projects = {project.id: project for project in self._context.store.list()}
        query = self._search.text().strip().casefold()
        systems = self._context.systems
        groups: dict[str, list[Project]] = {}
        for project in self._projects.values():
            haystack = f"{project.title} {project.db_name} {project.rom}".casefold()
            if query and query not in haystack:
                continue
            system = systems.get(project.console) if systems else None
            groups.setdefault(system.name if system else project.console, []).append(project)

        self._tree.blockSignals(True)
        self._tree.clear()
        for name in sorted(groups, key=str.casefold):
            members = groups[name]
            section = QTreeWidgetItem([f"{name} ({len(members)})"])
            section.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            self._tree.addTopLevelItem(section)
            for project in members:
                title_id = (
                    f"{unique_id_to_title_id(project.built_id):016X}"
                    if project.built_id is not None
                    else "—"
                )
                item = QTreeWidgetItem([project.title, project.core, title_id])
                item.setData(0, _ID_ROLE, project.id)
                item.setToolTip(0, project.rom)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    0, Qt.CheckState.Checked if project.id in checked else Qt.CheckState.Unchecked
                )
                section.addChild(item)
            section.setExpanded(section.text(0) not in self._collapsed)
        self._tree.blockSignals(False)
        self._update_buttons()

    def _items(self) -> list[QTreeWidgetItem]:
        items = []
        for row in range(self._tree.topLevelItemCount()):
            section = self._tree.topLevelItem(row)
            items += [section.child(index) for index in range(section.childCount())]
        return items

    def checked(self) -> list[Project]:
        """The ticked projects."""
        return [
            self._projects[str(item.data(0, _ID_ROLE))]
            for item in self._items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def chosen(self) -> list[Project]:
        """The ticked projects, or else the selected ones."""
        checked = self.checked()
        if checked:
            return checked
        return [
            self._projects[str(item.data(0, _ID_ROLE))]
            for item in self._tree.selectedItems()
            if item.data(0, _ID_ROLE)
        ]

    # ── Behaviour ────────────────────────────────────────────────────────

    def _on_select_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._tree.blockSignals(True)
        for item in self._items():
            item.setCheckState(0, state)
        self._tree.blockSignals(False)
        self._update_buttons()

    def _on_double_click(self, item: QTreeWidgetItem) -> None:
        project_id = item.data(0, _ID_ROLE)
        if project_id:
            self.open_requested.emit([self._projects[str(project_id)]])

    def _update_buttons(self) -> None:
        count = len(self.chosen())
        for button in (self._open, self._delete, self._export, self._generate):
            button.setEnabled(count > 0)
        self._generate.setText(
            self.tr("Generate {n} CIAs").format(n=count) if count > 1 else self.tr("Generate CIA")
        )
