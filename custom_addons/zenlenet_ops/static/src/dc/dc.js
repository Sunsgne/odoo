import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SITE_STATE = { active: "在用", planning: "规划中", closed: "已退租" };
const PREFIX_STATUS = { active: "在用", container: "容器", reserved: "预留", deprecated: "已弃用" };

export class ZenlenetDatacenter extends Component {
    static template = "zenlenet_ops.Datacenter";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            sites: [],
            search: "",
            selectedId: null,
            detail: null,
            filter: "free",
            pick: null,
            loading: false,
        });
        onWillStart(() => this.refresh());
    }

    async refresh() {
        const sites = await this.orm.call("zenlenet.datacenter", "dc_tree", [this.state.search]);
        this.state.sites = sites;
        const still = sites.some((site) => site.id === this.state.selectedId);
        const next = still ? this.state.selectedId : sites[0]?.id;
        if (next) {
            await this.select(next);
        } else {
            this.state.selectedId = null;
            this.state.detail = null;
            this.state.pick = null;
        }
    }

    async onSearch(ev) {
        this.state.search = ev.target.value;
        await this.refresh();
    }

    get regions() {
        const groups = {};
        for (const site of this.state.sites) {
            const name = site.region || "未分地区";
            groups[name] = groups[name] || { name, sites: [] };
            groups[name].sites.push(site);
        }
        return Object.values(groups).sort((a, b) => a.name.localeCompare(b.name, "zh"));
    }

    async select(id) {
        this.state.loading = true;
        this.state.selectedId = id;
        this.state.pick = null;
        try {
            this.state.detail = await this.orm.call("zenlenet.datacenter", "dc_site", [[id]]);
        } finally {
            this.state.loading = false;
        }
    }

    setFilter(filter) {
        this.state.filter = filter;
        this.state.pick = null;
    }

    get prefixes() {
        return this._visible(this.state.detail?.prefixes || []);
    }

    linesOf(kind) {
        return (this.state.detail?.lines || []).filter((row) => row.kind === kind);
    }

    get privateLines() {
        return this.linesOf("pl");
    }

    get sdwanLines() {
        return this.linesOf("sdwan");
    }

    get vxlanLines() {
        return this.linesOf("vxlan");
    }

    get otherLines() {
        return this.linesOf("private");
    }

    get devices() {
        return this.state.detail?.devices || [];
    }

    get vms() {
        return this.state.detail?.vms || [];
    }

    _visible(rows) {
        if (this.state.filter === "free") {
            return rows.filter((row) => row.sellable);
        }
        if (this.state.filter === "sold") {
            return rows.filter((row) => row.partner);
        }
        return rows;
    }

    pick(kind, row) {
        if (this.state.pick && this.state.pick.kind === kind && this.state.pick.id === row.id) {
            this.state.pick = null;
            return;
        }
        this.state.pick = { kind, id: row.id };
    }

    isPicked(kind, id) {
        return this.state.pick && this.state.pick.kind === kind && this.state.pick.id === id;
    }

    get pickedPrefix() {
        if (this.state.pick?.kind !== "prefix") {
            return null;
        }
        return (this.state.detail?.prefixes || []).find((row) => row.id === this.state.pick.id) || null;
    }

    get pickedLine() {
        if (this.state.pick?.kind !== "line") {
            return null;
        }
        return (this.state.detail?.lines || []).find((row) => row.id === this.state.pick.id) || null;
    }

    get pickedDevice() {
        if (this.state.pick?.kind !== "device") {
            return null;
        }
        return (this.state.detail?.devices || []).find((row) => row.id === this.state.pick.id) || null;
    }

    get pickedVm() {
        if (this.state.pick?.kind !== "vm") {
            return null;
        }
        return (this.state.detail?.vms || []).find((row) => row.id === this.state.pick.id) || null;
    }

    childrenOf(id) {
        return (this.state.detail?.prefixes || []).filter((row) => row.parent_id === id);
    }

    siteState(state) {
        return SITE_STATE[state] || state;
    }

    prefixStatus(status) {
        return PREFIX_STATUS[status] || status;
    }

    async openTicket(move) {
        const action = await this.orm.call("zenlenet.datacenter", "dc_open_ticket", [[this.state.selectedId], move]);
        await this.action.doAction(action, { onClose: () => this.select(this.state.selectedId) });
    }

    async addLine(kind) {
        const context = {
            default_kind: kind,
            default_datacenter_id: this.state.selectedId,
            default_status: "planned",
        };
        if (kind === "sdwan") {
            context.default_region = this.state.detail?.region_name || false;
        } else {
            context.default_a_site_id = this.state.selectedId;
        }
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "zenlenet.line",
                views: [[false, "form"]],
                target: "new",
                name: kind === "sdwan" ? "SD-WAN" : "专线",
                context,
            },
            { onClose: () => this.select(this.state.selectedId) },
        );
    }

    async openRecord(model, id, name, context) {
        const action = {
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "form"]],
            target: "new",
            name,
            context: context || {},
        };
        if (id) {
            action.res_id = id;
        }
        await this.action.doAction(action, { onClose: () => this.select(this.state.selectedId) });
    }

    async editLine(id) {
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "zenlenet.line",
                res_id: id,
                views: [[false, "form"]],
                target: "new",
                name: "这条线路",
            },
            { onClose: () => this.select(this.state.selectedId) },
        );
    }

    async editSite(id) {
        const action = {
            type: "ir.actions.act_window",
            res_model: "zenlenet.datacenter",
            views: [[false, "form"]],
            target: "new",
            name: id ? "改这个机房" : "新机房",
        };
        if (id) {
            action.res_id = id;
        }
        await this.action.doAction(action, { onClose: () => this.refresh() });
    }

    openNetbox() {
        if (this.state.detail?.netbox_url) {
            window.open(this.state.detail.netbox_url, "_blank");
        }
    }
}

registry.category("actions").add("zenlenet_datacenter", ZenlenetDatacenter);
