// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
// @vitest-environment jsdom

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { bridgeCommand } from "./bridgecommand";
import { installReviewShortcutGuard } from "./review-shortcuts";

vi.mock("./bridgecommand", () => ({ bridgeCommand: vi.fn() }));

let frame: HTMLIFrameElement;
let side: string;
let enabled: boolean;

beforeEach(() => {
    frame = document.createElement("iframe");
    document.body.append(frame);
    vi.stubGlobal("window", frame.contentWindow);
    vi.stubGlobal("document", frame.contentDocument);
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    side = "question";
    enabled = true;
    installReviewShortcutGuard(() => enabled, () => side);
});

afterEach(() => {
    vi.unstubAllGlobals();
    frame.remove();
    vi.clearAllMocks();
});

function key(name: string, type = "keydown", options: KeyboardEventInit = {}): KeyboardEvent {
    const event = new KeyboardEvent(type, { key: name, bubbles: true, cancelable: true, ...options });
    (document.activeElement ?? document.body).dispatchEvent(event);
    return event;
}

function allowed(): boolean {
    return (window as unknown as { ankiReviewShortcutAllowed: () => boolean }).ankiReviewShortcutAllowed();
}

test("one press requests one answer and cancels a button's native activation", () => {
    expect(key(" ").defaultPrevented).toBe(true);
    key(" ", "keyup");
    key(" ", "keydown", { repeat: true });
    expect(bridgeCommand).toHaveBeenCalledExactlyOnceWith("reviewShortcut:show");
});

test("space and enter on a focused rating button cannot submit a rating", () => {
    side = "answer";
    document.body.innerHTML = "<button data-ease=\"3\">Good</button>";
    document.querySelector("button")!.focus();
    for (const name of [" ", "Enter"]) {
        expect(key(name).defaultPrevented).toBe(true);
        expect(key(name, "keyup").defaultPrevented).toBe(true);
    }
    expect(bridgeCommand).not.toHaveBeenCalled();
});

test.each(["<input>", "<textarea></textarea>", "<div contenteditable=\"true\" tabindex=\"0\"></div>"])(
    "editing %s keeps space, enter, and numbers in the editor",
    html => {
        document.body.innerHTML = html;
        (document.body.firstElementChild as HTMLElement).focus();
        expect(allowed()).toBe(false);
        expect(key(" ").defaultPrevented).toBe(false);
        key("Enter");
        key("1");
        expect(bridgeCommand).not.toHaveBeenCalled();
    },
);

test("IME composition and composing key events do not flip the card", () => {
    document.dispatchEvent(new CompositionEvent("compositionstart"));
    expect(allowed()).toBe(false);
    key("Enter");
    document.dispatchEvent(new CompositionEvent("compositionend"));
    key(" ", "keydown", { isComposing: true });
    expect(bridgeCommand).not.toHaveBeenCalled();
});

test("an input in a same-origin card frame blocks reviewer shortcuts", () => {
    document.body.innerHTML = "<iframe></iframe>";
    const nested = document.querySelector("iframe")!;
    nested.contentDocument!.body.innerHTML = "<input>";
    nested.contentDocument!.querySelector("input")!.focus();
    expect(allowed()).toBe(false);
});

test("a visible modal owns keyboard input", () => {
    document.body.innerHTML = "<div aria-modal=\"true\">Dialog</div>";
    vi.spyOn(document.body.firstElementChild!, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
    expect(allowed()).toBe(false);
    key(" ");
    expect(bridgeCommand).not.toHaveBeenCalled();
});

test("preview documents retain their independent keyboard behavior", () => {
    enabled = false;
    expect(key(" ").defaultPrevented).toBe(false);
    expect(allowed()).toBe(false);
    expect(bridgeCommand).not.toHaveBeenCalled();
});
