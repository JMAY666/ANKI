# Six built-in tools: exact source provenance

Retrieved from AnkiWeb on 2026-09-11. These are source integrations in aqt, never installed via the add-on manager. Original archives, extraction and HTTP metadata are retained in the ignored recovery baseline `runtime/six-addons-20260911/`.

The only archive declaring a semantic version is Advanced Review Bottom Bar: CHANGELOG.md begins with 3.6.1 (2025-10-03). The other five archives do not declare a semantic version; use their timestamp and SHA-256 as the immutable source version. AnkiWeb compatibility metadata is historical, not proof of compatibility with this Anki 26.08.1 build.

| AnkiWeb ID / title                                                                                                    | Server update (UTC)       | Archive SHA-256                                                    | Runtime source                                 |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------ | ---------------------------------------------- |
| [1323545382 — Pace Graph — Review Speed Tracker](https://ankiweb.net/shared/info/1323545382)                          | 2026-09-10T01:43:45+00:00 | `e2f427d15e9fffa10704ad254fbd3b45f1e91c6a7b35fe1476d1aac082935fc1` | `pace_graph/`                                  |
| [2494384865 — Button Colours (Good, Again)](https://ankiweb.net/shared/info/2494384865)                               | 2022-09-27T10:18:23+00:00 | `7e587cfedefc2bf378c6e5560784d338c97adb6c87d041c92ca79f9916e0204b` | `__init__.py: decorate_buttons()`              |
| [1613056169 — Search Stats Extended](https://ankiweb.net/shared/info/1613056169)                                      | 2026-05-14T21:07:28+00:00 | `a35696530d581d8b62c2838fbeffa82691e043af98f948cc7253617c0ba914c8` | `search_stats/`                                |
| [1136455830 — Advanced Review Bottom Bar](https://ankiweb.net/shared/info/1136455830)                                 | 2025-10-03T19:55:16+00:00 | `13b92dc0cecfc6440d47acfa0294c0b7c7118313fc14c0f7629e3a77bb2407b6` | `advanced/, info.py, feedback.py, settings.py` |
| [2060144143 — Show Answer Button Pressed](https://ankiweb.net/shared/info/2060144143)                                 | 2026-09-06T21:23:36+00:00 | `e6b8538116a061791c50b0e37cb7e67f03fc6362e586aa8be9b4dd97b2391399` | `feedback.py`                                  |
| [1659223841 — Confident But Wrong — do your fast answers actually stick?](https://ankiweb.net/shared/info/1659223841) | 2026-09-09T03:46:08+00:00 | `f99e7a763e92681fbb6690693855db8ade7230e5dde0c8d3359cb7089662c170` | `confidence.py`                                |

## Dependencies and source boundaries

- Pace Graph: Python standard library + Anki Qt; preserve Pace, SmoothPace, three overlay modes, custom palettes, opacity, sizes, position, pause, temporary hiding, presets, live preview and cancel. Its README contains obsolete default-mode descriptions; the actual downloaded config uses Minimal.
- Button Colours: native answer-button hook and theme; copied light/dark palettes, original rating-index color selection.
- Search Stats Extended: original bundled Svelte 5, protobuf, D3/Lodash/ts-fsrs and Fluent runtime; en_GB, pt_BR and zh_CN are bundled. No npm dependency or other add-on is required at runtime. The compiled JS contains its source-module names and is retained in readable form. Native adapters namespace endpoints, validate requests, serialize collection access on the main thread, bind initialization once and supply the current graph request explicitly. Its calculations were not replaced with an approximate dashboard.
- Advanced Review Bottom Bar 3.6.1: original styles and renderer functions are retained with their copyright headers. Global Reviewer/DeckBrowser/Overview replacements and legacy add-on loading are removed. Current native operations handle grading/undo/bury/suspend. Settings and the card-information dock use current Qt/Anki APIs. The user approved keeping existing home layout, switching between three visual modes, a single optional rating indicator, and hiding the skip button by default. External Speed Focus/Rebuild add-on interoperability flags and old add-on menu placement remain in stored data but do not load external code.
- Show Answer Button Pressed: reusable QLabel, native post-answer hook, original language/custom-label options, colors, duration and debug switch. Cleanup now reuses and hides the label, including statistics within a paused review session.
- Confident But Wrong: original read-only SQL and consecutive-review-pair analysis, deck median, gap/lookback filters, report and browser query retained. It does not update card state or scheduling.

## Licenses

- Search Stats Extended: GPL-3.0-only, Copyright 2023 Luc McGrady and contributors; original LICENSE and bundled dependency notices retained.
- Advanced Review Bottom Bar: GNU GPL v3, original Noobj2 / Mohamad Janati copyright notices retained. LICENSE was verified against the author repository linked from the package README: https://github.com/noobj2/Anki-Advanced-Review-Bottombar/blob/master/LICENSE.
- Show Answer Button Pressed: the current AnkiWeb description explicitly declares MIT. Its author repository is https://github.com/codylewis/anki-show-answer-button-pressed. See `LICENSE-answer-feedback`.
- Button Colours, Pace Graph and Confident But Wrong: no separate license declaration in the retrieved archive or current AnkiWeb description. AnkiWeb Terms and Conditions state that add-ons with no explicit license are assumed to be AGPL3: https://ankiweb.net/account/terms. The published terms were retrieved as the current page asset `12.DfEVPDuk.mjs`; the audit copy is in the ignored recovery baseline. New native integration code is AGPL-3.0-or-later.

Original source archives and personal data are excluded from Git; licenses, adapted source, defaults and runtime resources are included.

## Chinese presentation

The integrated UI is localized into Chinese, including the pace overlay, native settings, stock rating labels, card information, feedback and confidence report. Missing Search Stats Extended translations and untranslated existing Chinese-locale messages are completed. Original configuration keys, query syntax, author attribution and user card content are retained. Nested configuration editors round-trip the original schema; English CSS color names are displayed as equivalent hexadecimal values without changing untouched stored values.
