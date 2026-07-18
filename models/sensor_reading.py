# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class SwmSensorReading(models.Model):
    _name = "otm.swm.sensor.reading"
    _description = "Bin Sensor Reading"
    _order = "id desc"

    bin_id = fields.Many2one(
        "otm.swm.bin", required=True, ondelete="cascade", index=True,
        string="Smart Bin")
    bin_code = fields.Char(related="bin_id.code", store=True, string="Bin Code")
    association_id = fields.Many2one(
        related="bin_id.association_id", store=True, readonly=True)
    corporation_id = fields.Many2one(
        related="bin_id.corporation_id", store=True, readonly=True)
    distance_cm = fields.Float(string="Distance (cm)")
    fill_percentage = fields.Float(string="Fill %", aggregator="avg")
    device_status = fields.Char()
    battery_level = fields.Float(string="Battery (%)")
    signal_strength = fields.Float(string="Signal (dBm)")
    raw_payload = fields.Text(string="Raw Payload")
