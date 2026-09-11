import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import preprocess from "svelte-preprocess";
import { fileURLToPath } from "url";

// This prevents errors being shown when opening VSCode on the root of the
// project, instead of the ts folder.
const tsFolder = dirname(fileURLToPath(import.meta.url));

/** @type {import('@sveltejs/kit').Config} */
const config = {
    // preprocess() slows things down by about 10%, but allows us to use :global { ... }
    preprocess: [vitePreprocess(), preprocess()],

    kit: {
        // Static fallback generation reloads config in another worker. A
        // timestamp default can give HTML and client code different globals.
        // Asset filenames remain content-hashed; the application version is
        // identical across all workers in this build.
        version: { name: readFileSync(join(tsFolder, "../.version"), "utf8").trim() },
        adapter: adapter(
            { pages: "../out/sveltekit", fallback: "index.html", precompress: false },
        ),
        alias: {
            "@tslib": join(tsFolder, "lib/tslib"),
            "@generated": join(tsFolder, "../out/ts/lib/generated"),
        },
        files: {
            lib: join(tsFolder, "lib"),
            routes: join(tsFolder, "routes"),
        },
        // outside of out/; as things break when out/ is a symlink
        outDir: join(tsFolder, ".svelte-kit"),
        output: { preloadStrategy: "preload-mjs" },
        prerender: {
            crawl: false,
            entries: [],
        },
        paths: {},
        csp: { mode: "hash", directives: { "script-src": ["'self'"] } },
    },
};

export default config;
