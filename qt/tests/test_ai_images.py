# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Image requests, draft recovery, and capture boundaries, with synthetic data."""

from __future__ import annotations

import base64
import importlib
import io
import json
import sys
import types
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PyQt6.QtTest import QTest

from aqt.qt import (
    QApplication,
    QColor,
    QImage,
    QPixmap,
    QPoint,
    QRect,
    QSize,
    Qt,
    QWidget,
)

package = types.ModuleType("synthetic_ai_images")
package.__path__ = [
    str(Path(__file__).resolve().parents[1] / "aqt/builtin_features/synapsepro")
]
sys.modules[package.__name__] = package
ai = importlib.import_module(package.__name__ + ".ai_assistant")
images = importlib.import_module(package.__name__ + ".ai_images")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(
        ["ai-images", "-platform", "offscreen"]
    )


@pytest.fixture
def state(monkeypatch, app):
    config = {
        ai.CK_PROVIDER: "deepseek",
        ai.CK_MODEL_DEEPSEEK: "deepseek-flash",
        ai.CK_KEY_DEEPSEEK: "synthetic-key",
    }
    monkeypatch.setattr(
        ai, "_cfg_get", lambda key, default="": config.get(key, default)
    )
    monkeypatch.setattr(ai, "_cfg_set", config.__setitem__)
    monkeypatch.setattr(ai, "_detect_night_mode", lambda: False)
    monkeypatch.setattr(ai, "_get_theme_accent", lambda dark: "#336699")
    monkeypatch.setattr(ai, "tooltip", lambda *args: None)
    js = []
    monkeypatch.setattr(ai, "_run_js", js.append)
    monkeypatch.setattr(
        ai, "_js_on_main", lambda code, generation=None: js.append(code)
    )
    monkeypatch.setattr(ai.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        ai.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("Unexpected network request"),
    )
    ai._session_generation += 1
    ai._request_busy = False
    ai._page_ready = True
    ai._attachments.clear()
    ai._draft_image_ids.clear()
    ai._reset_conversation()
    yield config, js
    ai._attachments.clear()
    ai._draft_image_ids.clear()
    ai._conversation.clear()
    ai._request_busy = False


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def attachment(app):
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("#197340"))
    return images.prepare_image(image, "synthetic.png")


@pytest.mark.parametrize(
    "provider",
    [
        "openai",
        "deepseek",
        "openrouter",
        "llamaserver",
        "gemini",
        "anthropic",
        "ollama",
    ],
)
def test_text_and_pixels_reach_each_provider_in_one_request(
    state, attachment, monkeypatch, provider
):
    requests = []

    def respond(request, **kwargs):
        requests.append(json.loads(request.data))
        stream = {
            "gemini": b'data: {"candidates":[{"content":{"parts":[{"text":"Answer"}]}}]}\n',
            "anthropic": b'data: {"type":"content_block_delta","delta":{"text":"Answer"}}\n',
            "ollama": b'{"message":{"content":"Answer"},"done":true}\n',
        }.get(provider, b'data: {"choices":[{"delta":{"content":"Answer"}}]}\n')
        return io.BytesIO(stream)

    monkeypatch.setattr(ai.urllib.request, "urlopen", respond)
    monkeypatch.setattr(
        ai,
        "_load_settings",
        lambda: {
            "provider": provider,
            "model": "deepseek-flash"
            if provider == "deepseek"
            else "synthetic-vision-model",
            "apiKey": "synthetic-key",
        },
    )
    key = ai._add_attachment(attachment)
    ai._action_send_message({"text": "解释绿色区域", "images": [key]})
    assert len(requests) == 1
    payload = requests[0]
    encoded = attachment["dataUrl"].split(",", 1)[1]
    if provider == "gemini":
        parts = payload["contents"][-1]["parts"]
        assert parts[0] == {"text": "解释绿色区域"}
        assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": encoded}}
    elif provider == "anthropic":
        parts = payload["messages"][-1]["content"]
        assert parts[0] == {"type": "text", "text": "解释绿色区域"}
        assert parts[1]["source"] == {
            "type": "base64",
            "media_type": "image/png",
            "data": encoded,
        }
    elif provider == "ollama":
        assert payload["messages"][-1] == {
            "role": "user",
            "content": "解释绿色区域",
            "images": [encoded],
        }
    else:
        assert payload["messages"][-1]["content"] == [
            {"type": "text", "text": "解释绿色区域"},
            {"type": "image_url", "image_url": {"url": attachment["dataUrl"]}},
        ]
    assert QImage.fromData(base64.b64decode(encoded)).pixelColor(1, 1) == QColor(
        "#197340"
    )
    assert ai._conversation[-1] == {"role": "assistant", "content": "Answer"}
    assert not ai._request_busy


