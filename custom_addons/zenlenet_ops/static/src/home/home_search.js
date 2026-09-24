import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class HomeSearch extends Component {
    static template = "zenlenet_ops.HomeSearch";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ rows: [] });
        this.token = 0;
        this.timer = 0;
    }

    onInput(ev) {
        const text = (ev.target.value || "").trim();
        this.token += 1;
        const mine = this.token;
        if (this.timer) {
            clearTimeout(this.timer);
        }
        if (!text) {
            this.state.rows = [];
            return;
        }
        this.timer = setTimeout(() => this.run(text, mine), 200);
    }

    async run(text, mine) {
        let rows = [];
        try {
            rows = await this.orm.call("zenlenet.home", "lookup", [text]);
        } catch {
            rows = [];
        }
        if (mine !== this.token) {
            return;
        }
        this.state.rows = rows || [];
    }

    async open(row) {
        if (!row || !row.action) {
            return;
        }
        await this.action.doAction(row.action);
    }
}

registry.category("fields").add("zenlenet_home_search", {
    component: HomeSearch,
    supportedTypes: ["char"],
});
