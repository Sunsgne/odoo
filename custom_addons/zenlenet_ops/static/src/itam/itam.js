import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ZenlenetItam extends Component {
    static template = "zenlenet_ops.Itam";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ board: null, category: "" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.board = await this.orm.call("zenlenet.asset", "itam_board", [this.state.category || false]);
    }

    async pickCategory(key) {
        if (this.state.category === key && key) {
            this.openCategory(key);
            return;
        }
        this.state.category = key;
        await this.load();
    }

    openCategory(key) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "资产",
            res_model: "zenlenet.asset",
            views: [[false, "list"], [false, "form"]],
            domain: [["category", "=", key]],
        });
    }

    openAssets() {
        this.action.doAction("zenlenet_ops.action_assets");
    }

    openTasks() {
        this.action.doAction("zenlenet_ops.action_asset_tasks");
    }

    openTask(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "任务",
            res_model: "zenlenet.asset.task",
            res_id: id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("zenlenet_itam", ZenlenetItam);
