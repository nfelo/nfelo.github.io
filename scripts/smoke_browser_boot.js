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
  attributes: {},
  innerHTML: (
    '<div class="loading-shell">'
    + "<p>Loading the latest ratings…</p></div>"
  ),
  focus: () => {},
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  },
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
  querySelector: () => null,
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
  body: {
    append: () => {},
    classList,
    dataset: {},
  },
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
      attributes: {},
      className: "",
      hidden: false,
      setAttribute(name, value) {
        this.attributes[name] = String(value);
      },
      set src(value) { this._src = value; },
      get src() { return this._src; },
      onerror: null,
    };
  },
};

const windowObject = {
  __nfeloBoot: {},
  goatcounter: null,
  scrollY: 0,
  scrollCalls: [],
  addEventListener(type, callback) {
    listeners.set(`window:${type}`, callback);
  },
  requestAnimationFrame(callback) {
    callback();
    return 1;
  },
  scrollTo(options) {
    const top = typeof options === "number"
      ? options
      : Number(options?.top) || 0;
    this.scrollY = top;
    this.scrollCalls.push(top);
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
const applyURL = (value) => {
  if (!value) return;
  const target = new URL(value, location.origin);
  location.pathname = target.pathname;
  location.search = target.search;
  location.hash = target.hash;
};
const historyEntries = [{
  pathname: location.pathname,
  search: location.search,
  hash: location.hash,
  state: null,
}];
let historyIndex = 0;
const history = {
  state: null,
  scrollRestoration: "auto",
  replaceState(state, _title, url) {
    applyURL(url);
    this.state = state;
    historyEntries[historyIndex] = {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
      state,
    };
  },
  pushState(state, _title, url) {
    applyURL(url);
    this.state = state;
    historyEntries.splice(
      historyIndex + 1,
      historyEntries.length,
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
        state,
      },
    );
    historyIndex += 1;
  },
  back() {
    if (historyIndex === 0) return;
    historyIndex -= 1;
    const entry = historyEntries[historyIndex];
    location.pathname = entry.pathname;
    location.search = entry.search;
    location.hash = entry.hash;
    this.state = entry.state;
    listeners.get("window:popstate")?.({
      state: entry.state,
    });
  },
};

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
    retrospective: { accuracy: 0, log_loss: 0 },
  },
};
const fixtures = { fixtures: [] };

async function fetchMock(input) {
  const pathname = new URL(String(input)).pathname;
  let value;
  if (pathname.endsWith("/data/bootstrap.json")) value = summary;
  else if (pathname.endsWith("/data/summary.json")) value = summary;
  else if (pathname.endsWith("/data/home.json")) value = fixtures;
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
  navigator: { onLine: true },
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
  if (history.scrollRestoration !== "manual") {
    throw new Error("Route scroll restoration was not made deterministic.");
  }

  windowObject.scrollY = 420;
  let prevented = false;
  const aboutLink = {
    getAttribute(name) {
      if (name === "href") return "#/about";
      if (name === "target") return "";
      return null;
    },
    hasAttribute: () => false,
  };
  listeners.get("document:click")?.({
    target: {
      closest(selector) {
        return selector === 'a[href^="#/"]'
          ? aboutLink
          : null;
      },
    },
    defaultPrevented: false,
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    preventDefault() {
      prevented = true;
    },
  });
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (content.innerHTML.includes("<h1>About</h1>")) break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  if (!prevented || location.pathname !== "/about/") {
    throw new Error("Internal route navigation did not use clean history.");
  }
  if (!content.innerHTML.includes("<h1>About</h1>")) {
    throw new Error("Internal route navigation did not render its page.");
  }
  if (windowObject.scrollY !== 0) {
    throw new Error("A newly selected page did not open at the top.");
  }

  history.back();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (content.innerHTML.includes("home-page")) break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  if (
    location.pathname !== "/"
    || !content.innerHTML.includes("home-page")
  ) {
    throw new Error(
      "Browser Back did not restore the preceding home route.",
    );
  }
  if (windowObject.scrollY !== 420) {
    throw new Error(
      "Browser Back did not restore the preceding page position.",
    );
  }

  console.log(
    "Browser boot and route-history smoke test passed: "
    + "new pages open at the top and Back restores the prior route.",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
