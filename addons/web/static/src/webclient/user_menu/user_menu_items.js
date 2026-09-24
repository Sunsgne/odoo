import { Component, markup } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { browser } from "../../core/browser/browser";
import { registry } from "../../core/registry";

class ShortcutsFooterComponent extends Component {
    static template = "web.UserMenu.ShortcutsFooterComponent";
    static props = {
        switchNamespace: { type: Function, optional: true },
    };
    setup() {
        this.runShortcutKey = isMacOS() ? "CONTROL" : "ALT";
    }
}

function shortCutsItem(env) {
    return {
        type: "item",
        id: "shortcuts",
        hide: env.isSmall,
        description: markup`
            <div class="d-flex align-items-center justify-content-between p-0 w-100">
                <span>${_t("Shortcuts")}</span>
                <span class="fw-bold">${isMacOS() ? "CMD" : "CTRL"}+K</span>
            </div>`,
        callback: () => {
            env.services.command.openMainPalette({ FooterComponent: ShortcutsFooterComponent });
        },
        sequence: 30,
    };
}

function separator() {
    return {
        type: "separator",
        sequence: 40,
    };
}

export function preferencesItem(env) {
    return {
        type: "item",
        id: "preferences",
        description: _t("My Preferences"),
        callback: async function () {
            const actionDescription = await env.services.orm.call("res.users", "action_get");
            actionDescription.res_id = user.userId;
            env.services.action.doAction(actionDescription);
        },
        sequence: 50,
    };
}

function logOutItem(env) {
    let route = "/web/session/logout";
    if (env.services.pwa.isScopedApp) {
        route += `?redirect=${encodeURIComponent(env.services.pwa.startUrl)}`;
    }
    return {
        type: "item",
        id: "logout",
        description: _t("Log out"),
        href: `${browser.location.origin}${route}`,
        callback: () => {
            browser.navigator.serviceWorker?.controller?.postMessage("user_logout");
            browser.location.href = route;
        },
        sequence: 70,
    };
}

registry
    .category("user_menuitems")
    .add("shortcuts", shortCutsItem)
    .add("separator", separator)
    .add("preferences", preferencesItem)
    .add("log_out", logOutItem);
