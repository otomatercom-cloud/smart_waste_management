# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import _


class SwmCollectionRequest(models.Model):
    _name = "otm.swm.collection.request"
    _description = "Waste Collection Request"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(
        string="Request Reference", readonly=True, copy=False,
        default=lambda self: _("New"))
    bin_id = fields.Many2one(
        "otm.swm.bin", required=True, string="Smart Bin", index=True)
    bin_code = fields.Char(related="bin_id.code", store=True, string="Bin Code")
    street_id = fields.Many2one(
        related="bin_id.street_id", store=True, readonly=True)
    association_id = fields.Many2one(
        related="bin_id.association_id", store=True, readonly=True)
    ward_id = fields.Many2one(related="bin_id.ward_id", store=True,
                              readonly=True)
    corporation_id = fields.Many2one(
        related="bin_id.corporation_id", store=True, readonly=True)
    staff_id = fields.Many2one(
        "otm.swm.staff", string="Assigned Staff", tracking=True)
    state = fields.Selection([
        ("new", "New"),
        ("assigned", "Assigned"),
        ("accepted", "Accepted"),
        ("in_progress", "In Progress"),
        ("done", "Completed"),
        ("cancelled", "Cancelled"),
    ], default="new", tracking=True, index=True)

    full_detected_time = fields.Datetime(string="Full Detected", readonly=True)
    accepted_time = fields.Datetime(readonly=True)
    start_time = fields.Datetime(string="Collection Started", readonly=True)
    completed_time = fields.Datetime(string="Collection Completed",
                                     readonly=True)
    sensor_confirmed = fields.Boolean(
        string="Sensor Confirmed Empty", readonly=True)
    manual_completion = fields.Boolean(readonly=True)
    manual_completion_note = fields.Char(readonly=True)
    response_hours = fields.Float(
        string="Response Time (h)", readonly=True, aggregator="avg")
    escalation_level = fields.Integer(
        string="Highest Escalation Sent", readonly=True, default=0)
    fired_rule_ids = fields.Many2many(
        "otm.swm.notification.rule", string="Rules Already Fired",
        help="Prevents the same delay/escalation rule firing twice for this "
             "request unless the rule is configured as recurring.")
    fill_at_request = fields.Float(string="Fill % at Request")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "otm.swm.collection.request") or "/"
            if vals.get("bin_id") and not vals.get("fill_at_request"):
                vals["fill_at_request"] = self.env["otm.swm.bin"].browse(
                    vals["bin_id"]).fill_percentage
            if vals.get("staff_id"):
                vals["state"] = "assigned"
        records = super().create(vals_list)
        return records

    # ------------------------------------------------------------------
    # Workflow buttons
    # ------------------------------------------------------------------
    def action_accept(self):
        for rec in self:
            rec.write({"state": "accepted",
                       "accepted_time": fields.Datetime.now()})
        return True

    def action_start(self):
        for rec in self:
            rec.write({"state": "in_progress",
                       "start_time": fields.Datetime.now()})
            if rec.bin_id.status in ("full", "collection_pending"):
                rec.bin_id.sudo()._change_status("collection_in_progress")
        return True

    def action_mark_done(self, sensor_confirmed=False, note=None):
        now = fields.Datetime.now()
        for rec in self:
            if not sensor_confirmed and not self.env.user.has_group(
                    "smart_waste_management.group_swm_supervisor"):
                raise AccessError(_(
                    "Manual completion requires the Collection Supervisor "
                    "role; normally completion is detected automatically by "
                    "the fill-level sensor."))
            vals = {
                "state": "done",
                "completed_time": now,
                "sensor_confirmed": sensor_confirmed,
                "manual_completion": not sensor_confirmed,
                "manual_completion_note": note,
            }
            if rec.full_detected_time:
                vals["response_hours"] = (
                    now - rec.full_detected_time).total_seconds() / 3600.0
            rec.write(vals)
            if not sensor_confirmed:
                rec.message_post(body=_(
                    "Collection manually marked completed by %s. %s",
                    self.env.user.name, note or ""))
                bin_rec = rec.bin_id.sudo()
                bin_rec.write({
                    "status": "collected",
                    "last_status_change": now,
                    "last_emptied_time": now,
                    "collection_completed_time": now,
                    "full_since": False,
                })
                self.env["otm.swm.notification.rule"].sudo().process_event(
                    "collection_completed", bin_rec, request=rec)
            rec._create_history()
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return True

    def _create_history(self):
        History = self.env["otm.swm.collection.history"].sudo()
        for rec in self:
            History.create({
                "bin_id": rec.bin_id.id,
                "bin_code": rec.bin_id.code,
                "association_id": rec.association_id.id,
                "street_id": rec.street_id.id,
                "corporation_id": rec.corporation_id.id,
                "request_id": rec.id,
                "full_detected_time": rec.full_detected_time,
                "request_time": rec.create_date,
                "staff_id": rec.staff_id.id,
                "accepted_time": rec.accepted_time,
                "start_time": rec.start_time,
                "completed_time": rec.completed_time,
                "sensor_confirmed_time":
                    rec.completed_time if rec.sensor_confirmed else False,
                "response_hours": rec.response_hours,
                "escalation_count": rec.escalation_level,
                "sla_status": "delayed" if rec.escalation_level else "on_time",
            })

    # ------------------------------------------------------------------
    # Escalation cron
    # ------------------------------------------------------------------
    @api.model
    def cron_check_delays(self):
        open_requests = self.search([
            ("state", "in", ("new", "assigned", "accepted", "in_progress")),
            ("full_detected_time", "!=", False),
        ])
        Rule = self.env["otm.swm.notification.rule"].sudo()
        for request in open_requests:
            Rule.process_delayed(request)


class SwmCollectionHistory(models.Model):
    _name = "otm.swm.collection.history"
    _description = "Collection History (permanent record)"
    _order = "id desc"

    bin_id = fields.Many2one("otm.swm.bin", string="Smart Bin", index=True)
    bin_code = fields.Char(string="Bin Code")
    association_id = fields.Many2one("otm.swm.association",
                                     string="Association", index=True)
    street_id = fields.Many2one("otm.swm.street", string="Street")
    corporation_id = fields.Many2one(
        "otm.swm.corporation", string="Corporation / Municipality",
        index=True)
    request_id = fields.Many2one(
        "otm.swm.collection.request", string="Collection Request")
    full_detected_time = fields.Datetime(string="Full Detected")
    request_time = fields.Datetime(string="Collection Requested")
    staff_id = fields.Many2one("otm.swm.staff", string="Staff Assigned")
    accepted_time = fields.Datetime(string="Staff Accepted")
    start_time = fields.Datetime(string="Collection Start")
    completed_time = fields.Datetime(string="Collection Completion")
    sensor_confirmed_time = fields.Datetime(string="Sensor Confirmed Empty")
    response_hours = fields.Float(string="Response Time (h)", aggregator="avg")
    escalation_count = fields.Integer(string="Escalations")
    sla_status = fields.Selection([
        ("on_time", "On Time"),
        ("delayed", "Delayed"),
    ], string="SLA Status")
