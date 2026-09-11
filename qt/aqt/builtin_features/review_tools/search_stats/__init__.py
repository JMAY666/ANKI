# Source integration: Ankitects Pty Ltd and contributors
# Copyright (c) 2023 Luc McGrady and contributors; native integration by Anki contributors.
# License: GPL-3.0-only; see LICENSE and ../SOURCE.md.
"""The original Search Stats Extended UI on the existing detailed statistics page."""

from __future__ import annotations

import json
import secrets
from concurrent.futures import Future
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from aqt.qt import QWebEngineScript

from ..config import get_config, merge, validate

ROOT = Path(__file__).parent
CARD_COLUMNS = [
    "id",
    "nid",
    "did",
    "ord",
    "mod",
    "usn",
    "type",
    "queue",
    "due",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "odue",
    "odid",
    "flags",
    "data",
]
REVLOG_COLUMNS = ["id", "cid", "ease", "ivl", "lastIvl", "time", "factor", "type"]


def card_ids(value: Any) -> list[int]:
    if not isinstance(value, list) or any(
        type(cid) is not int or not 0 < cid < 2**63 for cid in value
    ):
        raise ValueError("卡片编号必须为正整数")
    return list(dict.fromkeys(value))


def query_rows(
    col: Any, table: str, columns: list[str], ids: list[int], lower: int = 0
) -> list:
    result = []
    id_column = "id" if table == "cards" else "cid"
    for start in range(0, len(ids), 900):
        batch = ids[start : start + 900]
        query = f"select {','.join(columns)} from {table} where {id_column} in ({','.join('?' for _ in batch)})"
        if table == "revlog":
            query += " and id > ? order by id"
            result.extend(col.db.all(query, *batch, lower))
        else:
            result.extend(col.db.all(query, *batch))
    if table == "revlog":
        result.sort(key=lambda row: row[0])
    return result


def handle_data(col: Any, endpoint: str, data: bytes) -> Any:
    if endpoint == "cardSearch":
        return list(col.find_cards(data.decode("utf8")))
    parsed = json.loads(data)
    if endpoint == "cardData":
        ids = card_ids(parsed)
        return {
            "columns": CARD_COLUMNS,
            "data": query_rows(col, "cards", CARD_COLUMNS, ids),
        }
    if endpoint == "revlogs":
        if not isinstance(parsed, dict):
            raise ValueError("请求必须为对象")
        ids = card_ids(parsed.get("cids"))
        days = parsed.get("day_range")
        if type(days) is not int or not 0 <= days <= 100000:
            raise ValueError("复习记录范围无效")
        # Preserve the downloaded add-on's rolling-range cutoff formula.
        from anki.utils import int_time

        lower = (
            (
                int_time()
                - col.get_preferences().scheduling.rollover * 3600
                - days * 86400
            )
            * 1000
            if days
            else 0
        )
        return {
            "columns": REVLOG_COLUMNS,
            "data": query_rows(col, "revlog", REVLOG_COLUMNS, ids, lower),
        }
    raise ValueError("未知统计接口")


