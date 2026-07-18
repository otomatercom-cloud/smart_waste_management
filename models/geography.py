# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmCorporation(models.Model):
    _name = "otm.swm.corporation"
    _description = "Corporation / Municipality"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string="Unique Code", required=True, copy=False)
    body_type = fields.Selection([
        ("corporation", "Corporation"),
        ("municipality", "Municipality"),
        ("panchayat", "Panchayat"),
    ], string="Type", required=True, default="municipality", tracking=True)
    district = fields.Char()
    state_id = fields.Many2one("res.country.state", string="State")
    country_id = fields.Many2one(
        "res.country", string="Country",
        default=lambda self: self.env.ref("base.in", raise_if_not_found=False))
    officer_id = fields.Many2one(
        "res.users", string="Responsible Officer", tracking=True)
    phone = fields.Char(string="Contact Number")
    email = fields.Char()
    active = fields.Boolean(default=True)

    zone_ids = fields.One2many("otm.swm.zone", "corporation_id", string="Zones")
    association_ids = fields.One2many(
        "otm.swm.association", "corporation_id", string="Associations")
    street_ids = fields.One2many(
        "otm.swm.street", "corporation_id", string="Streets")
    bin_ids = fields.One2many("otm.swm.bin", "corporation_id", string="Bins")

    association_count = fields.Integer(
        compute="_compute_counts", string="Total Associations")
    street_count = fields.Integer(compute="_compute_counts", string="Total Streets")
    bin_count = fields.Integer(
        compute="_compute_bin_counts", store=True, string="Total Bins")
    full_bin_count = fields.Integer(
        compute="_compute_bin_counts", store=True, string="Full Bins")
    available_bin_count = fields.Integer(
        compute="_compute_bin_counts", store=True, string="Available Bins")
    pending_collection_count = fields.Integer(
        compute="_compute_bin_counts", store=True,
        string="Bins Awaiting Collection")
    avg_response_hours = fields.Float(
        compute="_compute_avg_response", string="Avg. Collection Response (h)")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Corporation code must be unique."),
    ]

    def _compute_counts(self):
        for rec in self:
            rec.association_count = len(rec.association_ids)
            rec.street_count = len(rec.street_ids)

    @api.depends("bin_ids", "bin_ids.status", "bin_ids.active")
    def _compute_bin_counts(self):
        for rec in self:
            bins = rec.bin_ids.filtered("active")
            rec.bin_count = len(bins)
            rec.full_bin_count = len(bins.filtered(
                lambda b: b.status == "full"))
            rec.available_bin_count = len(bins.filtered(
                lambda b: b.status == "available"))
            rec.pending_collection_count = len(bins.filtered(
                lambda b: b.status in ("collection_pending",
                                       "collection_in_progress")))

    def _compute_avg_response(self):
        History = self.env["otm.swm.collection.history"]
        for rec in self:
            data = History._read_group(
                [("corporation_id", "=", rec.id),
                 ("response_hours", ">", 0)],
                [], ["response_hours:avg"])
            rec.avg_response_hours = data[0][0] or 0.0 if data else 0.0

    def action_view_zones(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Zones",
            "res_model": "otm.swm.zone",
            "view_mode": "list,form",
            "domain": [("corporation_id", "=", self.id)],
            "context": {"default_corporation_id": self.id},
        }

    def action_view_bins(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Smart Bins",
            "res_model": "otm.swm.bin",
            "view_mode": "kanban,list,form",
            "domain": [("corporation_id", "=", self.id)],
            "context": {"default_corporation_id": self.id},
        }


class SwmZone(models.Model):
    _name = "otm.swm.zone"
    _description = "Zone"
    _order = "corporation_id, name"

    name = fields.Char(required=True)
    code = fields.Char(copy=False)
    corporation_id = fields.Many2one(
        "otm.swm.corporation", required=True, ondelete="cascade",
        string="Corporation / Municipality")
    manager_id = fields.Many2one("res.users", string="Zone Manager")
    active = fields.Boolean(default=True)
    ward_ids = fields.One2many("otm.swm.ward", "zone_id", string="Wards")
    ward_count = fields.Integer(compute="_compute_ward_count")

    def _compute_ward_count(self):
        for rec in self:
            rec.ward_count = len(rec.ward_ids)

    def action_view_wards(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Wards",
            "res_model": "otm.swm.ward",
            "view_mode": "list,form",
            "domain": [("zone_id", "=", self.id)],
            "context": {"default_zone_id": self.id,
                        "default_corporation_id": self.corporation_id.id},
        }


class SwmWard(models.Model):
    _name = "otm.swm.ward"
    _description = "Ward"
    _order = "zone_id, ward_number, name"

    name = fields.Char(string="Ward Name", required=True)
    ward_number = fields.Char(string="Ward Number")
    zone_id = fields.Many2one(
        "otm.swm.zone", required=True, ondelete="cascade", string="Zone")
    corporation_id = fields.Many2one(
        related="zone_id.corporation_id", store=True, readonly=True,
        string="Corporation / Municipality")
    officer_id = fields.Many2one("res.users", string="Responsible Officer")
    phone = fields.Char(string="Contact Number")
    email = fields.Char()
    active = fields.Boolean(default=True)
    association_ids = fields.One2many(
        "otm.swm.association", "ward_id", string="Associations")
    association_count = fields.Integer(compute="_compute_association_count")

    def _compute_association_count(self):
        for rec in self:
            rec.association_count = len(rec.association_ids)

    def action_view_associations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Associations",
            "res_model": "otm.swm.association",
            "view_mode": "list,form",
            "domain": [("ward_id", "=", self.id)],
            "context": {"default_ward_id": self.id,
                        "default_zone_id": self.zone_id.id,
                        "default_corporation_id": self.corporation_id.id},
        }
