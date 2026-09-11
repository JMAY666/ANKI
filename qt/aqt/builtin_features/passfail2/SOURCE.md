# Pass/Fail 2 source provenance

- AnkiWeb ID: [876946123](https://ankiweb.net/shared/info/876946123).
- Downloaded 2026-09-11 with the native Anki download route for client 260801.
- Resolved package: `https://ankiweb.net/svc/shared/download-addon/876946123?t=1717466194&minpt=15&maxpt=66&bidx=0`.
- Package SHA-256: `fb4c98a63d76384204b59cea75702939cc23b6e7f4eb6c73c307b2a810573c4f`.
- `build_info.py`: version `0.3.0`; manifest package `PassFail2`, name `Pass/Fail 2`.
- Server modification time: 2024-06-04 01:56:34 UTC; branch metadata minpt 15, maxpt 66. These old compatibility bounds do not prove compatibility with Anki 26.8.1.
- Original runtime files inspected: `passfail2.py`, `config.py`, `configuration_menu.py`, `config.json`, `__init__.py`, `logger.py`, `build_info.py`, `manifest.json`.
- Author repository: [lambdadog/passfail2](https://github.com/lambdadog/passfail2); HEAD observed during inspection: `d5313e4f1217e968b36edbc0a4fe92386209ffe6`.
- License: GNU GPL version 3 or later, from the original runtime header. The complete license is included in `LICENSE`, retrieved from the author's repository. Original attribution: Ashlynn Anderson; acknowledgements to Dmitry Mikheev, Rohan Modi and the Anki team.

The integrated implementation adapts the original button filter and rating remapping to the current native hooks. It retains Fail = 1, Pass = reviewer default ease, all non-Again input keys mapping to Pass, and the existing `toggle_names_textcolors` switch, names, color picker, preview, validation and explicit Save/Cancel behavior. The original code permits names shorter than 15 characters (the original help text's "0–15" is imprecise).

The original runtime has no two/four-button mode toggle and no background-color toggle, despite stale help text mentioning two checkboxes. Native four-grade versus Pass/Fail mode selection is an integration addition; new installations default to native grading, while migrated installations retain the former add-on enabled/disabled state.

Changes from the original: built-in storage instead of AddonManager configuration, idempotent native registration instead of legacy class monkey-patches, localized built-in settings entry, safe HTML escaping for labels, live controls-only redraw, and shortcut hints using the user's configured answer keys. Settings remain global to the local Anki data root, as with the original add-on.
