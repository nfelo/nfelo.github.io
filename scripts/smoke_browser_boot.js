#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const publicDir = process.argv[2];
if (!publicDir) {
  throw new Error("Usage: smoke_browser_boot.js PUBLIC_DIR");
}

const javascript = fs.readFileSync(
  path.join(publicDir, "assets", "app.js"),
  "utf8",
);

const listeners = new Map();
const classList = {
  contains: () => false,
  remove: () => {},
  toggle: () => {},
};
const content = {
  innerHTML: (
    '<div class="loading-shell">'
    + "<p>Loading the latest ratings…</p></div>"
  ),
  focus: () => {},
  querySelector(selector) {
    return selector === ".loading-shell"
      && this.innerHTML.includes("loading-shell")
      ? {}
      : null;
  },
};
const navigation = {
  classList,
  contains: () => false,
  querySelectorAll: () => [],
};
const menuButton = {
  addEventListener: () => {},
  setAttribute: () => {},
  focus: () => {},
};
const metadataNode = { setAttribute: () => {} };

const document = {
  baseURI: "https://example.test/",
  title: "",
  head: { appendChild: () => {} },
  getElementById(id) {
    if (id === "content") return content;
    if (id === "site-nav") return navigation;
    return null;
  },
  querySelector(selector) {
    if (selector === ".menu-button") return menuButton;
    if (selector === "h1") return null;
    if (
      selector.startsWith("meta[")
      || selector.startsWith("link[")
    ) return metadataNode;
    return null;
  },
  addEventListener(type, callback) {
    listeners.set(`document:${type}`, callback);
  },
  createElement() {
    return {
      set src(value) { this._src = value; },
      get src() { return this._src; },
      onerror: null,
    };
  },
};

const windowObject = {
  __nfeloBoot: {},
  goatcounter: null,
  addEventListener(type, callback) {
    listeners.set(`window:${type}`, callback);
  },
  setTimeout,
  clearTimeout,
};
windowObject.window = windowObject;
windowObject.document = document;

const location = {
  pathname: "/",
  search: "",
  hash: "",
  origin: "https://example.test",
  reload: () => {},
};
const history = { replaceState: () => {} };

const summary = {
  current: [],
  teams: [],
  top_matches: [],
  meta: {
    results_through: "2026-07-21",
    matches: 0,
    teams: 0,
  },
  validation: {
    nested: { accuracy: 0 },
  },
};
const catalog = { teams: [], tournaments: [] };
const fixtures = { fixtures: [] };

async function fetchMock(input) {
  const pathname = new URL(String(input)).pathname;
  let value;
  if (pathname.endsWith("/data/summary.json")) value = summary;
  else if (pathname.endsWith("/data/catalog.json")) value = catalog;
  else if (pathname.endsWith("/data/fixtures.json")) value = fixtures;
  else throw new Error(`Unexpected fetch in boot smoke test: ${pathname}`);
  return {
    ok: true,
    status: 200,
    async json() { return value; },
  };
}

const sandbox = {
  window: windowObject,
  document,
  location,
  history,
  fetch: fetchMock,
  URL,
  URLSearchParams,
  Date,
  Math,
  Intl,
  Number,
  String,
  Object,
  Array,
  Map,
  Set,
  Promise,
  console,
  encodeURIComponent,
  decodeURIComponent,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(javascript, sandbox, {
  filename: "public/assets/app.js",
});

(async () => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (windowObject.__nfeloBoot.ready) break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }

  if (!windowObject.__nfeloBoot.started) {
    throw new Error("Application JavaScript never started.");
  }
  if (!windowObject.__nfeloBoot.ready) {
    throw new Error(
      "Application JavaScript started but did not complete routing.",
    );
  }
  if (content.innerHTML.includes("Loading the latest ratings")) {
    throw new Error("Initial loading shell was not replaced.");
  }
  if (!content.innerHTML.includes("home-page")) {
    throw new Error("Home page was not rendered.");
  }

  console.log(
    "Browser boot smoke test passed: the application replaced "
    + "the initial loading shell.",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
