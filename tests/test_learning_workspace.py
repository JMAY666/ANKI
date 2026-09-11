"""Observable report, privacy, scheduling and recovery contracts on synthetic data."""

import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from anki.collection import Collection
from anki.lang import set_lang
from aqt.builtin_features.learning import metrics, policy, provider, service
from aqt.builtin_features.learning.storage import LearningStore
from aqt.builtin_features.protected_secrets import read_secrets, write_secrets


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "snapshot_id": "sample",
            "parameters": {"new_per_day": 20},
            "evidence": {"backlog": 15},
        }
        self.settings = policy.DEFAULT_SETTINGS | {"new_limit": 30}
        self.report = {
            "snapshot_id": "sample",
            "decision": "propose",
            "summary": "积压增加，建议减少新增负担。",
            "observations": ["有积压"],
            "inferences": ["不能据此推断专注度"],
            "changes": [
                {
                    "parameter": "new_per_day",
                    "before": 20,
                    "after": 18,
                    "reason": "减少新增",
                    "evidence": ["backlog"],
                }
            ],
        }

    def test_accepts_bounded_proposal_and_explicit_keep(self):
        self.assertEqual(
            policy.validate_report(self.report, self.snapshot, self.settings),
            self.report,
        )
        self.report.update(decision="keep", changes=[])
        self.assertEqual(
            policy.validate_report(self.report, self.snapshot, self.settings)[
                "changes"
            ],
            [],
        )

    def test_rejects_invalid_proposals_instead_of_clamping(self):
        for field, value in (
            ("after", 17),
            ("after", 18.5),
            ("after", True),
            ("before", 21),
            ("parameter", "desired_retention"),
            ("evidence", ["invented_metric"]),
        ):
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(self.report)
                report["changes"][0][field] = value
                with self.assertRaises(ValueError):
                    policy.validate_report(report, self.snapshot, self.settings)

    def test_rejects_mismatched_snapshot_unknown_fields_and_automatic_mode(self):
        for update in (
            {"snapshot_id": "other"},
            {"sql": "invalid"},
            {"decision": "keep"},
        ):
            with self.assertRaises(ValueError):
                policy.validate_report(
                    self.report | update, self.snapshot, self.settings
                )
        with self.assertRaises(ValueError):
            policy.validate_settings({"mode": "automatic"})
        with self.assertRaises(ValueError):
            policy.validate_settings({"monthly_budget": float("nan")})
        with self.assertRaises(ValueError):
            policy.validate_settings({"daily_enabled": True})

    def test_counts_repeat_ratings_separately_and_excludes_preview_and_manual(self):
        rows = [
            [1000, 1, 1, 1, 1, 2500, 60000, 1],
            [2000, 1, 3, 1, 1, 2500, 1000, 1],
            [3000, 2, 0, 1, 1, 2500, 0, 4],
            [4000, 3, 3, 1, 1, 0, 1000, 3],
        ]
        result = metrics.summarize(rows, 86400)
        self.assertEqual(
            (
                result["reviews"],
                result["unique_cards"],
                result["recorded_seconds"],
                result["true_retention"],
            ),
            (2, 1, 61, 0.5),
        )
        self.assertIsNone(metrics.summarize([], 86400)["true_retention"])

    def test_provider_requires_complete_response_and_usage(self):
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(self.report)},
                }
            ],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 1000},
            "model": "deepseek-flash",
        }
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return io.BytesIO(json.dumps(response).encode())

        result, usage = provider.request_report({}, "synthetic-key", opener)
        self.assertEqual(result, self.report)
        self.assertAlmostEqual(usage["estimated_cost"], 0.018)
        self.assertFalse(json.loads(captured[0][0].data)["stream"])
        response["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(provider.ProviderError):
            provider.request_report({}, "synthetic-key", opener)
        with self.assertRaises(provider.ProviderError):
            provider.request_report({}, "", opener)
        with self.assertRaisesRegex(provider.ProviderError, "格式无效"):
            provider.request_report({}, "synthetic\nsecret", opener)

    def test_effect_review_separates_insufficient_observation_and_material_decline(
        self,
    ):
        before = {
            "summary": {
                "long_reviews": 1000,
                "true_retention": 0.93,
                "recorded_seconds": 2000,
                "active_days": 7,
            },
            "cards": {"backlog": 1},
        }
        after = copy.deepcopy(before)
        after["summary"]["true_retention"] = 0.8
        self.assertFalse(policy.evaluate_effect(before, after, 5, 60)["blocked"])
        self.assertTrue(policy.evaluate_effect(before, after, 21, 60)["blocked"])
        after["summary"]["long_reviews"] = 20
        self.assertFalse(policy.evaluate_effect(before, after, 21, 60)["blocked"])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LearningStore(Path(self.temp.name))
        self.now = 1789084800

    def test_daily_claim_deduplicates_and_bounds_retries(self):
        key = self.store.claim("2026-09-10", "scope", 5, self.now)
        self.assertIsNone(self.store.claim("2026-09-10", "scope", 5, self.now))
        with self.store.connection() as db:
            db.execute("UPDATE reports SET status='retry',updated=?", (self.now,))
        self.assertIsNone(self.store.claim("2026-09-10", "scope", 5, self.now + 899))
        self.assertEqual(
            self.store.claim("2026-09-10", "scope", 5, self.now + 901), key
        )
        with self.store.connection() as db:
            db.execute(
                "UPDATE reports SET status='retry',attempts=3,updated=?", (self.now,)
            )
        self.assertIsNone(self.store.claim("2026-09-10", "scope", 5, self.now + 1000))
        self.assertEqual(LearningStore(Path(self.temp.name)).report(key)["attempts"], 3)

    def test_budget_and_pending_actions_prevent_duplicate_writes(self):
        key = self.store.claim("2026-09-10", "scope", 0.15, self.now)
        with self.assertRaises(ValueError):
            self.store.claim("2026-09-11", "scope", 0.15, self.now)
        self.store.pending_action(key, 1, None, 18, "reason", self.now)
        with self.assertRaises(ValueError):
            self.store.pending_action(key, 1, None, 18, "reason", self.now)

    def test_late_response_cannot_replace_new_attempt_and_cost_is_settled_once(self):
        key = self.store.claim("2026-09-10", "scope", 5, self.now)
        with self.store.connection() as db:
            db.execute("UPDATE reports SET status='interrupted' WHERE id=?", (key,))
        self.store.claim("2026-09-10", "scope", 5, self.now + 1, manual=True)
        self.store.finish(key, "ready", {"new": True}, cost=0.02, expected_attempt=2)
        self.store.finish(key, "ready", {"old": True}, cost=0.01, expected_attempt=1)
        self.assertEqual(json.loads(self.store.report(key)["snapshot"]), {"new": True})
        self.assertAlmostEqual(self.store.report(key)["cost"], 0.03)
        self.store.finish(key, "ready", {"old": True}, cost=0.01, expected_attempt=1)
        self.assertAlmostEqual(self.store.report(key)["cost"], 0.03)

    def test_static_web_runtime_rejects_mixed_build_identifiers(self):
        source = Path(__file__).resolve().parents[1] / "scripts/verify_web_runtime.py"
        spec = importlib.util.spec_from_file_location("verify_web_runtime", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = Path(self.temp.name) / "web"
        root.mkdir()
        (root / "_app").mkdir()
        (root / "index.html").write_text(
            'window.__sveltekit_a1={}; import("./_app/start.mjs")'
        )
        client = root / "_app/start.mjs"
        client.write_text("globalThis.__sveltekit_a1.data")
        self.assertEqual(module.verify(root), 1)
        client.write_text("globalThis.__sveltekit_b2.data")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            module.verify(root)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_credentials_are_encrypted_and_plaintext_legacy_is_readable(self):
        path = Path(self.temp.name) / "secrets.json"
        path.write_text('{"deepseek":"synthetic-secret"}')
        values = read_secrets(path)
        write_secrets(path, values)
        self.assertNotIn("synthetic-secret", path.read_text())
        self.assertEqual(read_secrets(path), values)
        value = json.loads(path.read_text())
        value["payload"] = "invalid"
        path.write_text(json.dumps(value))
        with self.assertRaises(Exception):
            read_secrets(path)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        set_lang("en_US")
        self.col = Collection(str(Path(self.temp.name) / "collection.anki2"))
        self.addCleanup(self.col.close)
        self.store = LearningStore(Path(self.temp.name))
        self.did = self.col.decks.id("Private deck name")
        self.other = self.col.decks.id("Unrelated")
        model = self.col.models.by_name("Basic")
        for number in range(60):
            note = self.col.new_note(model)
            note["Front"] = f"PRIVATE CARD CONTENT {number}"
            self.col.add_note(note, self.did)
        self.cids = self.col.find_cards(metrics.scope_query(self.col, self.did, True))
        self.assertEqual(len(self.cids), 60)
        self.cutoff = int(self.col.sched.day_cutoff)
        self.now = self.cutoff - 100
        self.col.set_config("fsrs", True)
        self.col.decks.select(self.did)
        for day in range(2, 16):
            for offset in range(16):
                rid = (self.cutoff - day * policy.DAY + 100) * 1000 + offset
                cid = self.cids[((day - 2) * 16 + offset) % 60]
                self.col.db.execute(
                    "INSERT INTO revlog VALUES(?,?,?,?,?,?,?,?,?)",
                    rid,
                    cid,
                    -1,
                    1 if offset == 0 else 3,
                    15,
                    10,
                    2500,
                    2000,
                    1,
                )
        self.settings = policy.DEFAULT_SETTINGS | {
            "consent": True,
            "deck_id": int(self.did),
            "minutes": 60,
            "new_limit": 30,
            "enabled_since": self.now - 15 * policy.DAY,
        }
        self.store.save_settings(self.settings)

    def create_report(self):
        snapshot = metrics.collect_snapshot(self.col, self.did, True, self.now)
        self.assertTrue(snapshot["quality"]["eligible"])
        before = snapshot["parameters"]["new_per_day"]
        report = {
            "snapshot_id": snapshot["snapshot_id"],
            "decision": "propose",
            "summary": "减少新增",
            "observations": [],
            "inferences": [],
            "changes": [
                {
                    "parameter": "new_per_day",
                    "before": before,
                    "after": before - 2,
                    "reason": "依据合成学习负担",
                    "evidence": ["backlog"],
                }
            ],
        }
        key = self.store.claim(snapshot["day"], "scope", 5, self.now)
        self.store.finish(
            key,
            "ready",
            snapshot,
            {"content": report, "model": "test", "estimated_cost": 0},
            cost=0,
        )
        return key, snapshot

    def test_public_data_contains_no_card_content_names_or_identifiers(self):
        _, snapshot = self.create_report()
        serialized = json.dumps(metrics.public_payload(snapshot, self.settings))
        for forbidden in (
            "PRIVATE CARD CONTENT",
            "Private deck name",
            str(self.did),
            str(self.cids[0]),
            "preset_id",
            "created_at",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(snapshot["summary"]["reviews"], 7 * 16)

    def test_filtered_deck_and_original_deck_match_native_search_scope(self):
        filtered = self.col.decks.new_filtered("Filtered")
        card = self.col.get_card(self.cids[0])
        card.odid, card.did, card.odue = self.did, filtered, card.due
        self.col.update_card(card)
        for did in (self.did, filtered):
            snapshot = metrics.collect_snapshot(self.col, did, True, self.now)
            self.assertEqual(
                snapshot["cards"]["total"],
                len(self.col.find_cards(metrics.scope_query(self.col, did, True))),
            )

    def test_confirm_and_revert_preserve_cards_reviews_other_limits_and_preset(self):
        key, snapshot = self.create_report()
        cards = self.col.db.all("SELECT * FROM cards ORDER BY id")
        reviews = self.col.db.all("SELECT * FROM revlog ORDER BY id")
        other = metrics.parameters(self.col, self.other)
        service.apply_confirmed(self.col, self.store, key, self.now)
        self.assertEqual(metrics.parameters(self.col, self.did)["new_per_day"], 18)
        self.assertEqual(self.col.db.all("SELECT * FROM cards ORDER BY id"), cards)
        self.assertEqual(self.col.db.all("SELECT * FROM revlog ORDER BY id"), reviews)
        self.assertEqual(metrics.parameters(self.col, self.other), other)
        with self.assertRaises(ValueError):
            service.apply_confirmed(self.col, self.store, key, self.now)
        service.revert_action(self.col, self.store, self.store.actions()[0]["id"])
        self.assertEqual(
            metrics.parameters(self.col, self.did)["override"],
            snapshot["parameters"]["override"],
        )
        self.assertEqual(self.col.db.all("SELECT * FROM revlog ORDER BY id"), reviews)

    def test_new_review_invalidates_report_even_outside_closed_analysis_window(self):
        key, _ = self.create_report()
        self.col.db.execute(
            "INSERT INTO revlog VALUES(?,?,?,?,?,?,?,?,?)",
            self.now * 1000,
            self.cids[0],
            -1,
            3,
            20,
            15,
            2500,
            2000,
            1,
        )
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.apply_confirmed(self.col, self.store, key, self.now)
        self.assertEqual(metrics.parameters(self.col, self.did)["new_per_day"], 20)
        self.assertEqual(self.store.actions(), [])

    def test_session_counts_follow_native_undo_without_deleting_audit_events(self):
        rid = self.col.db.scalar("SELECT MAX(id) FROM revlog")
        self.assertEqual(metrics.session_summary(self.col, [rid, rid])["reviews"], 1)
        self.col.db.execute("DELETE FROM revlog WHERE id=?", rid)
        self.assertEqual(metrics.session_summary(self.col, [rid])["reviews"], 0)

    def test_recovery_does_not_reapply_or_overwrite_later_manual_settings(self):
        key, _ = self.create_report()
        service.apply_confirmed(self.col, self.store, key, self.now)
        service.set_new_override(self.col, self.did, 12)
        service.reconcile(self.col, self.store)
        self.assertEqual(self.store.actions()[0]["status"], "conflict")
        self.assertEqual(metrics.parameters(self.col, self.did)["new_per_day"], 12)
        with self.assertRaises(ValueError):
            service.revert_action(self.col, self.store, self.store.actions()[0]["id"])
