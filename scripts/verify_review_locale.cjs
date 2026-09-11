// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "../qt/aqt/builtin_features/review_tools/search_stats");
const bundle = fs.readFileSync(path.join(root, "stats.min.js"), "utf8");
const start = bundle.indexOf("// node_modules/@fluent/bundle/esm/resource.js");
const end = bundle.indexOf("// src/ts/i18n.ts", start);
assert(start > 0 && end > start, "The reviewed Fluent parser must be present");
const context = vm.createContext({});
vm.runInContext(bundle.slice(start, end), context, { timeout: 2000 });
for (const language of ["zh_CN"]) {
    const source = fs.readFileSync(path.join(root, "locale", `${language}.ftl`), "utf8");
    const declared = [...source.matchAll(/^([A-Za-z][\w-]*)\s*=/gm)].map(match => match[1]);
    context.source = source;
    const parsed = Array.from(
        vm.runInContext("new FluentResource(source).body.map(entry => entry.id)", context, { timeout: 2000 }),
    );
    const missing = declared.filter(id => !parsed.includes(id));
    assert.deepEqual(missing, [], `${language}: invalid Fluent message syntax`);
    assert.equal(new Set(parsed).size, parsed.length, `${language}: duplicate messages`);
    // The downloaded English resource repeats two IDs; the original runtime
    // keeps the first declaration. Validate coverage without rewriting it.
    const original = fs.readFileSync(path.join(root, "locale", "en_GB.ftl"), "utf8");
    const englishIds = new Set([...original.matchAll(/^([A-Za-z][\w-]*)\s*=/gm)].map(match => match[1]));
    assert.deepEqual(
        [...englishIds].filter(id => !parsed.includes(id)),
        [],
        "Chinese must cover every original message",
    );
    process.stdout.write(`${language}: ${parsed.length} messages parsed by the shipped Fluent runtime\n`);
}
