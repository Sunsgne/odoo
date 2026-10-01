import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";

const LEGACY = "/odoo";
const PREFIX = "/obss";

function isConsolePath(pathname) {
    return (
        pathname === PREFIX ||
        pathname.startsWith(`${PREFIX}/`) ||
        pathname === LEGACY ||
        pathname.startsWith(`${LEGACY}/`) ||
        pathname === "/web"
    );
}

function asLegacy(url) {
    const copy = new URL(url.href);
    if (copy.pathname === PREFIX || copy.pathname.startsWith(`${PREFIX}/`)) {
        copy.pathname = LEGACY + copy.pathname.slice(PREFIX.length);
    }
    return copy;
}

function publish(pathAndSearch) {
    if (
        pathAndSearch === LEGACY ||
        pathAndSearch.startsWith(`${LEGACY}/`) ||
        pathAndSearch.startsWith(`${LEGACY}?`)
    ) {
        return PREFIX + pathAndSearch.slice(LEGACY.length);
    }
    return pathAndSearch;
}

function rewriteHref(url) {
    if (typeof url !== "string" || !url) {
        return url;
    }
    let parsed;
    try {
        parsed = new URL(url, browser.location.origin);
    } catch {
        return url;
    }
    if (parsed.origin !== new URL(browser.location.href).origin) {
        return url;
    }
    if (parsed.pathname === LEGACY || parsed.pathname.startsWith(`${LEGACY}/`)) {
        parsed.pathname = PREFIX + parsed.pathname.slice(LEGACY.length);
        return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
    return url;
}

const stateToUrl = router.stateToUrl.bind(router);
const urlToState = router.urlToState.bind(router);
router.stateToUrl = (state) => publish(stateToUrl(state));
router.urlToState = (urlObj) => {
    const current = router.stateToUrl;
    router.stateToUrl = stateToUrl;
    try {
        return urlToState(asLegacy(urlObj));
    } finally {
        router.stateToUrl = current;
    }
};

const historyPush = browser.history.pushState.bind(browser.history);
const historyReplace = browser.history.replaceState.bind(browser.history);
browser.history.pushState = (data, unused, url) => historyPush(data, unused, rewriteHref(url));
browser.history.replaceState = (data, unused, url) =>
    historyReplace(data, unused, rewriteHref(url));

function show(next, mode) {
    const href = browser.location.origin + router.stateToUrl(next);
    const data = { nextState: next };
    if (mode === "push") {
        browser.history.pushState(data, "", href);
    } else {
        browser.history.replaceState(data, "", href);
    }
    browser.dispatchEvent(new PopStateEvent("popstate", { state: data }));
}

try {
    const path = browser.location.pathname;
    if (path === PREFIX || path.startsWith(`${PREFIX}/`)) {
        show(router.urlToState(new URL(browser.location.href)), "replace");
    } else if (path === LEGACY || path.startsWith(`${LEGACY}/`) || path === "/web") {
        const next = router.urlToState(new URL(browser.location.href));
        browser.history.replaceState(
            { nextState: next },
            "",
            browser.location.origin + router.stateToUrl(next),
        );
    }
} catch {
    // The framework client still opens on its own prefix.
}

browser.addEventListener(
    "click",
    (ev) => {
        if (
            ev.defaultPrevented ||
            ev.button !== 0 ||
            ev.ctrlKey ||
            ev.metaKey ||
            ev.shiftKey ||
            ev.altKey
        ) {
            return;
        }
        const a = ev.target.closest?.("a");
        if (!a || a.target === "_blank" || ev.target.closest?.("[contenteditable]")) {
            return;
        }
        const href = a.getAttribute("href");
        if (!href || href.startsWith("#")) {
            return;
        }
        let url;
        try {
            url = new URL(a.href);
        } catch {
            return;
        }
        if (url.host !== new URL(browser.location.href).host || !isConsolePath(url.pathname)) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        show(router.urlToState(url), "push");
    },
    true,
);
