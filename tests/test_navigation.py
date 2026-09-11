"""Deck selection, Pass/Fail semantics and copy-only migration contracts."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtTest import QTest

from aqt.builtin_features.learning.deck_select import DeckTreeSelect
from aqt.builtin_features.passfail2 import (
    DEFAULTS,
    answer_buttons,
    remap_answer,
    validate,
)
from aqt.builtin_features.storage import FeatureStorage, write_object
from aqt.qt import QApplication, QPoint, Qt


class PassFailTests(unittest.TestCase):
    def test_two_buttons_and_all_non_again_keys_use_native_default(self):
        for default in (2, 3):
            reviewer = SimpleNamespace(_defaultEase=lambda: default)
            value = DEFAULTS | {"enabled": True}
            self.assertEqual(
                answer_buttons((), reviewer, value), ((1, "Fail"), (default, "Pass"))
            )
            self.assertEqual(remap_answer((True, 1), reviewer, value), (True, 1))
            for key in (2, 3, 4):
                self.assertEqual(
                    remap_answer((True, key), reviewer, value), (True, default)
                )
                self.assertEqual(
                    remap_answer((False, key), reviewer, value), (False, default)
                )

    def test_native_mode_preserves_buttons_and_all_rating_values(self):
        buttons = ((1, "Again"), (2, "Hard"), (3, "Good"), (4, "Easy"))
        reviewer = SimpleNamespace(_defaultEase=lambda: 3)
        self.assertEqual(answer_buttons(buttons, reviewer, DEFAULTS), buttons)
        for key in (1, 2, 3, 4):
            self.assertEqual(remap_answer((True, key), reviewer, DEFAULTS), (True, key))

    def test_custom_toggle_retains_values_and_escapes_button_text(self):
        reviewer = SimpleNamespace(_defaultEase=lambda: 3)
        value = DEFAULTS | {
            "enabled": True,
            "toggle_names_textcolors": "1",
            "again_button_name": "<b>&失败",
            "again_button_textcolor": "#123456",
        }
        validate(value)
        labels = answer_buttons((), reviewer, value)
        self.assertIn("&lt;b&gt;&amp;失败", labels[0][1])
        self.assertIn("#123456", labels[0][1])
        self.assertEqual(
            answer_buttons((), reviewer, value | {"toggle_names_textcolors": "0"}),
            ((1, "Fail"), (3, "Pass")),
        )
        self.assertEqual(value["again_button_name"], "<b>&失败")
        for invalid in (
            {"good_button_name": "x" * 15},
            {"good_button_textcolor": "red;"},
            {"enabled": "false"},
        ):
            with self.assertRaises(ValueError):
                validate(value | invalid)


class PassFailMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = FeatureStorage(self.base)

    def test_legacy_config_and_disabled_state_survive_without_overwriting_source(self):
        for disabled in (False, True):
            with self.subTest(disabled=disabled):
                folder = self.base / str(disabled)
                legacy = folder / "addons21/876946123/meta.json"
                write_object(
                    legacy,
                    {
                        "disabled": disabled,
                        "config": {
                            "toggle_names_textcolors": "1",
                            "good_button_name": "通过",
                            "future": "keep",
                        },
                    },
                )
                original = legacy.read_bytes()
                store = FeatureStorage(folder)
                value = store.load_passfail()
                self.assertEqual(value["enabled"], not disabled)
                self.assertEqual(value["good_button_name"], "通过")
                self.assertEqual(value["future"], "keep")
                write_object(store.passfail_path, value | {"enabled": disabled})
                self.assertEqual(
                    FeatureStorage(folder).load_passfail()["enabled"], disabled
                )
                self.assertEqual(legacy.read_bytes(), original)

    def test_new_install_preserves_native_ratings_and_corrupt_legacy_is_not_replaced(
        self,
    ):
        self.assertFalse(self.store.load_passfail()["enabled"])
        other = self.base / "corrupt"
        legacy = other / "addons21/PassFail2/meta.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{corrupt")
        store = FeatureStorage(other)
        with self.assertRaises(json.JSONDecodeError):
            store.load_passfail()
        self.assertFalse(store.passfail_path.exists())
        self.assertEqual(legacy.read_text(), "{corrupt")

    def test_renamed_legacy_package_retains_its_enabled_state_and_names(self):
        legacy = self.base / "addons21/renamed-copy"
        write_object(legacy / "manifest.json", {"package": "PassFail2"})
        write_object(legacy / "meta.json", {"config": {"good_button_name": "保留名称"}})
        value = self.store.load_passfail()
        self.assertTrue(value["enabled"])
        self.assertEqual(value["good_button_name"], "保留名称")


class DeckTreeTests(unittest.TestCase):
    def test_clicking_expand_arrow_keeps_popup_open_and_selected_deck(self):
        self.selector.show()
        self.selector.show_popup()
        self.app.processEvents()
        parent = self.selector.items[1]
        before = parent.isExpanded()
        rect = self.selector.tree.visualItemRect(parent)
        QTest.mouseClick(
            self.selector.tree.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(rect.left() - 10, rect.center().y()),
        )
        self.app.processEvents()
        self.assertNotEqual(parent.isExpanded(), before)
        self.assertTrue(self.selector.popup.isVisible())
        self.assertEqual(self.selector.currentData(), 2)
        self.selector.popup.hide()
        self.selector.hide()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.selector = DeckTreeSelect()
        self.addCleanup(self.selector.deleteLater)
        self.entries = [
            ("全部牌组", 0),
            ("A", 1),
            ("A::同名", 2),
            ("B", 3),
            ("B::同名", 4),
            ("全部牌组", 5),
        ]
        self.selector.set_decks(self.entries, 2)

    def test_duplicate_names_keep_paths_and_selected_id_through_search_and_collapse(
        self,
    ):
        self.selector.search.setText("同名")
        self.assertEqual(self.selector.items[2].text(1), "A::同名")
        self.assertEqual(self.selector.items[4].text(1), "B::同名")
        self.assertFalse(self.selector.items[1].isHidden())
        self.assertEqual(self.selector.currentData(), 2)
        self.selector.items[1].setExpanded(False)
        self.assertEqual(self.selector.currentData(), 2)
        self.selector.choose(self.selector.items[4])
        self.assertEqual(self.selector.currentData(), 4)
        self.assertEqual(self.selector.currentText(), "B::同名")
        self.assertNotEqual(self.selector.items[0], self.selector.items[5])

    def test_full_path_search_and_empty_results_do_not_change_scope(self):
        self.selector.search.setText("B::同名")
        self.assertTrue(self.selector.items[1].isHidden())
        self.assertFalse(self.selector.items[3].isHidden())
        self.selector.search.setText("不存在")
        self.assertFalse(self.selector.empty.isHidden())
        self.assertEqual(self.selector.currentData(), 2)
        self.selector.search.setText("B::同名")
        self.selector.select_first_match()
        self.assertEqual(self.selector.currentData(), 4)

    def test_many_decks_and_deleted_selection_fall_back_to_explicit_all_scope(self):
        entries = self.entries + [(f"大量::{i:04}::同名", 100 + i) for i in range(1000)]
        self.selector.set_decks(entries, 1099)
        self.selector.search.setText("大量::0999")
        self.selector.select_first_match()
        self.assertEqual(self.selector.currentData(), 1099)
        self.selector.set_decks(self.entries, 1099)
        self.assertEqual(self.selector.currentData(), 0)
        self.assertEqual(self.selector.currentText(), "全部牌组")
