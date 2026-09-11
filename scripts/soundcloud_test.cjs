const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("qt/aqt/builtin_features/synapsepro/soundcloud_player.html", "utf8").match(
    /<script>\s*([\s\S]*?)<\/script>/,
)[1];
function setup(index = 2) {
    const events = {}, calls = [], pending = [];
    const widget = {
        bind: (event, callback) => events[event] = callback,
        getSounds: cb => pending.push(() => cb([{}, {}, {}])),
        getCurrentSoundIndex: cb => pending.push(() => cb(index)),
        getCurrentSound: cb => cb(null),
        skip: n => calls.push(["skip", n]),
        play: () => calls.push(["play"]),
        pause: () => calls.push(["pause"]),
        next: () => calls.push(["next"]),
        prev: () => {},
    };
    const context = {
        console: { log() {} },
        window: { addEventListener() {} },
        SC: { Widget: { Events: { READY: "ready", PLAY: "play", PAUSE: "pause", FINISH: "finish" } } },
    };
    context.window.SC = context.SC;
    vm.createContext(context);
    vm.runInContext(source, context);
    context.widget = widget;
    context._widgetReady = true;
    context.bindEvents();
    return {
        context,
        calls,
        events,
        flush: () => {
            while (pending.length) { pending.shift()(); }
        },
    };
}
let s = setup();
s.context.scSetLoop(true);
s.events.finish();
s.flush();
assert.deepEqual(s.calls, [["skip", 0], ["play"]]);
s = setup();
s.events.finish();
s.flush();
assert.deepEqual(s.calls, []);
s = setup(1);
s.context.scSetLoop(true);
s.events.finish();
s.flush();
assert.deepEqual(s.calls, []);
for (const cancel of ["scPause", "scNext"]) {
    s = setup();
    s.context.scSetLoop(true);
    s.events.finish();
    s.context[cancel]();
    s.flush();
    assert.equal(s.calls.some(c => c[0] === "skip" || c[0] === "play"), false);
}
s = setup();
s.context.scSetLoop(true);
s.events.finish();
s.context.scSetLoop(false);
s.flush();
assert.deepEqual(s.calls, []);
s = setup();
s.context.scSetLoop(true);
s.context.scPause();
s.context.scPlay();
s.calls.length = 0;
s.events.finish();
s.flush();
assert.deepEqual(s.calls, [["skip", 0], ["play"]]);
console.log("SoundCloud: 7 deterministic widget queue scenarios passed (mock API, not live streaming).");