class SearchStats:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.token = secrets.token_urlsafe(32)
        from aqt.mediasrv import post_handlers

        for endpoint in (
            "cardSearch",
            "cardData",
            "revlogs",
            "writeConfig",
            "openLocaleFolder",
        ):
            key = "builtinSearchStats-" + endpoint
            if key in post_handlers:
                raise RuntimeError(f"统计接口已注册，不能重复加载：{key}")
            post_handlers[key] = partial(self.request, endpoint)

    def rotate_token(self) -> None:
        self.token = secrets.token_urlsafe(32)

    def request(self, endpoint: str) -> Any:
        from flask import Response, request

        token = request.headers.get("X-Builtin-Search-Stats", "")
        if not secrets.compare_digest(token, self.token):
            return Response("统计会话已失效，请重新打开统计页", status=403)
        raw = request.get_data()
        future: Future[Any] = Future()

        def main() -> None:
            if future.cancelled():
                return
            try:
                col = self.owner.mw.col
                if not col or not secrets.compare_digest(token, self.token):
                    raise ValueError("当前没有打开可用的集合")
                if endpoint == "writeConfig":
                    change = json.loads(raw)
                    key = change.get("key")
                    if key not in get_config("search_stats"):
                        raise ValueError("未知统计设置")
                    value = merge(get_config("search_stats"), {key: change["value"]})
                    validate("search_stats", value)
                    self.owner.config.save("search_stats", value)
                    result = None
                elif endpoint == "openLocaleFolder":
                    from aqt.utils import openFolder

                    from ...storage import copy_missing

                    destination = self.owner.config.root / "search_stats/locale"
                    copy_missing(ROOT / "locale", destination)
                    openFolder(str(destination))
                    result = None
                else:
                    result = handle_data(col, endpoint, raw)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)

        self.owner.mw.taskman.run_on_main(main)
        try:
            value = future.result(timeout=20)
            return Response(
                json.dumps(value, ensure_ascii=False), mimetype="application/json"
            )
        except Exception as exc:
            future.cancel()
            return Response(str(exc), status=400, mimetype="text/plain")

    def attach(self, web: Any) -> None:
        if getattr(web, "_builtin_search_stats", False):
            return
        web._builtin_search_stats = True
        script = QWebEngineScript()
        script.setName("builtin-search-stats-capture")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(
            """(()=>{const native=window.fetch,controller=new AbortController();window.__builtinStatsErrors=[];window.__builtinStatsAbort=controller;addEventListener('pagehide',()=>controller.abort());addEventListener('beforeunload',()=>controller.abort());addEventListener('error',e=>window.__builtinStatsErrors.push(String(e.message)));addEventListener('unhandledrejection',e=>{if(e.reason?.name==='AbortError'&&controller.signal.aborted){e.preventDefault();return}window.__builtinStatsErrors.push(String(e.reason?.stack||e.reason))});window.fetch=function(req,options={}){const signal=options.signal?AbortSignal.any([controller.signal,options.signal]):controller.signal;return native.call(this,req,{...options,signal})}})();"""
        )
        web.page().scripts().insert(script)
        web.loadFinished.connect(lambda ok: self.inject(web) if ok else None)

    def inject(self, web: Any) -> None:
        if not self.owner.mw.col or not get_config("policy")["search_stats_enabled"]:
            return
        url = urlparse(web.url().toString())
        expected = urlparse(self.owner.mw.serverURL())
        if (url.hostname, url.port) != (
            expected.hostname,
            expected.port,
        ) or url.path.rstrip("/") != "/graphs":
            return
        col = self.owner.mw.col
        config = get_config("search_stats")
        locale = ROOT / "locale"
        custom_locale = self.owner.config.root / "search_stats/locale"
        locale_files = {
            path.stem: path
            for directory in (locale, custom_locale)
            for path in directory.glob("*.ftl")
        }
        names = sorted(locale_files)
        lang = config.get("forceLang") or self.owner.mw.pm.meta["defaultLang"]
        if lang not in names:
            lang = "en_GB"
        prefs = col.get_preferences().scheduling
        other = {
            "rollover": prefs.rollover,
            "learn_ahead_secs": prefs.learn_ahead_secs,
            "deck_configs": {conf["id"]: conf for conf in col.decks.all_config()},
            "deck_config_ids": {
                deck["id"]: deck.get("conf") for deck in col.decks.all()
            },
            "days_elapsed": col.sched.today,
            "lang": lang,
            "available_langs": names,
            "lang_ftl": locale_files[lang].read_text(encoding="utf8"),
            "fallback_ftl": (locale / "en_GB.ftl").read_text(encoding="utf8"),
        }
        css = (ROOT / "stats.min.css").read_text(encoding="utf8")
        js = (ROOT / "stats.min.js").read_text(encoding="utf8")
        from anki.stats_pb2 import GraphsRequest

        scope = parse_qs(url.query)
        initial = GraphsRequest(
            search=scope.get("scope", [""])[0],
            days=int(scope.get("days", ["0"])[0]),
        ).SerializeToString()
        web.eval(
            "(()=>{if(window.__builtinSearchStatsMounted)return;window.__builtinSearchStatsMounted=true;"
            + f"const css={json.dumps(css)}, SSEconfig={json.dumps(config)}, SSEother={json.dumps(other)}, SSEtoken={json.dumps(self.token)}, SSEinitialBody=new Uint8Array({list(initial)});"
            + js
            + "window.fetch('/_anki/graphs',{method:'POST',headers:{'Content-Type':'application/binary'},body:SSEinitialBody}).catch(e=>{if(e?.name!=='AbortError')throw e});})();"
        )


def install(owner: Any) -> SearchStats:
    return SearchStats(owner)
