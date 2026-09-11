/* Copyright: Ankitects Pty Ltd and contributors
 * License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html */

$(init);

function init() {
    setupDeckWorkspace();
    $("tr.deck").draggable({
        scroll: false,

        // can't use "helper: 'clone'" because of a bug in jQuery 1.5
        helper: function(_event) {
            return $(this).clone(false);
        },
        delay: 200,
        opacity: 0.7,
    });
    $("tr.deck").droppable({
        drop: handleDropEvent,
        hoverClass: "drag-hover",
    });
    $("tr.top-level-drag-row").droppable({
        drop: handleDropEvent,
        hoverClass: "drag-hover",
    });
}

function setupDeckWorkspace() {
    const workspace = document.querySelector<HTMLElement>(".deck-workspace");
    const search = document.querySelector<HTMLInputElement>("#deck-search");
    const scroll = document.querySelector<HTMLElement>(".deck-tree-scroll");
    if (!workspace || !search || !scroll) { return; }
    const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tr.deck"));
    const byId = new Map(rows.map((row) => [row.id, row]));
    const key = "anki-deck-directory";
    let previous: { query?: string; scroll?: number; auxiliary?: boolean; widgets?: boolean } = {};
    try {
        previous = JSON.parse(sessionStorage.getItem(key) || "{}");
    } catch { /* A previous page may have stored invalid state. */ }
    search.value = previous.query || "";
    const auxiliary = document.querySelector<HTMLDetailsElement>(".deck-auxiliary")!;
    const widgets = document.querySelector<HTMLDetailsElement>(".deck-global-widgets")!;
    auxiliary.open = previous.auxiliary ?? window.innerWidth >= 1000;
    widgets.open = previous.widgets ?? true;

    function save() {
        sessionStorage.setItem(
            key,
            JSON.stringify({
                query: search!.value,
                scroll: scroll!.scrollTop,
                auxiliary: auxiliary.open,
                widgets: widgets.open,
            }),
        );
    }
    function filter() {
        const query = search!.value.trim().toLocaleLowerCase();
        const matches = new Set<string>();
        rows.forEach((row) => {
            if ((row.dataset.path || "").toLocaleLowerCase().includes(query)) {
                matches.add(row.id);
                (row.dataset.ancestors || "").split(",").forEach((id) => matches.add(id));
            }
        });
        rows.forEach((row) => {
            const ancestors = (row.dataset.ancestors || "").split(",").filter(Boolean);
            row.hidden = query
                ? !matches.has(row.id)
                : ancestors.some((id) => byId.get(id)?.dataset.collapsed === "1");
            const link = row.querySelector<HTMLAnchorElement>("a.deck");
            if (link) {
                link.textContent = query ? row.dataset.path! : row.dataset.path!.split("::").pop()!;
            }
        });
        document.querySelector<HTMLElement>("#deck-no-match")!.hidden = rows.some((row) => !row.hidden);
    }
    filter();
    scroll.scrollTop = previous.scroll || 0;
    if (!search.value) {
        document.querySelector<HTMLElement>("tr.current:not([hidden])")?.scrollIntoView({ block: "nearest" });
    }
    search.addEventListener("input", () => {
        filter();
        save();
    });
    search.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            search.value = "";
            filter();
            save();
        }
        if (event.key === "Enter") {
            const match = rows.find((row) =>
                !row.hidden
                && (row.dataset.path || "").toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
            );
            if (match) { pycmd("select:" + match.id); }
        }
    });
    scroll.addEventListener("scroll", save);
    auxiliary.addEventListener("toggle", save);
    widgets.addEventListener("toggle", save);
    workspace.dataset.ready = "true";
}

function handleDropEvent(event, ui) {
    const draggedDeckId = ui.draggable.attr("id");
    const ontoDeckId = $(this).attr("id") || "";

    pycmd("drag:" + draggedDeckId + "," + ontoDeckId);
}
