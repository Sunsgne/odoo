import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PROMPTS = [
    "今早先处理什么",
    "超时工单有哪些",
    "未收款客户",
    "待续签合同",
    "待分配资源",
    "本周排班缺口",
];

export class ZenlenetCopilot extends Component {
    static template = "zenlenet_ops.Copilot";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            query: PROMPTS[0],
            active: PROMPTS[0],
            hits: [],
            busy: false,
        });
        this.prompts = PROMPTS;
    }

    pick(text) {
        this.state.active = text;
        this.state.query = text;
    }

    onInput(ev) {
        this.state.query = ev.target.value;
    }

    async ask(ev) {
        ev?.preventDefault?.();
        const text = (this.state.query || "").trim();
        if (!text) {
            return;
        }
        this.state.busy = true;
        try {
            this.state.hits = (await this.orm.call("zenlenet.home", "lookup", [text])) || [];
        } catch {
            this.state.hits = [];
        } finally {
            this.state.busy = false;
        }
    }

    async open(hit) {
        if (hit?.action) {
            await this.action.doAction(hit.action);
        }
    }
}

registry.category("actions").add("zenlenet_copilot", ZenlenetCopilot);
