// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { describe, expect, test } from "vitest";

import { viewportFrameInset } from "./viewport";

describe("legacy full-card frame resizing", () => {
    test("retains the original inset of a viewport-sized frame", () => {
        expect(viewportFrameInset("665px", 0, 1394, 1394, 670)).toBe(5);
        expect(viewportFrameInset("665.5px", 2, 1370, 1394, 670)).toBe(4.5);
    });

    test.each(["95vh", "100%", "auto", "", "NaNpx", "Infinitypx"])(
        "leaves responsive or invalid height %s alone",
        (height) => expect(viewportFrameInset(height, 0, 1394, 1394, 670)).toBeNull(),
    );

    test("leaves smaller, overflowing, narrow and lower embeds alone", () => {
        expect(viewportFrameInset("300px", 0, 1394, 1394, 670)).toBeNull();
        expect(viewportFrameInset("1200px", 0, 1394, 1394, 670)).toBeNull();
        expect(viewportFrameInset("665px", 0, 480, 1394, 670)).toBeNull();
        expect(viewportFrameInset("665px", 100, 1394, 1394, 670)).toBeNull();
    });
});