def test_follow_up_retains_image_history_and_card_context_is_request_only(
    state, attachment, monkeypatch
):
    requests = []
    monkeypatch.setattr(ai, "_get_card_content", lambda: "synthetic private card")
    monkeypatch.setattr(
        ai,
        "_run_api_in_thread",
        lambda settings, messages, ids: requests.append(messages),
    )
    key = ai._add_attachment(attachment)
    ai._action_send_message(
        {"text": "Compare", "images": [key], "useCardContext": True}
    )
    assert "synthetic private card" in requests[0][-1]["content"][0]["text"]
    assert "synthetic private card" not in json.dumps(ai._conversation)
    assert (
        ai._conversation[-1]["content"][1]["image_url"]["url"] == attachment["dataUrl"]
    )
    ai._request_busy = False
    ai._action_release_images({"images": [key]})
    ai._action_send_message({"text": "What is the color?"})
    assert requests[-1][-2]["content"][1]["image_url"]["url"] == attachment["dataUrl"]
    assert requests[-1][-1]["content"] == "What is the color?"


@pytest.mark.parametrize(
    "setting,value",
    [
        (ai.CK_KEY_DEEPSEEK, ""),
        (ai.CK_MODEL_DEEPSEEK, ""),
        (ai.CK_MODEL_DEEPSEEK, "deepseek-v4-pro"),
    ],
)
def test_missing_configuration_or_text_model_preserves_image_draft(
    state, attachment, setting, value
):
    config, js = state
    config[setting] = value
    key = ai._add_attachment(attachment)
    before = list(ai._conversation)
    ai._action_send_message({"text": "Keep this draft", "images": [key]})
    assert ai._conversation == before
    assert ai._attachments[key]["dataUrl"] == attachment["dataUrl"]
    assert ai._draft_image_ids == [key]
    assert not ai._request_busy
    assert any("receiveResponse" in call for call in js)


def test_failed_stream_rolls_back_history_and_keeps_retry_image(
    state, attachment, monkeypatch
):
    def fail(*args, **kwargs):
        raise HTTPError(
            "https://example.invalid", 400, "synthetic failure", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(ai.urllib.request, "urlopen", fail)
    key = ai._add_attachment(attachment)
    before = list(ai._conversation)
    ai._action_send_message({"text": "Retry me", "images": [key]})
    assert ai._conversation == before
    assert key in ai._attachments
    assert not ai._request_busy
    assert not any("completeSend" in call for call in state[1])


@pytest.mark.parametrize("provider", ["deepseek", "gemini", "anthropic", "ollama"])
def test_stream_error_event_keeps_images_available_for_retry(
    state, attachment, monkeypatch, provider
):
    event = b'{"error":{"message":"Synthetic stream failure"}}\n'
    if provider != "ollama":
        event = b"data: " + event
    monkeypatch.setattr(ai.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(event))
    monkeypatch.setattr(
        ai,
        "_load_settings",
        lambda: {
            "provider": provider,
            "model": "synthetic-model",
            "apiKey": "synthetic-key",
        },
    )
    key = ai._add_attachment(attachment)
    before = list(ai._conversation)
    ai._action_send_message({"text": "Keep failed stream draft", "images": [key]})
    assert ai._conversation == before
    assert key in ai._attachments
    assert not any("completeSend" in call for call in state[1])
    assert any("receiveResponse" in call for call in state[1])


def test_image_only_message_gets_a_prompt_and_invalid_ids_do_not_send(
    state, attachment, monkeypatch
):
    requests = []
    monkeypatch.setattr(ai, "_run_api_in_thread", lambda *args: requests.append(args))
    ai._action_send_message({"text": "Question", "images": ["deleted"]})
    assert requests == []
    key = ai._add_attachment(attachment)
    ai._action_send_message({"text": "", "images": [key]})
    assert requests[0][1][-1]["content"][0]["text"]
    ai._action_send_message({"text": "double click", "images": [key]})
    assert len(requests) == 1


def test_remove_cancel_and_clear_never_upload(state, attachment, monkeypatch):
    from aqt.qt import QFileDialog

    key = ai._add_attachment(attachment)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a: ([], ""))
    ai._action_choose_images({})
    assert ai._draft_image_ids == [key]
    ai._action_remove_image({"id": key})
    assert ai._draft_image_ids == []
    assert not ai._attachments
    ai._add_attachment(attachment)
    generation = ai._session_generation
    ai._action_clear_history()
    assert ai._session_generation > generation
    assert not ai._attachments


