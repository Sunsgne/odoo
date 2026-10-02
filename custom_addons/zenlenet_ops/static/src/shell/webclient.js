import { WebClient } from "@web/webclient/webclient";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { ZenlenetSidebar } from "./sidebar";

const BRAND = "OBSS 运营业务支撑";

WebClient.components = {
    ...WebClient.components,
    ZenlenetSidebar,
};

patch(WebClient, {
    template: "zenlenet_ops.WebClient",
});

patch(NavBar.prototype, {
    get currentApp() {
        const app = super.currentApp;
        if (!app) {
            return app;
        }
        return { ...app, name: BRAND };
    },
    get currentAppSections() {
        return [];
    },
});
