import { registry } from "@web/core/registry";

const menu = registry.category("user_menuitems");
for (const key of ["support", "odoo_account", "install_pwa"]) {
    if (menu.contains(key)) {
        menu.remove(key);
    }
}
