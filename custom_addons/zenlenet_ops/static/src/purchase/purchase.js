import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const QUEUES = [
    ["plan", "采购计划"],
    ["expected", "设备入库"],
    ["inbound", "设备签收"],
    ["signed", "采购验收"],
];

export class ZenlenetPurchaseBoard extends Component {
    static template = "zenlenet_ops.PurchaseBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.queues = QUEUES;
        this.state = useState({
            queue: "plan",
            query: "",
            rows: [],
        });
        onWillStart(() => this.load());
    }

    async load() {
        const query = this.state.query || "";
        if (this.state.queue === "plan") {
            this.state.rows = await this.orm.call("zenlenet.purchase", "plan_rows", [query]);
        } else {
            this.state.rows = await this.orm.call("zenlenet.purchase.device", "queue_rows", [this.state.queue, query]);
        }
    }

    async pick(queue) {
        this.state.queue = queue;
        await this.load();
    }

    async onQuery(ev) {
        this.state.query = ev.target.value;
    }

    async search() {
        await this.load();
    }

    createPlan() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "采购计划",
            res_model: "zenlenet.purchase",
            views: [[false, "form"]],
        });
    }

    openPlan(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "采购计划",
            res_model: "zenlenet.purchase",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openDevice(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "设备",
            res_model: "zenlenet.purchase.device",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    async step(row) {
        const method = {
            expected: "action_inbound",
            inbound: "action_sign",
            signed: "action_accept",
        }[row.state];
        if (!method) {
            return;
        }
        await this.orm.call("zenlenet.purchase.device", method, [[row.id]]);
        await this.load();
    }

    stepLabel(state) {
        return { expected: "入库", inbound: "签收", signed: "验收" }[state] || "";
    }
}

registry.category("actions").add("zenlenet_purchase_board", ZenlenetPurchaseBoard);
