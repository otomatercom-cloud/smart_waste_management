# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models
from odoo.tools import _

COMPLAINT_TYPES = [
    ("waste_outside", "Waste Outside Bin"),
    ("damaged", "Bin Damaged"),
    ("smell", "Bad Smell"),
    ("dumping", "Unauthorized Dumping"),
    ("sensor", "Sensor Not Working"),
    ("overflowing", "Bin Overflowing"),
    ("other", "Other"),
]


class SwmComplaint(models.Model):
    _name = "otm.swm.complaint"
    _description = "Waste Bin Complaint"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(
        string="Complaint Number", readonly=True, copy=False,
        default=lambda self: _("New"))
    bin_id = fields.Many2one("otm.swm.bin", string="Smart Bin", index=True)
    street_id = fields.Many2one(
        related="bin_id.street_id", store=True, readonly=True)
    association_id = fields.Many2one(
        related="bin_id.association_id", store=True, readonly=True)
    corporation_id = fields.Many2one(
        related="bin_id.corporation_id", store=True, readonly=True)
    complaint_type = fields.Selection(
        COMPLAINT_TYPES, required=True, default="other", tracking=True)
    description = fields.Text()
    photo = fields.Binary(string="Photo Attachment", attachment=True)
    reported_by_name = fields.Char(string="Reported By")
    reported_by_partner_id = fields.Many2one("res.partner",
                                             string="Reporter Contact")
    report_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    is_public = fields.Boolean(
        string="Reported from Public QR Page", readonly=True)
    reporter_ip = fields.Char(readonly=True,
                              groups="smart_waste_management.group_swm_manager")
    assigned_user_id = fields.Many2one(
        "res.users", string="Assigned To", tracking=True)
    state = fields.Selection([
        ("new", "New"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ], default="new", tracking=True, index=True)
    resolution = fields.Text()
    resolution_date = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "otm.swm.complaint") or "/"
        return super().create(vals_list)

    def action_assign(self):
        for rec in self:
            rec.write({"state": "assigned",
                       "assigned_user_id": rec.assigned_user_id.id
                       or self.env.user.id})
        return True

    def action_start(self):
        self.write({"state": "in_progress"})
        return True

    def action_resolve(self):
        self.write({"state": "resolved",
                    "resolution_date": fields.Datetime.now()})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True
