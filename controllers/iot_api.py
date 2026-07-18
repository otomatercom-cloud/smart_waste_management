# Part of Otomater. See LICENSE file for full copyright and licensing details.
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json_response(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        headers=[("Content-Type", "application/json")],
        status=status,
    )


class SwmIotApi(http.Controller):
    """Plain-HTTP JSON endpoint for ESP32 devices.

    Deliberately NOT an Odoo `type="json"` route: Odoo 19 json routes
    expect a JSON-RPC 2.0 envelope, which is awkward from microcontroller
    firmware. The device posts a flat JSON body and receives flat JSON.
    """

    @http.route("/api/smart_waste/bin/status", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    def bin_status(self, **kwargs):
        try:
            payload = json.loads(
                request.httprequest.get_data(as_text=True) or "{}")
        except (ValueError, TypeError):
            return _json_response(
                {"result": "error", "message": "Invalid JSON body"}, 400)

        device_id = str(payload.get("device_id") or "").strip()
        bin_code = str(payload.get("bin_code") or "").strip()
        token = str(
            payload.get("api_token")
            or request.httprequest.headers.get("X-SWM-Token") or "").strip()

        if not (device_id and bin_code and token):
            return _json_response(
                {"result": "error",
                 "message": "device_id, bin_code and api_token required"},
                400)

        env = request.env(su=True)
        bin_rec = env["otm.swm.bin"].search(
            [("code", "=", bin_code)], limit=1)
        valid = bool(
            bin_rec
            and bin_rec.device_id == device_id
            and bin_rec.api_token
            and hmac.compare_digest(bin_rec.api_token, token))
        if not valid:
            _logger.warning(
                "SWM IoT auth failure: device=%s bin=%s ip=%s",
                device_id, bin_code,
                request.httprequest.remote_addr)
            # Do not leak which of the three factors was wrong.
            return _json_response(
                {"result": "error", "message": "Authentication failed"}, 401)
        if not bin_rec.active:
            return _json_response(
                {"result": "error", "message": "Bin is inactive"}, 403)

        def _num(key):
            val = payload.get(key)
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        result = bin_rec.process_reading(
            distance_cm=_num("distance_cm"),
            fill_percentage=_num("fill_percentage"),
            device_status=str(payload.get("device_status") or "online"),
            battery_level=_num("battery_level"),
            signal_strength=_num("signal_strength"),
            raw=json.dumps(payload)[:2000],
        )
        status = 200 if result.get("result") == "ok" else 400
        return _json_response(result, status)
