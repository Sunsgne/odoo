import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATUSES = [
    ["free", "未分配"],
    ["allocated", "已分配"],
    ["reserved", "预分配"],
    ["transferring", "调库中"],
    ["returning", "出库中"],
    ["testing", "测试"],
    ["internal", "自用"],
];

export class ZenlenetIpam extends Component {
    static template = "zenlenet_ops.Ipam";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.statuses = STATUSES;
        this.state = useState({
            nodes: [],
            byParent: {},
            expanded: {},
            search: "",
            selectedId: null,
            detail: null,
            loading: false,
            cell: null,
            cellForm: { status: "allocated", partner_id: false, partner_name: "", usage: "" },
            customers: [],
            customerQuery: "",
            assignOpen: false,
            assignQuery: "",
            assignChoices: [],
            selection: [],
        });
        onWillStart(async () => {
            await this.loadTree();
            const first = this.roots[0];
            const wanted = this.props.action?.context?.ipam_prefix_id;
            if (wanted) {
                await this.select(wanted);
            } else if (first) {
                await this.select(first.id);
            }
        });
    }

    // ---------------------------------------------------------------- tree
    async loadTree() {
        const nodes = await this.orm.call("zenlenet.prefix", "ipam_tree", [this.state.search]);
        const byParent = {};
        const ids = new Set(nodes.map((node) => node.id));
        for (const node of nodes) {
            const key = node.parent_id && ids.has(node.parent_id) ? node.parent_id : 0;
            (byParent[key] = byParent[key] || []).push(node);
        }
        this.state.nodes = nodes;
        this.state.byParent = byParent;
        if (this.state.search) {
            for (const node of nodes) {
                this.state.expanded[node.id] = true;
            }
        }
    }

    get roots() {
        return this.state.byParent[0] || [];
    }

    children(node) {
        return this.state.byParent[node.id] || [];
    }

    toggle(node) {
        this.state.expanded[node.id] = !this.state.expanded[node.id];
    }

    isExpanded(node) {
        return !!this.state.expanded[node.id];
    }

    async onSearch(ev) {
        this.state.search = ev.target.value;
        await this.loadTree();
    }

    // -------------------------------------------------------------- detail
    async select(id) {
        this.state.loading = true;
        this.state.selectedId = id;
        this.state.cell = null;
        this.state.selection = [];
        this.state.assignOpen = false;
        try {
            this.state.detail = await this.orm.call("zenlenet.prefix", "ipam_detail", [[id]]);
            let parent = this.state.detail.parent_id;
            while (parent) {
                this.state.expanded[parent] = true;
                const node = this.state.nodes.find((item) => item.id === parent);
                parent = node ? node.parent_id : false;
            }
        } finally {
            this.state.loading = false;
        }
    }

    async refresh() {
        await this.loadTree();
        if (this.state.selectedId) {
            await this.select(this.state.selectedId);
        }
    }

    cellClass(cell) {
        if (cell.special) {
            return "zl-cell zl-cell-special";
        }
        const selected = this.state.selection.includes(cell.ip) ? " zl-cell-selected" : "";
        return `zl-cell zl-cell-${cell.status}${selected}`;
    }

    cellTitle(cell) {
        if (cell.special) {
            return `${cell.ip} · ${cell.special === "network" ? "网络地址" : "广播地址"}`;
        }
        const label = Object.fromEntries(STATUSES)[cell.status] || "未登记";
        return [cell.ip, label, cell.partner, cell.usage].filter(Boolean).join(" · ");
    }

    // ----------------------------------------------------------------- cell
    openCell(cell, ev) {
        if (cell.special) {
            return;
        }
        if (ev && (ev.shiftKey || ev.ctrlKey || ev.metaKey)) {
            const index = this.state.selection.indexOf(cell.ip);
            if (index >= 0) {
                this.state.selection.splice(index, 1);
            } else {
                this.state.selection.push(cell.ip);
            }
            return;
        }
        this.state.cell = cell;
        this.state.cellForm = {
            status: cell.status === "none" ? "allocated" : cell.status,
            partner_id: false,
            partner_name: cell.partner || "",
            usage: cell.usage || "",
        };
        this.state.customers = [];
        this.state.customerQuery = cell.partner || "";
    }

    closeCell() {
        this.state.cell = null;
    }

    async searchCustomers(ev, target) {
        const query = ev.target.value;
        if (target === "assign") {
            this.state.assignQuery = query;
            this.state.assignChoices = await this.orm.call("zenlenet.prefix", "ipam_customers", [query]);
        } else {
            this.state.customerQuery = query;
            this.state.cellForm.partner_name = query;
            this.state.cellForm.partner_id = false;
            this.state.customers = await this.orm.call("zenlenet.prefix", "ipam_customers", [query]);
        }
    }

    pickCustomer(customer) {
        this.state.cellForm.partner_id = customer.id;
        this.state.cellForm.partner_name = customer.name;
        this.state.customerQuery = customer.name;
        this.state.customers = [];
    }

    async saveCell() {
        const form = this.state.cellForm;
        const values = { status: form.status, usage: form.usage };
        if (form.partner_id || !form.partner_name) {
            values.partner_id = form.partner_id || false;
        }
        try {
            await this.orm.call("zenlenet.prefix", "ipam_set_address", [[this.state.selectedId], this.state.cell.ip, values]);
            this.notification.add(`${this.state.cell.ip} 已保存`, { type: "success" });
            this.state.cell = null;
            await this.select(this.state.selectedId);
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
        }
    }

    async bulkStatus(status) {
        if (!this.state.selection.length) {
            return;
        }
        await this.orm.call("zenlenet.prefix", "ipam_bulk_status", [[this.state.selectedId], this.state.selection, status]);
        this.notification.add(`${this.state.selection.length} 个地址已标为${Object.fromEntries(STATUSES)[status]}`, { type: "success" });
        await this.select(this.state.selectedId);
    }

    clearSelection() {
        this.state.selection = [];
    }

    // -------------------------------------------------------------- actions
    async openAssign() {
        this.state.assignOpen = !this.state.assignOpen;
        if (this.state.assignOpen) {
            this.state.assignChoices = await this.orm.call("zenlenet.prefix", "ipam_customers", [""]);
        }
    }

    async assign(customer) {
        await this.orm.call("zenlenet.prefix", "ipam_assign", [[this.state.selectedId], customer ? customer.id : false]);
        this.notification.add(customer ? `已整段分配给 ${customer.name}` : "已整段回收", { type: "success" });
        this.state.assignOpen = false;
        await this.refresh();
    }

    async addPrefix(parent) {
        await this.action.doAction("zenlenet_ops.action_prefix_add", {
            additionalContext: parent
                ? { default_parent_id: parent.id, default_datacenter_id: parent.datacenter_id }
                : {},
            onClose: () => this.refresh(),
        });
    }

    async split() {
        const detail = this.state.detail;
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "zenlenet.prefix.split",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                name: `切割 ${detail.prefix}`,
                context: { default_prefix_id: detail.id, default_new_prefixlen: Math.min((this.selectedNode()?.prefixlen || 24) + 2, detail.family === "4" ? 32 : 64) },
            },
            { onClose: () => this.refresh() },
        );
    }

    selectedNode() {
        return this.state.nodes.find((node) => node.id === this.state.selectedId);
    }

    async openForm() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "zenlenet.prefix",
            res_id: this.state.selectedId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openList() {
        await this.action.doAction("zenlenet_ops.action_prefixes");
    }

    openNetbox() {
        if (this.state.detail?.netbox_url) {
            window.open(this.state.detail.netbox_url, "_blank");
        }
    }
}

registry.category("actions").add("zenlenet_ipam", ZenlenetIpam);
