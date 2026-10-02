import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ZenlenetDuty extends Component {
    static template = "zenlenet_ops.Duty";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const context = this.props.action?.context || {};
        this.state = useState({
            board: null,
            panel: context.duty_panel || "calendar",
            regionId: false,
            userId: false,
            shiftId: false,
            kind: false,
            cell: null,
            pref: { week_start: "sun", prefer: "any" },
        });
        onWillStart(() => this.load());
    }

    async load(anchor) {
        const board = this.state.board;
        const next = await this.orm.call("zenlenet.duty.sheet", "calendar", [], {
            sheet_id: board?.sheet_id || false,
            anchor: anchor || board?.anchor || false,
            mode: board?.mode || "week",
            region_id: this.state.regionId || false,
            user_id: this.state.userId || false,
            shift_id: this.state.shiftId || false,
            kind: this.state.kind || false,
        });
        this.state.board = next;
        this.state.pref = next.preference || this.state.pref;
    }

    weeks() {
        const days = this.state.board?.days || [];
        const rows = [];
        for (let index = 0; index < days.length; index += 7) {
            rows.push(days.slice(index, index + 7));
        }
        return rows;
    }

    async pickSheet(id) {
        this.state.board.sheet_id = id;
        this.state.cell = null;
        await this.load();
    }

    async setMode(mode) {
        this.state.board.mode = mode;
        this.state.cell = null;
        await this.load();
    }

    iso(day) {
        const month = String(day.getMonth() + 1).padStart(2, "0");
        const date = String(day.getDate()).padStart(2, "0");
        return `${day.getFullYear()}-${month}-${date}`;
    }

    async move(step) {
        const anchor = this.state.board?.anchor;
        if (!anchor) {
            return;
        }
        const day = new Date(`${anchor}T00:00:00`);
        if (this.state.board.mode === "month") {
            day.setMonth(day.getMonth() + step, 1);
        } else {
            day.setDate(day.getDate() + step * 7);
        }
        this.state.cell = null;
        await this.load(this.iso(day));
    }

    async today() {
        this.state.cell = null;
        await this.load(this.iso(new Date()));
    }

    async onAnchor(ev) {
        this.state.cell = null;
        await this.load(ev.target.value);
    }

    async onRegion(ev) {
        this.state.regionId = Number(ev.target.value) || false;
        this.state.cell = null;
        await this.load();
    }

    async onShift(ev) {
        this.state.shiftId = Number(ev.target.value) || false;
        this.state.cell = null;
        await this.load();
    }

    async onUser(ev) {
        this.state.userId = Number(ev.target.value) || false;
        this.state.cell = null;
        await this.load();
    }

    async onKind(ev) {
        this.state.kind = ev.target.value || false;
        this.state.cell = null;
        await this.load();
    }

    async openCell(shift) {
        if (!shift.cell_id || !this.state.board?.can_edit) {
            return;
        }
        this.state.cell = await this.orm.call("zenlenet.duty.cell", "detail", [[shift.cell_id]]);
        this.state.panel = "calendar";
    }

    async toggle(person) {
        const cell = this.state.cell;
        if (!cell) {
            return;
        }
        await this.orm.call("zenlenet.duty.cell", "set_member", [[cell.cell_id], person.id, !person.on]);
        this.state.cell = await this.orm.call("zenlenet.duty.cell", "detail", [[cell.cell_id]]);
        await this.load();
    }

    async setNeed(ev) {
        const cell = this.state.cell;
        if (!cell) {
            return;
        }
        await this.orm.call("zenlenet.duty.cell", "set_need", [[cell.cell_id], Number(ev.target.value || 0)]);
        await this.load();
    }

    closeCell() {
        this.state.cell = null;
    }

    async savePref() {
        this.state.pref = await this.orm.call("zenlenet.duty.preference", "save_mine", [], {
            week_start: this.state.pref.week_start,
            prefer: this.state.pref.prefer,
        });
        await this.load();
        this.state.panel = "calendar";
    }

    show(panel) {
        this.state.panel = panel;
    }

    openSheets() {
        this.action.doAction("zenlenet_ops.action_duty_sheets");
    }

    openShifts() {
        this.action.doAction("zenlenet_ops.action_duty_shifts");
    }

    openSwap() {
        const cell = this.state.cell;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "换班",
            res_model: "zenlenet.duty.swap",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_sheet_id: this.state.board?.sheet_id || false,
                default_date: cell?.date || this.state.board?.anchor,
                default_from_shift_id: cell?.shift_id || false,
            },
        });
    }
}

registry.category("actions").add("zenlenet_duty", ZenlenetDuty);
