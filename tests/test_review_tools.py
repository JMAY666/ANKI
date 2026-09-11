"""Behavioral contracts for migration, timing, statistics and grading compatibility."""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from anki.collection import Collection
from anki.lang import set_lang
from aqt.builtin_features.review_tools import decorate_buttons
from aqt.builtin_features.review_tools.confidence import _scan
from aqt.builtin_features.review_tools.config import ToolConfig, defaults, validate
from aqt.builtin_features.review_tools.pace_graph.compat import normalize_config
from aqt.builtin_features.review_tools.pace_graph.model import Pace, SmoothPace
from aqt.builtin_features.review_tools.search_stats import card_ids, handle_data
from aqt.builtin_features.storage import FeatureStorage, read_object, write_object


class ToolStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_migrates_overrides_unknown_fields_and_files_only_once(self):
        legacy = self.base / "addons21/renamed"
        write_object(legacy / "manifest.json", {"package": "pace_graph"})
        write_object(legacy / "config.json", {"goal": 17, "unknown": {"keep": True}})
        write_object(legacy / "meta.json", {"disabled": True, "config": {"goal": 23}})
        (legacy / "user_files").mkdir()
        (legacy / "user_files/settings.json").write_text("preserve original")
        before = {str(p): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
        storage = ToolConfig(FeatureStorage(self.base))
        self.assertEqual(storage.values["pace_graph"]["goal"], 23)
        self.assertEqual(storage.values["pace_graph"]["unknown"], {"keep": True})
        storage.save("pace_graph", storage.values["pace_graph"] | {"goal": 19.0})
        restarted = ToolConfig(FeatureStorage(self.base))
        self.assertEqual(restarted.values["pace_graph"]["goal"], 19)
        self.assertEqual(
            before, {str(p): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
        )
        self.assertEqual(
            (storage.root / "pace_graph/user_files/settings.json").read_text(),
            "preserve original",
        )

    def test_corrupt_saved_configuration_is_not_replaced(self):
        path = self.base / "builtin_features/review_tools/pace_graph.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json")
        with self.assertRaises(ValueError):
            ToolConfig(FeatureStorage(self.base))
        self.assertEqual(path.read_text(), "not json")

    def test_different_legacy_copies_require_explicit_resolution(self):
        for name, goal in (("1323545382", 11), ("pace_graph", 13)):
            write_object(self.base / "addons21" / name / "config.json", {"goal": goal})
        with self.assertRaisesRegex(ValueError, "多个不同"):
            ToolConfig(FeatureStorage(self.base))
        self.assertFalse(
            (self.base / "builtin_features/review_tools/pace_graph.json").exists()
        )

    def test_invalid_save_leaves_last_good_file_intact(self):
        store = ToolConfig(FeatureStorage(self.base))
        before = store.path("policy").read_bytes()
        with self.assertRaises(ValueError):
            store.save("policy", store.values["policy"] | {"feedback": "both"})
        self.assertEqual(store.path("policy").read_bytes(), before)
        self.assertEqual(read_object(store.path("policy"))["style"], "current")


class PaceTests(unittest.TestCase):
    def test_question_to_flip_timing_excludes_pauses_sleep_and_answer_reading(self):
        pace = Pace(10, 5)
        pace.question()
        pace.advance(1.2, True)
        pace.advance(1, False)
        pace.advance(40, True)
        pace.paused = True
        pace.advance(1, True)
        pace.paused = False
        pace.flip()
        pace.advance(1, True)
        pace.answer()
        self.assertEqual(list(pace.answers), [1.2])
        self.assertAlmostEqual(pace.delta(), 8.8)

    def test_new_question_does_not_improve_average_and_smoothing_is_bounded(self):
        pace = Pace(10, 5)
        pace.answers.extend([8, 12])
        pace.question()
        self.assertEqual(pace.average(), 10)
        pace.current = 14
        self.assertEqual(pace.average(), 12)
        smooth = SmoothPace(4)
        self.assertTrue(0 < smooth.advance(10, 1) < 10)


class CollectionToolTests(unittest.TestCase):
    def setUp(self):
        set_lang("en_US")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.col = Collection(str(Path(self.temp.name) / "collection.anki2"))
        self.addCleanup(self.col.close)
        note = self.col.new_note(self.col.models.by_name("Basic"))
        note["Front"], note["Back"] = "Synthetic only", "Answer"
        self.col.add_note(note, self.col.decks.id("Synthetic"))
        self.cid = note.cards()[0].id

    def test_statistics_rejects_injected_ids_and_returns_explicit_columns(self):
        for bad in (["1) or 1=1 --"], [True], [-1], {"id": 1}):
            with self.assertRaises(ValueError):
                card_ids(bad)
        data = handle_data(self.col, "cardData", json.dumps([self.cid]).encode())
        self.assertEqual(data["data"][0][data["columns"].index("id")], self.cid)
        self.assertEqual(handle_data(self.col, "cardData", b"[]")["data"], [])
        self.assertEqual(
            handle_data(self.col, "cardSearch", b"deck:Synthetic"), [self.cid]
        )

    def test_confidence_scan_respects_consecutive_pairs_and_does_not_write(self):
        cutoff = self.col.sched.day_cutoff * 1000
        for days, ease, time_ms, kind in (
            (9, 3, 1000, 1),
            (7, 1, 10000, 1),
            (5, 3, 10000, 1),
            (3, 3, 10000, 1),
            (1, 0, 0, 4),
        ):
            self.col.db.execute(
                "insert into revlog values (?,?,?,?,?,?,?,?,?)",
                cutoff - days * 86400000,
                self.cid,
                -1,
                ease,
                20,
                10,
                2500,
                time_ms,
                kind,
            )
        before = list(self.col.db.all("select * from revlog"))
        cards, summary = _scan(defaults("confident_wrong"), self.col)
        self.assertEqual(cards, [(self.cid, "Synthetic", 1, 1)])
        self.assertEqual(summary["Synthetic"], (1, 1, 0, 1))
        self.assertEqual(self.col.db.all("select * from revlog"), before)

    def test_passfail_labels_take_precedence_in_both_color_modes(self):
        values = {
            name: defaults(name)
            for name in ("policy", "advanced_review", "button_colours")
        }
        pf = {"enabled": True, "toggle_names_textcolors": "1"}
        mw = SimpleNamespace(
            review_tools=SimpleNamespace(config=SimpleNamespace(values=values)),
            passfail2=SimpleNamespace(value=pf),
            col=self.col,
        )
        reviewer = SimpleNamespace(mw=mw, card=self.col.get_card(self.cid))
        buttons = ((1, '<span style="color:#123456">No</span>'), (3, "Yes"))
        with patch("aqt.mw", mw):
            for mode in ("advanced", "colours"):
                values["policy"]["style"] = mode
                self.assertEqual(decorate_buttons(buttons, reviewer), buttons)


class ValidationTests(unittest.TestCase):
    def test_pace_normalized_defaults_save_without_a_position(self):
        value = normalize_config(defaults("pace_graph"))
        validate("pace_graph", value)

    def test_defaults_validate_and_bad_dimensions_do_not(self):
        conf = defaults("advanced_review")
        validate("advanced_review", conf)
        for replacement in (
            {" Review_ Buttons Style": 99},
            {"Tooltip Position": [0]},
            {"Color_ Again": "red;display:none"},
        ):
            with self.assertRaises(ValueError):
                validate("advanced_review", copy.deepcopy(conf) | replacement)


class ChineseSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from aqt.qt import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_all_visible_setting_captions_have_chinese_labels(self):
        from aqt.builtin_features.review_tools.config import FEATURES
        from aqt.builtin_features.review_tools.i18n import caption
        from aqt.builtin_features.review_tools.settings import MANAGED

        for feature in FEATURES:
            if feature == "pace_graph":
                continue
            for key in defaults(feature):
                if key not in MANAGED:
                    self.assertRegex(caption(key), r"[\u4e00-\u9fff]", key)

    def test_chinese_editors_preserve_palette_values_and_unknown_fields(self):
        from aqt.builtin_features.review_tools.structured_settings import (
            StructuredEditor,
        )

        original = {"4 answers": ["red", "darkorange", "green", "blue"]}
        editor = StructuredEditor("colours", original)
        self.assertEqual(editor.value(), original)
        extended = original | {"future-palette": ["#112233"]}
        editor.set_value(extended)
        self.assertEqual(editor.value(), extended)
        editor.deleteLater()

    def test_drag_order_changes_keep_the_original_category_ids(self):
        from aqt.builtin_features.review_tools.structured_settings import (
            StructuredEditor,
        )

        editor = StructuredEditor("categoryOrder", ["due", "rating", "fsrs"])
        item = editor.order.takeItem(0)
        editor.order.insertItem(2, item)
        self.assertEqual(editor.value(), ["rating", "fsrs", "due"])
        self.assertEqual(editor.order.item(0).text(), "评分")
        editor.deleteLater()

    def test_chinese_stats_locale_covers_all_original_message_keys(self):
        from aqt.builtin_features.review_tools.search_stats import ROOT

        def keys(language):
            content = (ROOT / "locale" / f"{language}.ftl").read_text(encoding="utf8")
            return set(re.findall(r"^([A-Za-z][\w-]*)\s*=", content, re.M))

        self.assertFalse(keys("en_GB") - keys("zh_CN"))
