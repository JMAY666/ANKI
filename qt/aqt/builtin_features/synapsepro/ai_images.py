"""In-memory image attachments and an Anki-window-only region selector."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from aqt.qt import (
    QBuffer,
    QByteArray,
    QColor,
    QDialog,
    QDialogButtonBox,
    QImage,
    QImageReader,
    QIODevice,
    QLabel,
    QPainter,
    QPen,
    QPixmap,
    QPlainTextEdit,
    QPoint,
    QRect,
    QSize,
    Qt,
    QVBoxLayout,
    QWidget,
)

from .locales import _

MAX_IMAGES = 4
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_EDGE = 2048


def prepare_image(image: QImage, name: str = "screenshot.png") -> dict[str, Any]:
    if image.isNull() or image.width() * image.height() > MAX_PIXELS:
        raise ValueError(_("The image is too large or could not be decoded."))
    if max(image.width(), image.height()) > MAX_EDGE:
        image = image.scaled(
            MAX_EDGE,
            MAX_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    image.setDevicePixelRatio(1)
    # Copy pixels to a fresh image, excluding EXIF/text metadata from imports.
    clean = QImage(image.size(), QImage.Format.Format_ARGB32)
    clean.fill(Qt.GlobalColor.transparent)
    painter = QPainter(clean)
    painter.drawImage(0, 0, image)
    painter.end()
    image = clean
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError(_("The image could not be decoded."))
    mime = "image/png"
    if data.size() > MAX_IMAGE_BYTES:
        # Flatten transparency on white before JPEG encoding. No source file or
        # metadata is copied into the attachment or the collection's media.
        opaque = QImage(image.size(), QImage.Format.Format_RGB32)
        opaque.fill(QColor("white"))
        painter = QPainter(opaque)
        painter.drawImage(0, 0, image)
        painter.end()
        buffer.close()
        data.clear()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not opaque.save(buffer, "JPEG", 85):
            raise ValueError(_("The image could not be decoded."))
        mime = "image/jpeg"
    buffer.close()
    if data.size() > MAX_IMAGE_BYTES:
        raise ValueError(_("The image is too large or could not be decoded."))
    return {
        "name": Path(name).stem[:80] + (".png" if mime == "image/png" else ".jpg"),
        "dataUrl": f"data:{mime};base64,"
        + base64.b64encode(bytes(data)).decode("ascii"),
        "width": image.width(),
        "height": image.height(),
    }


def read_image(path: str) -> dict[str, Any]:
    if not 0 < Path(path).stat().st_size <= MAX_FILE_BYTES:
        raise ValueError(_("The image must be smaller than 20 MB."))
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if bytes(reader.format()).lower() not in (b"png", b"jpg", b"jpeg", b"webp"):
        raise ValueError(_("Please choose a valid PNG, JPEG or WebP image."))
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        raise ValueError(_("The image is too large or could not be decoded."))
    if reader.supportsAnimation() and reader.imageCount() != 1:
        raise ValueError(_("Animated images are not supported."))
    if max(size.width(), size.height()) > MAX_EDGE:
        reader.setScaledSize(
            size.scaled(QSize(MAX_EDGE, MAX_EDGE), Qt.AspectRatioMode.KeepAspectRatio)
        )
    return prepare_image(reader.read(), Path(path).name)


def message_content(
    text: str, images: list[dict[str, Any]]
) -> str | list[dict[str, Any]]:
    if not images:
        return text
    return [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": item["dataUrl"]}} for item in images
    ]


def image_parts(content: Any) -> list[dict[str, Any]]:
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def split_data_url(url: str) -> tuple[str, str]:
    header, data = url.split(",", 1)
    return header.removeprefix("data:").removesuffix(";base64"), data


def gemini_parts(content: Any) -> list[dict[str, Any]]:
    parts = []
    for part in image_parts(content):
        if part["type"] == "text":
            parts.append({"text": part["text"]})
        else:
            mime, data = split_data_url(part["image_url"]["url"])
            parts.append({"inlineData": {"mimeType": mime, "data": data}})
    return parts


def anthropic_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if part["type"] == "text":
            parts.append(dict(part))
        else:
            mime, data = split_data_url(part["image_url"]["url"])
            parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                }
            )
    return parts


def ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    parts = image_parts(message["content"])
    result = {
        "role": message["role"],
        "content": "\n".join(part["text"] for part in parts if part["type"] == "text"),
    }
    images = [
        split_data_url(part["image_url"]["url"])[1]
        for part in parts
        if part["type"] == "image_url"
    ]
    if images:
        result["images"] = images
    return result


def crop_region(snapshot: QPixmap, region: QRect, logical_size: QSize) -> QImage:
    """Map logical Qt coordinates to capture pixels, including mixed DPI."""
    bounded = region.normalized().intersected(QRect(QPoint(), logical_size))
    if bounded.width() < 4 or bounded.height() < 4:
        return QImage()
    sx, sy = (
        snapshot.width() / logical_size.width(),
        snapshot.height() / logical_size.height(),
    )
    left, top = round(bounded.x() * sx), round(bounded.y() * sy)
    right, bottom = (
        round((bounded.x() + bounded.width()) * sx),
        round((bounded.y() + bounded.height()) * sy),
    )
    return snapshot.copy(QRect(left, top, right - left, bottom - top)).toImage()


class RegionCapture(QDialog):
    def __init__(self, parent: QWidget, snapshot: QPixmap) -> None:
        super().__init__(
            parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("aiRegionCapture")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setGeometry(QRect(parent.mapToGlobal(QPoint()), parent.size()))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.snapshot = snapshot
        self.origin: QPoint | None = None
        self.selection = QRect()
        self.image = QImage()
        self.hint = QLabel(_("Drag to capture inside Anki · Esc to cancel"), self)
        self.hint.setStyleSheet(
            "background:#20252b;color:white;padding:10px;border-radius:6px;"
        )
        self.hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hint.adjustSize()
        self.hint.move(max(0, (self.width() - self.hint.width()) // 2), 12)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 105))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawPixmap(self.rect(), self.snapshot)
            painter.restore()
            painter.setPen(QPen(QColor("#62b6ff"), 2))
            painter.drawRect(self.selection.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.reject()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QRect()
            self.hint.hide()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.origin is not None:
            self.selection = self._selection_to(event.position().toPoint())
            self.update()

    def _selection_to(self, point: QPoint) -> QRect:
        return QRect(
            min(self.origin.x(), point.x()),
            min(self.origin.y(), point.y()),
            abs(self.origin.x() - point.x()),
            abs(self.origin.y() - point.y()),
        ).intersected(self.rect())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.selection = self._selection_to(event.position().toPoint())
        self.origin = None
        self.image = crop_region(self.snapshot, self.selection, self.size())
        if not self.image.isNull():
            self.accept()


class ScreenshotQuestion(QDialog):
    """Compose before showing the right dock; settings transfers the same draft."""

    SETTINGS = 2

    def __init__(self, parent: QWidget, image: QImage, destination: str) -> None:
        super().__init__(parent)
        self.setObjectName("aiScreenshotQuestion")
        self.setWindowTitle(_("Screenshot question"))
        self.resize(580, 470)
        layout = QVBoxLayout(self)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                540,
                250,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(preview)
        layout.addWidget(QLabel(_("Default AI") + ": " + destination))
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText(_("Ask about this image…"))
        layout.addWidget(self.question)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        settings = buttons.addButton(
            _("Default AI…"), QDialogButtonBox.ButtonRole.ActionRole
        )
        settings.clicked.connect(lambda: self.done(self.SETTINGS))
        send = buttons.addButton(_("Send"), QDialogButtonBox.ButtonRole.AcceptRole)
        send.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.question.setFocus()
