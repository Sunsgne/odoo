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
            drag: null,
            bulkAssign: null,
            bulkReserve: null,
            pendingFlows: [],
            bulkCustomerQuery: "",
            bulkCustomers: [],
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

    /** 地区 → AS → 顶级 IP 段 → IP 小段 */
    get regionGroups() {
        const groups = {};
        for (const node of this.roots) {
            const region = node.region || "未分地区";
            const asn = node.asn ? `AS${node.asn}` : "未填 AS";
            groups[region] = groups[region] || { name: region, asns: {}, count: 0 };
            const bucket = groups[region];
            bucket.asns[asn] = bucket.asns[asn] || { name: asn, nodes: [] };
            bucket.asns[asn].nodes.push(node);
            bucket.count += 1;
        }
        return Object.values(groups)
            .sort((a, b) => a.name.localeCompare(b.name, "zh"))
            .map((group) => ({ ...group, asns: Object.values(group.asns).sort((a, b) => a.name.localeCompare(b.name)) }));
    }

    groupKey(...parts) {
        return "g:" + parts.join("/");
    }

    isGroupOpen(key) {
        return this.state.expanded[key] !== false;
    }

    toggleGroup(key) {
        this.state.expanded[key] = !this.isGroupOpen(key);
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
        this.state.bulkAssign = null;
        this.state.bulkReserve = null;
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

    prefixStatus(status) {
        return { active: "在用", container: "容器", reserved: "预留", deprecated: "已弃用" }[status] || status;
    }

    cellClass(cell, block, index) {
        if (cell.special) {
            return "zl-cell zl-cell-special";
        }
        const selected = this.state.selection.includes(cell.ip) || (block && this.isInDrag(block, index)) ? " zl-cell-selected" : "";
        return `zl-cell zl-cell-${cell.status}${selected}`;
    }

    cellTitle(cell) {
        if (cell.special) {
            return `${cell.ip} · ${cell.special === "network" ? "网络地址" : "广播地址"}`;
        }
        const label = Object.fromEntries(STATUSES)[cell.status] || "未登记";
        return [cell.ip, label, cell.partner, cell.usage].filter(Boolean).join(" · ");
    }

    // ------------------------------------------------------------ drag select
    onCellDown(block, index, cell, ev) {
        if (cell.special || ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        this.state.drag = { block: block.prefix, start: index, end: index, additive: ev.shiftKey || ev.ctrlKey || ev.metaKey, moved: false };
    }

    onCellEnter(block, index) {
        const drag = this.state.drag;
        if (!drag || drag.block !== block.prefix) {
            return;
        }
        if (index !== drag.end) {
            drag.moved = true;
        }
        drag.end = index;
    }

    onGridUp(block, ev) {
        const drag = this.state.drag;
        this.state.drag = null;
        if (!drag || drag.block !== block.prefix) {
            return;
        }
        const [from, to] = drag.start <= drag.end ? [drag.start, drag.end] : [drag.end, drag.start];
        const range = block.cells.slice(from, to + 1).filter((cell) => !cell.special).map((cell) => cell.ip);
        if (!drag.moved && !drag.additive) {
            // a plain click opens the single-address editor
            this.openCell(block.cells[drag.start], { shiftKey: false });
            return;
        }
        if (!drag.additive) {
            this.state.selection = range;
            return;
        }
        for (const ip of range) {
            const at = this.state.selection.indexOf(ip);
            if (at >= 0 && !drag.moved) {
                this.state.selection.splice(at, 1);
            } else if (at < 0) {
                this.state.selection.push(ip);
            }
        }
    }

    isInDrag(block, index) {
        const drag = this.state.drag;
        if (!drag || drag.block !== block.prefix) {
            return false;
        }
        const [from, to] = drag.start <= drag.end ? [drag.start, drag.end] : [drag.end, drag.start];
        return index >= from && index <= to;
    }

    selectAllFree(block) {
        this.state.selection = block.cells.filter((cell) => !cell.special && (cell.status === "free" || cell.status === "none")).map((cell) => cell.ip);
    }

    // --------------------------------------------------------- bulk assign
    async openBulkAssign() {
        this.state.bulkReserve = null;
        this.state.bulkAssign = { flow_id: false, partner_id: false, partner_name: "", usage: "" };
        this.state.pendingFlows = await this.orm.call("zenlenet.prefix", "ipam_pending_flows", []);
        this.state.bulkCustomers = [];
        this.state.bulkCustomerQuery = "";
    }

    closeBulkAssign() {
        this.state.bulkAssign = null;
    }

    pickFlow(flow) {
        this.state.bulkAssign.flow_id = flow.id;
        this.state.bulkAssign.partner_id = flow.partner_id;
        this.state.bulkAssign.partner_name = flow.partner;
    }

    async searchBulkCustomers(ev) {
        const query = ev.target.value;
        this.state.bulkCustomerQuery = query;
        const target = this.state.bulkReserve || this.state.bulkAssign;
        if (target) {
            target.partner_id = false;
            target.partner_name = query;
        }
        if (this.state.bulkAssign) {
            this.state.bulkAssign.flow_id = false;
        }
        this.state.bulkCustomers = await this.orm.call("zenlenet.prefix", "ipam_customers", [query]);
    }

    pickBulkCustomer(customer) {
        const target = this.state.bulkReserve || this.state.bulkAssign;
        if (!target) {
            return;
        }
        target.partner_id = customer.id;
        target.partner_name = customer.name;
        this.state.bulkCustomerQuery = customer.name;
        this.state.bulkCustomers = [];
    }

    async openBulkReserve() {
        this.state.bulkAssign = null;
        this.state.bulkReserve = { partner_id: false, partner_name: "" };
        this.state.bulkCustomerQuery = "";
        this.state.bulkCustomers = await this.orm.call("zenlenet.prefix", "ipam_customers", [""]);
    }

    closeBulkReserve() {
        this.state.bulkReserve = null;
        this.state.bulkCustomers = [];
    }

    async confirmBulkReserve() {
        const form = this.state.bulkReserve;
        if (!form?.partner_id) {
            this.notification.add("预分配要先从列表里点选客户。", { type: "warning" });
            return;
        }
        try {
            const result = await this.orm.call("zenlenet.prefix", "ipam_bulk_reserve", [[this.state.selectedId], this.state.selection, form.partner_id]);
            this.notification.add(`已把 ${result.count} 个地址预分配给 ${result.partner}`, { type: "success" });
            this.state.bulkReserve = null;
            this.state.selection = [];
            await this.select(this.state.selectedId);
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
        }
    }

    async confirmBulkAssign() {
        const form = this.state.bulkAssign;
        if (!form.flow_id) {
            this.notification.add("请选一张处于「分配资源」的开通工单。没有的话先开一张。", { type: "warning" });
            return;
        }
        try {
            const result = await this.orm.call("zenlenet.prefix", "ipam_bulk_assign", [[this.state.selectedId], this.state.selection, form.partner_id || false, form.flow_id || false, form.usage || ""]);
            this.notification.add(`${result.count} 个地址已分配${result.flow ? "，并挂到交付工单 " + result.flow : ""}`, { type: "success" });
            this.state.bulkAssign = null;
            this.state.selection = [];
            await this.select(this.state.selectedId);
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
        }
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
            partner_id: cell.partner_id || false,
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

    get ticketLocked() {
        return ["allocated", "testing", "returning", "transferring"].includes(this.state.cell?.status);
    }

    async openTicket(move) {
        try {
            const action = await this.orm.call("zenlenet.prefix", "ipam_open_ticket", [[this.state.selectedId], this.state.selection, move]);
            this.state.bulkAssign = null;
            this.state.selection = [];
            await this.action.doAction(action, { onClose: () => this.select(this.state.selectedId) });
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
        }
    }

    async openPrefixTicket(move) {
        try {
            const action = await this.orm.call("zenlenet.prefix", "ipam_open_prefix_ticket", [[this.state.selectedId], move]);
            await this.action.doAction(action, { onClose: () => this.select(this.state.selectedId) });
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
        }
    }

    async saveCell() {
        const form = this.state.cellForm;
        if (form.status === "reserved" && !form.partner_id) {
            this.notification.add("预分配要先从列表里点选客户。", { type: "warning" });
            return;
        }
        const values = { usage: form.usage };
        if (!this.ticketLocked) {
            values.status = form.status;
            if (form.status === "reserved" || form.partner_id || !form.partner_name) {
                values.partner_id = form.partner_id || false;
            }
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
        try {
            await this.orm.call("zenlenet.prefix", "ipam_bulk_status", [[this.state.selectedId], this.state.selection, status]);
        } catch (error) {
            this.notification.add(error.data?.message || String(error), { type: "danger" });
            return;
        }
        this.notification.add(`${this.state.selection.length} 个地址已标为${Object.fromEntries(STATUSES)[status]}`, { type: "success" });
        this.state.selection = [];
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
