# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PyQt6.QtTest import QTest

from aqt.builtin_features.learning.review_layout import ReviewLayout, layout_ratios
from aqt.qt import QApplication, QPoint, Qt, QWidget


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "bad",
        {"width": True, "height": float("nan")},
        {"width": -1, "height": 2},
    ],
)
def test_invalid_layout_uses_full_available_space(value: object) -> None:
    assert layout_ratios(value) == (1.0, 1.0)


def test_layout_restores_each_valid_dimension_independently() -> None:
    assert layout_ratios({"width": 0.6, "height": None}) == (0.6, 1.0)
    assert layout_ratios({"width": 0.8, "height": 0.75}) == (0.8, 0.75)


@pytest.fixture(scope="module")
def layout_app() -> QApplication:
    return QApplication.instance() or QApplication(
        ["review-layout-test", "-platform", "offscreen"]
    )


@pytest.fixture
def review_layout(
    layout_app: QApplication,
) -> Iterator[tuple[QApplication, ReviewLayout, list[dict[str, float]]]]:
    app = layout_app
    saved: list[dict[str, float]] = []
    bottom = QWidget()
    bottom.setFixedHeight(74)
    layout = ReviewLayout(QWidget(), bottom, saved.append)
    layout.resize(1000, 700)
    layout.viewport.set_reviewing(True)
    layout.show()
    app.processEvents()
    yield app, layout, saved
    layout.close()
    layout.deleteLater()
    app.processEvents()


def test_drag_saves_layout_and_window_resize_preserves_preference(
    review_layout,
) -> None:
    app, layout, saved = review_layout
    viewport = layout.viewport
    width = viewport.web.width()
    handle = viewport.handles["right"]
    start = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(handle, start + QPoint(-120, 0))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert viewport.web.width() < width
    assert len(saved) == 1
    preference = saved[0]
    layout.resize(520, 460)
    app.processEvents()
    assert viewport.rect().contains(viewport.web.geometry())
    layout.resize(1200, 850)
    app.processEvents()
    assert viewport.ratios == layout_ratios(preference)
    assert len(saved) == 1


def test_reset_and_leaving_review_restore_the_unrestricted_viewport(
    review_layout,
) -> None:
    app, layout, saved = review_layout
    viewport = layout.viewport
    viewport.load({"width": 0.65, "height": 0.6})
    viewport.set_reviewing(False)
    app.processEvents()
    assert viewport.web.geometry() == viewport.rect()
    assert all(handle.isHidden() for handle in viewport.handles.values())
    viewport.set_reviewing(True)
    assert viewport.ratios == (0.65, 0.6)
    QTest.mouseDClick(viewport.handles["bottom"], Qt.MouseButton.LeftButton)
    assert saved == [{"width": 1.0, "height": 1.0}]
    assert viewport.ratios == (1.0, 1.0)


def test_previous_button_does_not_reduce_card_resize_range(review_layout) -> None:
    app, layout, saved = review_layout
    layout.set_reviewing(True)
    viewport = layout.viewport
    for width in (520, 1000, 1400):
        layout.resize(width, 700)
        viewport.reset_layout()
        app.processEvents()
        assert viewport.width() == layout.width()
        assert viewport.web.width() == layout.width() - 16
        assert layout.previous_button.isVisible()
        assert not layout.previous_button.geometry().intersects(
            viewport.handles["left"].geometry()
        )
        viewport.resize_card(viewport.width() - 64, viewport.web.height())
        app.processEvents()
        assert not layout.previous_button.geometry().intersects(
            viewport.handles["left"].geometry()
        )
        viewport.resize_card(400, 250)
        app.processEvents()
        assert viewport.web.width() == 400
        assert viewport.web.height() == 250
    layout.set_reviewing(False)
    app.processEvents()
    assert layout.previous_button.isHidden()
    assert viewport.web.geometry() == viewport.rect()
