/** @odoo-module **/
// Part of Otomater. See LICENSE file for full copyright and licensing details.

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, onWillStart, useState } from "@odoo/owl";

const OPEN_STATES = ["new", "assigned", "accepted", "in_progress"];

export class SwmDashboard extends Component {
    static template = "smart_waste_management.SwmDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            kpi: {
                total: 0,
                available: 0,
                nearly_full: 0,
                full: 0,
                pending: 0,
                offline: 0,
                maintenance: 0,
                open_requests: 0,
                escalated: 0,
                complaints_open: 0,
                avg_response: 0,
            },
            byStatus: [],
            byCorporation: [],
            recentRequests: [],
            isManager: false,
        });
        onWillStart(async () => {
            this.state.isManager = await user.hasGroup(
                "smart_waste_management.group_swm_manager");
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        const orm = this.orm;

        // Bins grouped by status
        const statusGroups = await orm.formattedReadGroup(
            "otm.swm.bin",
            [["active", "=", true]],
            ["status"],
            ["__count"],
        );
        const counts = {};
        let total = 0;
        for (const g of statusGroups) {
            const key = g.status && g.status[0] ? g.status[0] : g.status;
            const cnt = g.__count || 0;
            counts[key] = cnt;
            total += cnt;
        }
        const kpi = this.state.kpi;
        kpi.total = total;
        kpi.available = (counts.available || 0) + (counts.collected || 0);
        kpi.nearly_full = counts.nearly_full || 0;
        kpi.full = counts.full || 0;
        kpi.pending =
            (counts.collection_pending || 0) +
            (counts.collection_in_progress || 0);
        kpi.offline = counts.offline || 0;
        kpi.maintenance = counts.maintenance || 0;
        this.state.byStatus = Object.entries(counts).map(([k, v]) => ({
            status: k,
            count: v,
        }));

        // Open / escalated requests
        kpi.open_requests = await orm.searchCount(
            "otm.swm.collection.request",
            [["state", "in", OPEN_STATES]]);
        kpi.escalated = await orm.searchCount(
            "otm.swm.collection.request",
            [["state", "in", OPEN_STATES], ["escalation_level", ">", 0]]);
        kpi.complaints_open = await orm.searchCount(
            "otm.swm.complaint",
            [["state", "in", ["new", "assigned", "in_progress"]]]);

        // Average response time from history
        const respGroups = await orm.formattedReadGroup(
            "otm.swm.collection.history",
            [],
            [],
            ["response_hours:avg"],
        );
        if (respGroups.length) {
            kpi.avg_response = Math.round(
                (respGroups[0]["response_hours:avg"] || 0) * 10) / 10;
        }

        // Per-corporation drill-down table
        const corpGroups = await orm.formattedReadGroup(
            "otm.swm.bin",
            [["active", "=", true]],
            ["corporation_id"],
            ["__count"],
        );
        const fullGroups = await orm.formattedReadGroup(
            "otm.swm.bin",
            [
                ["active", "=", true],
                ["status", "in",
                    ["full", "collection_pending", "collection_in_progress"]],
            ],
            ["corporation_id"],
            ["__count"],
        );
        const fullByCorp = {};
        for (const g of fullGroups) {
            const cid = g.corporation_id ? g.corporation_id[0] : 0;
            fullByCorp[cid] = g.__count || 0;
        }
        this.state.byCorporation = corpGroups.map((g) => {
            const cid = g.corporation_id ? g.corporation_id[0] : 0;
            return {
                id: cid,
                name: g.corporation_id
                    ? g.corporation_id[1]
                    : "Unassigned",
                bins: g.__count || 0,
                full: fullByCorp[cid] || 0,
            };
        });

        // Recent open requests
        this.state.recentRequests = await orm.searchRead(
            "otm.swm.collection.request",
            [["state", "in", OPEN_STATES]],
            ["name", "bin_code", "street_id", "staff_id", "state",
                "escalation_level", "full_detected_time"],
            { limit: 10, order: "full_detected_time asc" },
        );
        this.state.loading = false;
    }

    statusLabel(status) {
        const labels = {
            available: "Available",
            nearly_full: "Nearly Full",
            full: "Full",
            collection_pending: "Collection Pending",
            collection_in_progress: "Collection In Progress",
            collected: "Empty / Collected",
            offline: "Offline",
            maintenance: "Maintenance",
        };
        return labels[status] || status;
    }

    openBins(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Smart Bins",
            res_model: "otm.swm.bin",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openRequests(domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Collection Requests",
            res_model: "otm.swm.collection.request",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openComplaints() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Complaints",
            res_model: "otm.swm.complaint",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["new", "assigned", "in_progress"]]],
            target: "current",
        });
    }

    openRequest(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.swm.collection.request",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onKpiTotal() { this.openBins([["active", "=", true]]); }
    onKpiAvailable() {
        this.openBins(
            [["status", "in", ["available", "collected"]]],
            "Available Bins");
    }
    onKpiNearlyFull() {
        this.openBins([["status", "=", "nearly_full"]], "Nearly Full Bins");
    }
    onKpiFull() { this.openBins([["status", "=", "full"]], "Full Bins"); }
    onKpiPending() {
        this.openBins(
            [["status", "in",
                ["collection_pending", "collection_in_progress"]]],
            "Pending Collection");
    }
    onKpiOffline() {
        this.openBins([["status", "=", "offline"]], "Offline Bins");
    }
    onKpiOpenRequests() {
        this.openRequests([["state", "in", OPEN_STATES]]);
    }
    onKpiEscalated() {
        this.openRequests(
            [["state", "in", OPEN_STATES], ["escalation_level", ">", 0]]);
    }
    onCorpRow(corpId) {
        this.openBins(
            [["corporation_id", "=", corpId], ["active", "=", true]]);
    }

    async refresh() {
        await this.loadData();
    }
}

registry.category("actions").add("swm_dashboard", SwmDashboard);
