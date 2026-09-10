"""Search behavior against a real temporary Anki collection."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from anki.collection import Collection

spec = importlib.util.spec_from_file_location(
    "browser_scope", Path(__file__).resolve().parents[1] / "qt/aqt/builtin_features/synapsepro" / "browser_scope.py"
)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class DeckScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.col = Collection(str(Path(self.tmp.name) / "collection.anki2"))
        self.names = [
            '英语 "精选" * _ \\',
            '英语 "精选" * _ \\::子牌组',
            "其他",
            '英语 "精选" 任意 X \\',
        ]
        self.cards = []
        for index, name in enumerate(self.names):
            did = self.col.decks.id(name)
            note = self.col.new_note(self.col.models.by_name("Basic"))
            note["Front"] = f"card{index} apple"
            note["Back"] = "answer"
            self.col.add_note(note, did)
            self.cards.append(note.cards()[0].id)

    def tearDown(self):
        self.col.close()
        self.tmp.cleanup()

    def test_parent_includes_children_but_not_unrelated_decks(self):
        query = scope.deck_query(self.col, self.names[0])
        self.assertEqual(set(self.col.find_cards(query)), set(self.cards[:2]))

    def test_parent_only_handles_literal_quotes_wildcards_and_backslashes(self):
        query = scope.deck_query(self.col, self.names[0], False)
        self.assertEqual(self.col.find_cards(query), self.cards[:1])

    def test_content_or_search_stays_inside_selected_scope(self):
        query = scope.deck_query(self.col, self.names[0], True, "card1 OR card2")
        self.assertEqual(self.col.find_cards(query), self.cards[1:2])

    def test_all_decks_and_empty_results(self):
        self.assertEqual(
            set(self.col.find_cards(scope.deck_query(self.col, None))), set(self.cards)
        )
        self.assertEqual(
            self.col.find_cards(scope.deck_query(self.col, None, text="absent")), []
        )

    def test_latest_request_wins_even_when_old_request_finishes_last(self):
        gate = scope.RequestGate()
        old = gate.advance()
        new = gate.advance()
        self.assertTrue(gate.accepts(new))
        self.assertFalse(gate.accepts(old))
        gate.advance()  # closing or changing scope also invalidates completion
        self.assertFalse(gate.accepts(new))

    def test_bad_layout_preferences_are_not_restored(self):
        for value in (None, "300,400", [0, 400], [200], [200, 400, 500], [-1, 300]):
            self.assertFalse(scope.valid_sizes(value))
        self.assertTrue(scope.valid_sizes([360, 480]))


if __name__ == "__main__":
    unittest.main()
