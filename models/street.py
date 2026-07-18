# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmStreet(models.Model):
    _name = "otm.swm.street"
    _description = "Street"
    _order = "association_id, name"

    name = fields.Char(string="Street Name", required=True)
    code = fields.Char(string="Street Code", copy=False)
    association_id = fields.Many2one(
        "otm.swm.association", required=True, ondelete="cascade",
        string="Association")
    ward_id = fields.Many2one(
        related="association_id.ward_id", store=True, readonly=True,
        string="Ward")
    zone_id = fields.Many2one(
        related="association_id.zone_id", store=True, readonly=True,
        string="Zone")
    corporation_id = fields.Many2one(
        related="association_id.corporation_id", store=True, readonly=True,
        string="Corporation / Municipality")
    responsible_partner_id = fields.Many2one(
        "res.partner", string="Responsible Person")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    location_note = fields.Char(string="GPS / Location Information")
    active = fields.Boolean(default=True)

    bin_ids = fields.One2many("otm.swm.bin", "street_id", string="Bins")
    bin_count = fields.Integer(
        compute="_compute_bin_count", store=True, string="Bins #")

    @api.depends("bin_ids", "bin_ids.active")
    def _compute_bin_count(self):
        for rec in self:
            rec.bin_count = len(rec.bin_ids.filtered("active"))

    def action_view_bins(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Smart Bins",
            "res_model": "otm.swm.bin",
            "view_mode": "kanban,list,form",
            "domain": [("street_id", "=", self.id)],
            "context": {"default_street_id": self.id,
                        "default_association_id": self.association_id.id},
        }
