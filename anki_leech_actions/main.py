"""Addon entrypoint providing tools to manage leech cards."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Iterable, Optional

from anki.cards import Card
from anki.collection import Collection
from anki.notes import Note
from aqt import gui_hooks, mw
from aqt.qt import (
    QAbstractItemView,
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QVBoxLayout,
    Qt,
)

from aqt.utils import restoreGeom, saveGeom, tooltip

from .migrations import CURRENT_SCHEMA_VERSION, run_migrations

ACTION_OPTIONS: list[tuple[str, str]] = [
    ("Reset progress", "reset"),
    ("Delay card", "delay"),
    ("Delete card", "delete"),
    ("Reset lapse count", "reset_lapses"),
    ("Remove leech tag", "remove_tag"),
]
ACTION_LABEL_MAP = {label.lower(): value for label, value in ACTION_OPTIONS}
ALLOWED_ACTIONS = {value for _, value in ACTION_OPTIONS}

ADDON_NAME = __name__
MENU_ACTION_TEXT = "Anki Leech Actions"
RUN_DIALOG_TITLE = "Run Leech Actions"
AUTO_CHECKPOINT_TITLE = "Anki Leech Actions (auto)"
_menu_action: Optional[QAction] = None


def _get_callable(obj: Any, *names: str):
    for name in names:
        fn = getattr(obj, name, None)
        if fn:
            return fn
    raise AttributeError(f"Object {obj} does not provide any of {names}")


def _format_summary(prefix: str, summary: dict[str, int]) -> str:
    parts = [f"{action}: {count}" for action, count in summary.items() if count]
    if not parts:
        return f"{prefix} — no changes"
    return f"{prefix} — " + ", ".join(parts)


def _format_bullet_summary(prefix: str, summary: dict[str, int]) -> str:
    parts = [f"- {action}: {count}" for action, count in summary.items() if count]
    if not parts:
        return f"{prefix} — no changes"
    return f"{prefix}:\n" + "\n".join(parts)


def _empty_summary() -> dict[str, int]:
    return {"delete": 0, "reset": 0, "delay": 0, "reset_lapses": 0, "remove_tag": 0, "skipped": 0}


@dataclass
class Rule:
    """Representation of a single management rule."""

    deck: str
    note_type: str
    action: str
    delay_days: Optional[int]

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> "Rule":
        deck = data.get("deck", "*")
        note_type = data.get("note_type", "*")
        raw_action = str(data.get("action", "reset")).strip()
        normalized_action = ACTION_LABEL_MAP.get(raw_action.lower(), raw_action.lower())
        if normalized_action not in ALLOWED_ACTIONS:
            normalized_action = "reset"
        raw_delay = data.get("delay_days")
        delay = int(raw_delay) if raw_delay not in (None, "") else None
        if normalized_action != "delay":
            delay = None
        elif delay is not None:
            delay = max(1, delay)
        else:
            delay = 7
        return cls(deck=deck, note_type=note_type, action=normalized_action, delay_days=delay)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck": self.deck,
            "note_type": self.note_type,
            "action": self.action,
            "delay_days": self.delay_days,
        }


class ConfigManager:
    """Loads and validates addon configuration."""

    def __init__(self) -> None:
        self._config = self._ensure_config()

    @staticmethod
    def _ensure_config() -> dict[str, Any]:
        addon_manager = mw.addonManager
        existing_config = addon_manager.getConfig(ADDON_NAME) or {}
        is_new = not existing_config
        config = copy.deepcopy(existing_config)
        config, migrated = run_migrations(config)
        if is_new or migrated:
            addon_manager.writeConfig(ADDON_NAME, config)
        return config

    @property
    def leech_tag(self) -> str:
        return str(self._config["leech_tag"])

    @property
    def rules(self) -> list[Rule]:
        raw_rules = self._config["rules"]
        return [Rule.from_raw(rule) for rule in raw_rules]

    @property
    def auto_run_enabled(self) -> bool:
        return bool(self._config["auto_run_enabled"])

    @property
    def show_auto_notifications(self) -> bool:
        return bool(self._config["show_auto_notifications"])

    def save_rules(self, rules: list[Rule], auto_run_enabled: bool, show_auto_notifications: bool) -> None:
        self._config["rules"] = [rule.to_dict() for rule in rules]
        self._config["auto_run_enabled"] = bool(auto_run_enabled)
        self._config["show_auto_notifications"] = bool(show_auto_notifications)
        self._config["schema_version"] = CURRENT_SCHEMA_VERSION
        mw.addonManager.writeConfig(ADDON_NAME, self._config)


class LeechActionManager:
    """Applies configured actions to leech cards."""

    def __init__(self, collection: Collection) -> None:
        self.col = collection
        self.config = ConfigManager()

    def find_leech_cards(self, deck: Optional[str] = None, note_type: Optional[str] = None) -> list[int]:
        query_parts = [f"tag:{self.config.leech_tag}"]
        if deck:
            query_parts.append(f'deck:"{deck}"')
        if note_type:
            query_parts.append(f'note:"{note_type}"')
        query = " ".join(query_parts)
        finder = _get_callable(self.col, "find_cards", "findCards")
        return finder(query)

    def process_cards(self, card_ids: Iterable[int], simulate: bool = False) -> dict[str, int]:
        total_summary = _empty_summary()
        if not card_ids:
            return total_summary

        for cid in card_ids:
            card = self._get_card(cid)
            if not card:
                total_summary["skipped"] += 1
                continue
            card_summary = self.apply_rules_to_card(card, simulate=simulate)
            for key, value in card_summary.items():
                total_summary[key] += value
        return total_summary

    def apply_rules_to_card(self, card: Card, simulate: bool = False) -> dict[str, int]:
        summary = _empty_summary()
        note = card.note()
        deck_name = self.col.decks.name(card.did)
        model_id = getattr(note, "mid", None)
        model = self.col.models.get(model_id) if model_id else None
        model_name = model.get("name", "") if model else ""
        matched = False
        for rule in self.config.rules:
            if not self._rule_matches(rule, deck_name, model_name):
                continue
            matched = True
            self._execute_rule(rule, card, note, summary, simulate=simulate)
            if rule.action == "delete":
                break
        if not matched:
            summary["skipped"] += 1
        return summary

    def _rule_matches(self, rule: Rule, deck_name: str, model_name: str) -> bool:
        return fnmatch(deck_name, rule.deck) and fnmatch(model_name, rule.note_type)

    def _execute_rule(
        self,
        rule: Rule,
        card: Card,
        note: Note,
        summary: dict[str, int],
        simulate: bool = False,
    ) -> None:
        if rule.action == "delete":
            if not simulate:
                self._strip_leech_tag(note)
                self._delete_card(card)
            summary["delete"] += 1
        elif rule.action == "reset":
            if not simulate:
                self._reset_card(card)
                self._strip_leech_tag(note)
            summary["reset"] += 1
        elif rule.action == "delay":
            delay_days = rule.delay_days or 7
            if not simulate:
                self._delay_card(card, delay_days)
                self._strip_leech_tag(note)
            summary["delay"] += 1
        elif rule.action == "reset_lapses":
            if not simulate:
                self._reset_lapses(card)
                self._strip_leech_tag(note)
            summary["reset_lapses"] += 1
        elif rule.action == "remove_tag":
            if not simulate:
                self._strip_leech_tag(note)
            summary["remove_tag"] += 1
        else:
            summary["skipped"] += 1

    def _get_card(self, cid: int) -> Optional[Card]:
        getter = getattr(self.col, "get_card", None) or getattr(self.col, "getCard", None)
        if not getter:
            return None
        return getter(cid)

    def _delete_card(self, card: Card) -> None:
        remover = _get_callable(self.col, "rem_cards", "remCards")
        remover([card.id])

    def _reset_card(self, card: Card) -> None:
        resetter = _get_callable(self.col.sched, "reset_cards", "resetCards")
        resetter([card.id])

    def _delay_card(self, card: Card, delay_days: int) -> None:
        delay_days = max(1, delay_days)
        card.queue = 2
        card.type = 2
        card.ivl = delay_days
        card.due = self.col.sched.today + delay_days
        card.flush()

    def _reset_lapses(self, card: Card) -> None:
        card.lapses = 0
        card.flush()

    def _strip_leech_tag(self, note: Note) -> None:
        tag = self.config.leech_tag
        if tag not in note.tags:
            return
        note.tags = [t for t in note.tags if t != tag]
        note.flush()


class LeechActionsDialog(QDialog):
    """Qt dialog to preview and trigger leech actions."""

    def __init__(self, manager: LeechActionManager) -> None:
        super().__init__(mw)
        self._manager = manager
        self.setWindowTitle(RUN_DIALOG_TITLE)
        self.button_box: QDialogButtonBox | None = None
        self._setup_ui()
        restoreGeom(self, "anki_leech_actions.dialog")
        self._preview_summary: dict[str, int] | None = None
        self._preview_card_ids: list[int] | None = None
        self._refresh_preview()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.preview_box = QLabel(self)
        self.preview_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.preview_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_box.setWordWrap(True)
        layout.addWidget(self.preview_box)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        confirm_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        confirm_btn.setText("Confirm")
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Cancel")
        self.button_box.accepted.connect(self._confirm)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _refresh_preview(self) -> None:
        card_ids = self._manager.find_leech_cards()
        self._preview_card_ids = list(card_ids)
        if not card_ids:
            self.preview_box.setText("No leech cards currently match the configured rules.")
            self._preview_summary = None
            self._set_confirm_enabled(False)
            return
        summary = self._manager.process_cards(card_ids, simulate=True)
        self._preview_summary = summary
        self.preview_box.setText(_format_bullet_summary("Pending actions", summary))
        self._set_confirm_enabled(any(summary.values()))

    def _set_confirm_enabled(self, enabled: bool) -> None:
        if not self.button_box:
            return
        button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if button:
            button.setEnabled(enabled)

    def _confirm(self) -> None:
        if not self._preview_card_ids:
            self._refresh_preview()
            if not self._preview_card_ids:
                return
        if not self._preview_summary or not any(self._preview_summary.values()):
            tooltip("No changes would be applied.")
            return
        mw.checkpoint(RUN_DIALOG_TITLE)
        summary = self._manager.process_cards(self._preview_card_ids)
        mw.reset()
        tooltip(_format_summary("Processed leech cards", summary))
        self._refresh_preview()

    def reject(self) -> None:  # type: ignore[override]
        saveGeom(self, "anki_leech_actions.dialog")
        super().reject()


class RulesConfigDialog(QDialog):
    """Custom configuration dialog with dropdown-based rules."""

    def __init__(self, manager: ConfigManager, collection: Collection) -> None:
        super().__init__(mw)
        self._manager = manager
        self._col = collection
        self._actions = list(ACTION_OPTIONS)
        self._action_label_map = {label.lower(): value for label, value in self._actions}
        self._deck_choices = self._build_deck_choices()
        self._note_type_choices = self._build_note_type_choices()
        self._auto_notification_checkbox: QCheckBox | None = None
        self.setWindowTitle("Anki Leech Actions — Rules")
        self.resize(1200, 600)
        self._setup_ui()
        restoreGeom(self, "anki_leech_actions.config")
        self._load_rules()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._auto_run_checkbox = QCheckBox("Automatically run rules when cards gain the leech tag", self)
        self._auto_run_checkbox.setChecked(self._manager.auto_run_enabled)
        self._auto_run_checkbox.stateChanged.connect(self._sync_auto_notification_checkbox)
        layout.addWidget(self._auto_run_checkbox)

        self._auto_notification_checkbox = QCheckBox(
            "Show notification after automatically processing a leech card",
            self,
        )
        self._auto_notification_checkbox.setChecked(self._manager.show_auto_notifications)
        layout.addWidget(self._auto_notification_checkbox)
        self._sync_auto_notification_checkbox()

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["", "Deck", "Note type", "Action", "Delay (days)"])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 35)
        header.resizeSection(1, 245)
        header.resizeSection(2, 175)
        header.resizeSection(3, 130)
        header.resizeSection(4, 130)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._update_selection_indicators)
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        add_btn = QPushButton("Add rule", self)
        add_btn.clicked.connect(self._add_rule_row)
        remove_btn = QPushButton("Remove selected", self)
        remove_btn.clicked.connect(self._remove_selected_rows)
        move_up_btn = QPushButton("Move up", self)
        move_up_btn.clicked.connect(self._move_selected_rows_up)
        move_down_btn = QPushButton("Move down", self)
        move_down_btn.clicked.connect(self._move_selected_rows_down)
        button_row.addWidget(add_btn)
        button_row.addWidget(remove_btn)
        button_row.addWidget(move_up_btn)
        button_row.addWidget(move_down_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        run_btn = QPushButton("Run actions now", self)
        run_btn.clicked.connect(lambda: _show_run_dialog(modal=True))
        layout.addWidget(run_btn)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _sync_auto_notification_checkbox(self) -> None:
        enabled = self._auto_run_checkbox.isChecked()
        if hasattr(self, "_auto_notification_checkbox") and self._auto_notification_checkbox:
            self._auto_notification_checkbox.setEnabled(enabled)

    def _build_deck_choices(self) -> list[tuple[str, str]]:
        decks = self._col.decks
        names: list[str] = []
        getter = getattr(decks, "all_names_and_ids", None)
        if getter:
            entries = getter(include_filtered=False)
            for entry in entries:
                name = getattr(entry, "name", None) or getattr(entry, "fullname", None)
                if not name and isinstance(entry, dict):
                    name = entry.get("name")
                if not name and isinstance(entry, (list, tuple)):
                    name = entry[1] if len(entry) > 1 else entry[0]
                if name:
                    names.append(name)
        else:
            fallback = getattr(decks, "allNames", None)
            if fallback:
                names.extend(fallback())
        unique_names = sorted(set(names))
        return [("Any deck (*)", "*")] + [(name, name) for name in unique_names]

    def _build_note_type_choices(self) -> list[tuple[str, str]]:
        models = self._col.models
        names: list[str] = []
        getter = getattr(models, "all_names_and_ids", None)
        if getter:
            entries = getter()
            for entry in entries:
                name = getattr(entry, "name", None)
                if not name and isinstance(entry, dict):
                    name = entry.get("name")
                if not name and isinstance(entry, (list, tuple)):
                    name = entry[1] if len(entry) > 1 else entry[0]
                if name:
                    names.append(name)
        else:
            fallback = getattr(models, "all", None)
            if fallback:
                for model in fallback():
                    name = model.get("name")
                    if name:
                        names.append(name)
        unique_names = sorted(set(names))
        return [("Any note type (*)", "*")] + [(name, name) for name in unique_names]

    def _load_rules(self) -> None:
        self._populate_rules(self._manager.rules)

    def _populate_rules(self, rules: list[Rule]) -> None:
        self.table.setRowCount(0)
        for rule in rules:
            self._add_rule_row(rule)
        self._update_selection_indicators()

    def _create_combo(self, options: list[tuple[str, str]], value: str) -> QComboBox:
        combo = QComboBox(self)
        for label, data in options:
            combo.addItem(label, data)
        index = combo.findData(value)
        if index < 0:
            index = 0
        combo.setCurrentIndex(index)
        return combo

    def _create_action_combo(self, value: str, delay_widget: QSpinBox) -> QComboBox:
        combo = QComboBox(self)
        for label, data in self._actions:
            combo.addItem(label, data)
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _idx, c=combo, d=delay_widget: self._sync_delay_enabled(c, d))
        self._sync_delay_enabled(combo, delay_widget)
        return combo

    def _create_delay_spin(self, delay_value: Optional[int]) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setMinimum(0)
        spin.setMaximum(365)
        spin.setSpecialValueText("N/A")
        value = delay_value if delay_value is not None else 0
        spin.setValue(max(0, value))
        if value and value > 0:
            spin.setProperty("last_delay_value", value)
        spin.valueChanged.connect(lambda val, widget=spin: self._on_delay_value_changed(widget, val))
        return spin

    def _on_delay_value_changed(self, widget: QSpinBox, value: int) -> None:
        if value > 0:
            widget.setProperty("last_delay_value", value)

    def _add_rule_row(self, rule: Optional[Rule] = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        deck_value = rule.deck if rule else "*"
        note_value = rule.note_type if rule else "*"
        action_value = rule.action if rule else "reset"
        delay_value = rule.delay_days if rule and rule.delay_days is not None else None

        indicator = QTableWidgetItem("")
        indicator.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        indicator.setFlags(indicator.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, indicator)

        deck_combo = self._create_combo(self._deck_choices, deck_value)
        deck_combo.setMinimumWidth(200)
        note_combo = self._create_combo(self._note_type_choices, note_value)
        note_combo.setMinimumWidth(200)
        delay_spin = self._create_delay_spin(delay_value if rule and rule.action == "delay" else None)
        action_combo = self._create_action_combo(action_value, delay_spin)
        action_combo.setMinimumWidth(140)

        self.table.setCellWidget(row, 1, deck_combo)
        self.table.setCellWidget(row, 2, note_combo)
        self.table.setCellWidget(row, 3, action_combo)
        self.table.setCellWidget(row, 4, delay_spin)
        for col in range(1, 5):
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, col, item)

    def _selected_rows(self) -> list[int]:
        model = self.table.selectionModel()
        if not model:
            return []
        return sorted({index.row() for index in model.selectedRows()})

    def _select_rows(self, rows: list[int]) -> None:
        self.table.clearSelection()
        for row in rows:
            if 0 <= row < self.table.rowCount():
                self.table.selectRow(row)
        self._update_selection_indicators()

    def _move_selected_rows(self, direction: int) -> None:
        row_count = self.table.rowCount()
        if row_count < 2 or direction == 0:
            return
        selected_rows = self._selected_rows()
        if not selected_rows:
            return
        rules = self._collect_rules()
        new_positions: list[int] = []
        if direction < 0:
            for row in selected_rows:
                if row == 0:
                    new_positions.append(row)
                    continue
                rules[row - 1], rules[row] = rules[row], rules[row - 1]
                new_positions.append(row - 1)
        else:
            for row in reversed(selected_rows):
                if row >= row_count - 1:
                    new_positions.append(row)
                    continue
                rules[row], rules[row + 1] = rules[row + 1], rules[row]
                new_positions.append(row + 1)
        self._populate_rules(rules)
        self._select_rows(sorted(set(new_positions)))

    def _move_selected_rows_up(self) -> None:
        self._move_selected_rows(-1)

    def _move_selected_rows_down(self) -> None:
        self._move_selected_rows(1)

    def _update_selection_indicators(self) -> None:
        model = self.table.selectionModel()
        selected_rows = set()
        if model:
            selected_rows = {index.row() for index in model.selectedRows()}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 0, item)
            item.setText("●" if row in selected_rows else "")

    def _remove_selected_rows(self) -> None:
        for row in reversed(self._selected_rows()):
            self.table.removeRow(row)
        self._update_selection_indicators()

    def _sync_delay_enabled(self, combo: QComboBox, delay_widget: QSpinBox) -> None:
        is_delay = combo.currentData() == "delay"
        stored_value = delay_widget.property("last_delay_value")
        if is_delay:
            delay_widget.setMinimum(1)
            if isinstance(stored_value, int) and stored_value > 0:
                fallback = stored_value
            else:
                current = delay_widget.value()
                fallback = current if current > 0 else 7
            delay_widget.blockSignals(True)
            delay_widget.setValue(fallback)
            delay_widget.blockSignals(False)
            delay_widget.setProperty("last_delay_value", fallback)
            delay_widget.setEnabled(True)
        else:
            delay_widget.setMinimum(0)
            if delay_widget.isEnabled() and delay_widget.value() > 0:
                delay_widget.setProperty("last_delay_value", delay_widget.value())
            delay_widget.blockSignals(True)
            delay_widget.setValue(0)
            delay_widget.blockSignals(False)
            delay_widget.setEnabled(False)

    def _collect_rules(self) -> list[Rule]:
        rules: list[Rule] = []
        for row in range(self.table.rowCount()):
            deck_combo = self.table.cellWidget(row, 1)
            note_combo = self.table.cellWidget(row, 2)
            action_combo = self.table.cellWidget(row, 3)
            delay_spin = self.table.cellWidget(row, 4)
            if not isinstance(deck_combo, QComboBox) or not isinstance(note_combo, QComboBox):
                continue
            if not isinstance(action_combo, QComboBox) or not isinstance(delay_spin, QSpinBox):
                continue
            deck = deck_combo.currentData() or deck_combo.currentText()
            note_type = note_combo.currentData() or note_combo.currentText()
            action_data = action_combo.currentData()
            if not action_data:
                action_label = action_combo.currentText().strip().lower()
                action_data = self._action_label_map.get(action_label, "reset")
            action = action_data or "reset"
            delay_days = max(1, delay_spin.value()) if action == "delay" else None
            rules.append(Rule(deck=deck, note_type=note_type, action=action, delay_days=delay_days))
        return rules

    def _save(self) -> None:
        rules = self._collect_rules()
        self._manager.save_rules(
            rules,
            self._auto_run_checkbox.isChecked(),
            bool(self._auto_notification_checkbox and self._auto_notification_checkbox.isChecked()),
        )
        saveGeom(self, "anki_leech_actions.config")
        tooltip("Saved Anki Leech Actions configuration.")
        self.accept()

    def reject(self) -> None:  # type: ignore[override]
        saveGeom(self, "anki_leech_actions.config")
        super().reject()


def _show_run_dialog(modal: bool = False) -> None:
    if not mw or not mw.col:
        tooltip("Open a collection to run actions.")
        return
    dialog = LeechActionsDialog(LeechActionManager(mw.col))
    if modal:
        dialog.exec()
    else:
        dialog.show()


def _auto_process_leech(card: Optional[Card]) -> None:
    if not card or not mw or not mw.col:
        return
    manager = LeechActionManager(mw.col)
    if not manager.config.auto_run_enabled:
        return
    note = card.note()
    if manager.config.leech_tag not in note.tags:
        return
    mw.checkpoint(AUTO_CHECKPOINT_TITLE)
    summary = manager.apply_rules_to_card(card)
    if not any(summary.values()):
        return
    if manager.config.show_auto_notifications:
        tooltip(_format_summary("Auto-processed leech card", summary))
    mw.reset()


def _on_reviewer_did_answer_card(_reviewer: Any, card: Optional[Card], _ease: int) -> None:
    if not card:
        return
    QTimer.singleShot(0, lambda: _auto_process_leech(card))


def _show_rules_dialog() -> None:
    if not mw or not mw.col:
        tooltip("Open a collection to configure rules.")
        return
    dialog = RulesConfigDialog(ConfigManager(), mw.col)
    dialog.exec()


def _inject_menu_entry() -> None:
    global _menu_action
    if not mw:
        return
    if not _menu_action:
        _menu_action = QAction(MENU_ACTION_TEXT, mw)
        _menu_action.triggered.connect(_show_rules_dialog)
        mw.form.menuTools.addAction(_menu_action)


def _on_profile_loaded() -> None:
    _inject_menu_entry()


gui_hooks.profile_did_open.append(_on_profile_loaded)
gui_hooks.reviewer_did_answer_card.append(_on_reviewer_did_answer_card)
