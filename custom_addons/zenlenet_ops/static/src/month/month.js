import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const FILTERS = [
    { id: "all", label: "全部" },
    { id: "attention", label: "要处理" },
    { id: "skip", label: "本月不出" },
    { id: "paid", label: "已收清" },
    { id: "quote", label: "报价" },
];
const ATTENTION = new Set([
    "missing", "naked", "no_items", "draft_contract", "unpaid", "partial", "draft", "mixed",
]);

export class ZenlenetMonth extends Component {
    static template = "zenlenet_ops.Month";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.filters = FILTERS;
        this.state = useState({
            period: "",
            title: "",
            todayPeriod: "",
            rows: [],
            totals: [],
            count: 0,
            nakedCount: 0,
            includeHolders: false,
            search: "",
            filter: "all",
            selectedId: null,
            detail: null,
            canBill: false,
            canQuote: false,
            notice: "",
            loading: true,
            busy: false,
        });
        onWillStart(() => this.load(false, 0));
    }

    async load(period, shift) {
        this.state.loading = true;
        try {
            const board = await this.orm.call("zenlenet.contract", "month_board", [
                period || false, shift || 0, this.state.includeHolders,
            ]);
            this.state.period = board.period;
            this.state.title = board.title;
            this.state.todayPeriod = board.today_period;
            this.state.rows = board.rows;
            this.state.totals = board.totals;
            this.state.count = board.count;
            this.state.nakedCount = board.naked_count || 0;
            this.state.canBill = board.can_bill;
            this.state.canQuote = board.can_quote;
            const still = board.rows.some((row) => row.id === this.state.selectedId);
            if (still) {
                await this.select(this.state.selectedId);
            } else {
                this.state.selectedId = null;
                this.state.detail = null;
            }
        } finally {
            this.state.loading = false;
        }
    }

    async reload() {
        await this.load(this.state.period, 0);
    }

    async shift(step) {
        await this.load(this.state.period, step);
    }

    async showHolders(flag) {
        this.state.includeHolders = flag;
        this.state.filter = flag ? "naked" : "all";
        await this.load(this.state.period, 0);
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    _match(row, filter) {
        if (filter === "attention") {
            return ATTENTION.has(row.status);
        }
        if (filter === "all") {
            return true;
        }
        return row.status === filter;
    }

    countOf(filter) {
        return this.state.rows.filter((row) => this._match(row, filter)).length;
    }

    get visible() {
        const query = this.state.search.trim().toLowerCase();
        return this.state.rows.filter((row) => {
            if (!this._match(row, this.state.filter)) {
                return false;
            }
            if (!query) {
                return true;
            }
            return [row.name, row.code, row.sales, row.currency, row.rhythm].join(" ").toLowerCase().includes(query);
        });
    }

    get isCurrent() {
        return this.state.period && this.state.period === this.state.todayPeriod;
    }

    async select(id) {
        this.state.selectedId = id;
        this.state.detail = await this.orm.call("zenlenet.contract", "month_customer", [id, this.state.period]);
    }

    async bill(partnerId) {
        if (partnerId) {
            await this._runBill(partnerId);
            return;
        }
        const ok = window.confirm(`按 ${this.state.title} 给所有执行中的合同出账。已经出过的不会重复。`);
        if (ok) {
            await this._runBill(false);
        }
    }

    async _runBill(partnerId) {
        this.state.busy = true;
        try {
            const result = await this.orm.call("zenlenet.contract", "month_bill", [partnerId || false, this.state.period]);
            this.state.notice = result.message;
            await this.reload();
        } finally {
            this.state.busy = false;
        }
    }

    async post(invoiceId) {
        this.state.busy = true;
        try {
            await this.orm.call("zenlenet.contract", "month_post", [invoiceId]);
            this.state.notice = "账单已确认。";
            await this.reload();
        } finally {
            this.state.busy = false;
        }
    }

    async openRecord(kind, id) {
        const action = await this.orm.call("zenlenet.contract", "month_open", [kind, id]);
        await this.action.doAction(action, { onClose: () => this.reload() });
    }

    async newQuote() {
        const action = await this.orm.call("zenlenet.contract", "month_new_quote", [this.state.selectedId || false]);
        await this.action.doAction(action, { onClose: () => this.reload() });
    }
}

registry.category("actions").add("zenlenet_month", ZenlenetMonth);