def test_long_conversation_keeps_complete_earlier_turns_and_latest_image(
    state, attachment
):
    for index in range(13):
        ai._conversation.extend(
            [
                {"role": "user", "content": f"Question {index}"},
                {"role": "assistant", "content": f"Answer {index}"},
            ]
        )
    latest = {"role": "user", "content": images.message_content("Latest", [attachment])}
    ai._conversation.append(latest)
    ai._trim_conversation()
    assert ai._conversation[1]["role"] == "user"
    assert len(ai._conversation) <= 25
    assert ai._conversation[-1] == latest


def test_cleared_request_cannot_repopulate_history(state, attachment, monkeypatch):
    def respond(*args, **kwargs):
        ai._action_clear_history()
        return io.BytesIO(b'data: {"choices":[{"delta":{"content":"Stale"}}]}\n')

    monkeypatch.setattr(ai.urllib.request, "urlopen", respond)
    key = ai._add_attachment(attachment)
    ai._action_send_message({"text": "Question", "images": [key]})
    assert ai._conversation == [ai._SYSTEM_MSG]
    assert not ai._attachments
    assert not ai._request_busy


def test_defaults_remember_each_custom_model_and_legacy_selection(state):
    config, _ = state
    config.update({ai.CK_PROVIDER: "openai", ai.CK_MODEL: "legacy-custom"})
    ai._save_settings_dict(
        {"provider": "gemini", "model": "gemini-custom", "apiKey": "synthetic-gemini"}
    )
    assert ai._load_settings()["provider"] == "gemini"
    assert ai._load_settings()["model"] == "gemini-custom"
    assert ai._load_settings("openai")["model"] == "legacy-custom"
    ai._save_settings_dict(
        {"provider": "openai", "model": "openai-custom", "apiKey": "synthetic-openai"}
    )
    assert ai._load_settings("gemini")["model"] == "gemini-custom"
    assert ai._load_settings("gemini")["apiKey"] == "synthetic-gemini"
    assert ai._load_settings()["model"] == "openai-custom"
    ai._save_settings_dict(
        {"provider": "gemini", "model": "", "apiKey": "synthetic-gemini"}
    )
    assert ai._load_settings()["model"] == ""
    assert ai._load_settings("openai")["model"] == "openai-custom"


def test_large_image_resizes_and_corrupt_or_oversized_files_are_rejected(app, tmp_path):
    image = QImage(3000, 1500, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    path = tmp_path / "synthetic.png"
    image.save(str(path))
    result = images.read_image(str(path))
    assert (result["width"], result["height"]) == (2048, 1024)
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        images.read_image(str(path))
    with path.open("wb") as stream:
        stream.truncate(images.MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError):
        images.read_image(str(path))


def test_imported_metadata_is_not_sent_with_pixels(app):
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    image.setText("Comment", "synthetic private metadata")
    result = images.prepare_image(image)
    decoded = QImage.fromData(base64.b64decode(result["dataUrl"].split(",", 1)[1]))
    assert decoded.size() == image.size()
    assert not decoded.textKeys()


@pytest.mark.parametrize("scale", [1, 1.25, 2])
def test_crop_maps_dpi_and_clamps_to_anki_window(app, scale):
    snapshot = QPixmap(round(400 * scale), round(200 * scale))
    snapshot.fill(QColor("#114488"))
    result = images.crop_region(snapshot, QRect(-40, 50, 140, 250), QSize(400, 200))
    assert result.size() == QSize(
        round(100 * scale), round(200 * scale) - round(50 * scale)
    )
    assert result.pixelColor(1, 1) == QColor("#114488")
    assert images.crop_region(snapshot, QRect(0, 0, 2, 2), QSize(400, 200)).isNull()


def test_region_selection_can_reverse_drag_and_escape_without_an_image(app):
    parent = QWidget()
    parent.resize(400, 240)
    parent.show()
    snapshot = QPixmap(400, 240)
    snapshot.fill(QColor("#114488"))
    selector = images.RegionCapture(parent, snapshot)
    selector.show()
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(200, 170))
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(30, 50))
    assert selector.result() == selector.DialogCode.Accepted
    assert selector.image.size() == QSize(170, 120)
    selector = images.RegionCapture(parent, snapshot)
    selector.show()
    QTest.keyClick(selector, Qt.Key.Key_Escape)
    assert selector.result() == selector.DialogCode.Rejected
    assert selector.image.isNull()
    parent.close()
