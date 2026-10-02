import { Component, useState, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const GROUPS = [
    {
        label: "运行",
        items: [
            { key: "home", label: "总览", icon: "fa-th-large", action: "zenlenet_ops.action_home_page" },
            { key: "campus", label: "园区", icon: "fa-building", action: "zenlenet_ops.action_datacenter_board" },
            { key: "itam", label: "资产", icon: "fa-cubes", action: "zenlenet_ops.action_itam" },
            { key: "ipam", label: "地址", icon: "fa-sitemap", action: "zenlenet_ops.action_ipam" },
            { key: "purchase", label: "采购", icon: "fa-shopping-cart", action: "zenlenet_ops.action_purchase_board" },
            { key: "duty", label: "排班", icon: "fa-calendar", action: "zenlenet_ops.action_duty_calendar" },
            { key: "flow", label: "工单", icon: "fa-random", action: "zenlenet_ops.action_flow" },
            { key: "ticket", label: "故障", icon: "fa-exclamation-triangle", action: "zenlenet_ops.action_tickets" },
        ],
    },
    {
        label: "业务",
        items: [
            { key: "customer", label: "客户", icon: "fa-building-o", action: "zenlenet_ops.action_customers" },
            { key: "contract", label: "合同", icon: "fa-file-text-o", action: "zenlenet_ops.action_contracts" },
            { key: "order", label: "订单", icon: "fa-list-alt", action: "zenlenet_ops.action_orders" },
            { key: "bill", label: "账单", icon: "fa-credit-card", action: "zenlenet_ops.action_month" },
            { key: "copilot", label: "副驾", icon: "fa-comments", action: "zenlenet_ops.action_copilot" },
        ],
    },
];

const ACTION_KEY = {
    "zenlenet_ops.action_home_page": "home",
    "zenlenet_ops.action_datacenter_board": "campus",
    "zenlenet_ops.action_itam": "itam",
    "zenlenet_ops.action_ipam": "ipam",
    "zenlenet_ops.action_purchase_board": "purchase",
    "zenlenet_ops.action_duty_calendar": "duty",
    "zenlenet_ops.action_flow": "flow",
    "zenlenet_ops.action_tickets": "ticket",
    "zenlenet_ops.action_customers": "customer",
    "zenlenet_ops.action_contracts": "contract",
    "zenlenet_ops.action_orders": "order",
    "zenlenet_ops.action_month": "bill",
    "zenlenet_ops.action_copilot": "copilot",
};

export class ZenlenetSidebar extends Component {
    static template = "zenlenet_ops.Sidebar";
    static props = {};

    setup() {
        this.action = useService("action");
        this.state = useState({ active: "home" });
        this.groups = GROUPS;
        this._onUi = () => this.syncActive();
        this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", this._onUi);
        onWillUnmount(() => {
            this.env.bus.removeEventListener("ACTION_MANAGER:UI-UPDATED", this._onUi);
        });
        this.syncActive();
    }

    syncActive() {
        const current = this.action.currentController?.action;
        if (!current) {
            return;
        }
        const xmlid = current.xml_id || current.xmlid;
        if (xmlid && ACTION_KEY[xmlid]) {
            this.state.active = ACTION_KEY[xmlid];
            return;
        }
        const tag = current.tag;
        const byTag = {
            zenlenet_datacenter: "campus",
            zenlenet_itam: "itam",
            zenlenet_ipam: "ipam",
            zenlenet_purchase_board: "purchase",
            zenlenet_duty: "duty",
            zenlenet_month: "bill",
            zenlenet_copilot: "copilot",
        };
        if (tag && byTag[tag]) {
            this.state.active = byTag[tag];
            return;
        }
        const model = current.res_model;
        const byModel = {
            "zenlenet.home": "home",
            "res.partner": "customer",
            "zenlenet.contract": "contract",
            "sale.order": "order",
            "zenlenet.flow": "flow",
            "zenlenet.ticket": "ticket",
        };
        if (model && byModel[model]) {
            this.state.active = byModel[model];
        }
    }

    isActive(key) {
        return this.state.active === key;
    }

    async open(item) {
        this.state.active = item.key;
        await this.action.doAction(item.action, { clearBreadcrumbs: true });
    }
}
