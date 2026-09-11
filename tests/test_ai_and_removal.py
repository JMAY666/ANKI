"""Offline regression tests. Only synthetic credentials/collections are used."""
import ast
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("synapse_test")
package.__path__ = [str(ROOT / "qt/aqt/builtin_features/synapsepro")]
sys.modules[package.__name__] = package
ai = importlib.import_module("synapse_test.ai_assistant")


class Collection:
    def __init__(self):
        self.values = {}

    def get_config(self, key, default=None):
        return self.values.get(key, default)

    def set_config(self, key, value):
        self.values[key] = value

    def remove_config(self, key):
        self.values.pop(key, None)


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class AIRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.col = Collection()
        mw = types.SimpleNamespace(col=self.col, pm=types.SimpleNamespace(profileFolder=lambda: self.temp.name))
        self.patch = patch.object(ai, "mw", mw)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        ai._conversation.clear()

    def test_deepseek_key_is_profile_local_and_old_settings_survive(self):
        ai._save_settings_dict(dict(provider="openai", apiKey="synthetic-openai", model="existing-custom-model"))
        ai._save_settings_dict(dict(provider="deepseek", apiKey="synthetic-deepseek", model="custom-deepseek-model"))
        self.assertEqual(ai._load_settings("deepseek")["model"], "custom-deepseek-model")
        self.assertEqual(ai._load_settings("openai")["model"], "existing-custom-model")
        self.assertEqual(ai._load_settings("openai")["apiKey"], "synthetic-openai")
        self.assertEqual(ai._load_settings("deepseek")["apiKey"], "synthetic-deepseek")
        self.assertNotIn(ai.CK_KEY_DEEPSEEK, self.col.values)
        self.assertNotIn("synthetic-deepseek", json.dumps(self.col.values))
        secrets = json.loads(Path(ai._secret_path()).read_text())
        from aqt.builtin_features.protected_secrets import read_secrets

        if ai.os.name == "nt":
            self.assertNotIn("synthetic-deepseek", json.dumps(secrets))
        self.assertEqual(read_secrets(Path(ai._secret_path()))[ai.CK_KEY_DEEPSEEK], "synthetic-deepseek")
        ai._save_settings_dict(dict(provider="deepseek", apiKey="", model=""))
        self.assertFalse(ai._load_settings("deepseek")["isConfigured"])
        self.assertEqual(ai._load_settings("deepseek")["model"], "deepseek-flash")
        self.assertEqual(ai._load_settings("openai")["apiKey"], "synthetic-openai")

    def test_actual_deepseek_request_and_stream(self):
        stream = (b'data: {"choices":[{"delta":{"content":"Synthetic "}}]}\n'
                  b'data: {"choices":[{"delta":{"content":"answer"}}]}\n'
                  b'data: [DONE]\n')
        with patch.object(ai.threading, "Thread", ImmediateThread), patch.object(ai.urllib.request, "urlopen", return_value=io.BytesIO(stream)) as call, patch.object(ai, "_js_on_main") as js:
            ai._run_api_in_thread(dict(provider="deepseek", apiKey="synthetic-key", model="custom-model"), [{"role": "user", "content": "Synthetic question"}])
        req = call.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer synthetic-key")
        payload = json.loads(req.data)
        self.assertEqual(payload["model"], "custom-model")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(ai._conversation[-1]["content"], "Synthetic answer")
        self.assertTrue(any("finalizeResponse" in c.args[0] for c in js.call_args_list))

    def test_deepseek_401_reports_error_without_success(self):
        error = HTTPError("https://api.deepseek.com/chat/completions", 401, "Unauthorized", {}, io.BytesIO(b'{}'))
        with patch.object(ai.threading, "Thread", ImmediateThread), patch.object(ai.urllib.request, "urlopen", side_effect=error), patch.object(ai, "_js_on_main") as js:
            ai._run_api_in_thread(dict(provider="deepseek", apiKey="synthetic-key", model="deepseek-flash"), [])
        calls = [c.args[0] for c in js.call_args_list]
        self.assertTrue(any("receiveResponse" in c and "true" in c for c in calls))
        self.assertFalse(any("finalizeResponse" in c for c in calls))
        self.assertFalse(ai._conversation)

    def test_existing_provider_routes_unchanged(self):
        providers = {
            "openai": ("_stream_openai_compat", "https://api.openai.com/v1/chat/completions"),
            "openrouter": ("_stream_openai_compat", "https://openrouter.ai/api/v1/chat/completions"),
            "llamaserver": ("_stream_openai_compat", "http://localhost:8080/v1/chat/completions"),
            "gemini": ("_stream_gemini", None),
            "anthropic": ("_stream_anthropic", None),
            "ollama": ("_stream_ollama", None),
        }
        for provider, (function, url) in providers.items():
            with self.subTest(provider=provider), patch.object(ai.threading, "Thread", ImmediateThread), patch.object(ai, function) as stream, patch.object(ai, "_js_on_main"):
                ai._run_api_in_thread(dict(provider=provider, apiKey="synthetic", model="existing-model"), [])
                stream.assert_called_once()
                if url:
                    self.assertEqual(stream.call_args.args[0], url)
                    self.assertNotIn("extra_body", stream.call_args.kwargs)

    def test_missing_key_does_not_send(self):
        ai._save_settings_dict(dict(provider="deepseek", apiKey="", model="deepseek-flash"))
        with patch.object(ai, "_run_api_in_thread") as stream, patch.object(ai, "_run_js") as js:
            ai._action_send_message({"text": "Synthetic question"})
            stream.assert_not_called()
            self.assertIn("No API key", js.call_args.args[0])


class RemovalRegression(unittest.TestCase):
    def test_exclusive_files_and_imports_removed(self):
        retired = {"website_sidebar", "notebook_sidebar", "mindmap_sidebar", "embedded_window"}
        for name in retired:
            self.assertFalse((ROOT / "qt/aqt/builtin_features/synapsepro" / (name + ".py")).exists())
        self.assertFalse(any((ROOT / "qt/aqt/builtin_features/synapsepro/web_notebook").rglob("*.js")))
        self.assertFalse((ROOT / "qt/aqt/builtin_features/synapsepro/index.html").exists())
        for p in (ROOT / "qt/aqt/builtin_features/synapsepro").glob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, retired, p.name)
                    self.assertFalse(retired & {n.name for n in node.names}, p.name)
        self.assertTrue((ROOT / "qt/aqt/builtin_features/synapsepro/chat_ui.html").exists())
        self.assertTrue((ROOT / "qt/aqt/builtin_features/synapsepro/media/wordcloud2.min.js").exists())

    def test_removed_controls_and_shortcuts_not_registered(self):
        constants = importlib.import_module("synapse_test.constants")
        for key in ("website_viewer_enabled", "notebook_enabled", "mindmap_enabled"):
            self.assertNotIn(key, constants.SIDEBAR_SHORTCUT_KEYS)
            for name in ("__init__.py", "launcher_widget.py", "sidebar_shortcuts.py", "settings_dialog.py", "web_settings_dialog.py", "settings_web/settings.html"):
                self.assertNotIn(key, (ROOT / "qt/aqt/builtin_features/synapsepro" / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
