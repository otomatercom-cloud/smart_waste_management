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


def _authenticate_bin(env, payload):
    """Shared device+bin+token check used by every IoT endpoint.
    Returns (bin_rec, error_response_or_None)."""
    device_id = str(payload.get("device_id") or "").strip()
    bin_code = str(payload.get("bin_code") or "").strip()
    token = str(
        payload.get("api_token")
        or request.httprequest.headers.get("X-SWM-Token") or "").strip()

    if not (device_id and bin_code and token):
        return None, _json_response(
            {"result": "error",
             "message": "device_id, bin_code and api_token required"}, 400)

    bin_rec = env["otm.swm.bin"].search([("code", "=", bin_code)], limit=1)
    valid = bool(
        bin_rec
        and bin_rec.device_id == device_id
        and bin_rec.api_token
        and hmac.compare_digest(bin_rec.api_token, token))
    if not valid:
        _logger.warning(
            "SWM IoT auth failure: device=%s bin=%s ip=%s",
            device_id, bin_code, request.httprequest.remote_addr)
        # Do not leak which of the three factors was wrong.
        return None, _json_response(
            {"result": "error", "message": "Authentication failed"}, 401)
    if not bin_rec.active:
        return None, _json_response(
            {"result": "error", "message": "Bin is inactive"}, 403)
    return bin_rec, None


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

        env = request.env(su=True)
        bin_rec, err = _authenticate_bin(env, payload)
        if err:
            return err

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
            weight_kg=_num("weight_kg"),
            raw=json.dumps(payload)[:2000],
        )
        status = 200 if result.get("result") == "ok" else 400
        return _json_response(result, status)

    @http.route("/api/smart_waste/bin/rfid-access", type="http",
                auth="none", methods=["POST"], csrf=False,
                save_session=False)
    def bin_rfid_access(self, **kwargs):
        """Called by the ESP32 the instant an RFID card is tapped, BEFORE
        the lock/servo actuates. The device must only open the bin if
        this returns access: "granted" - the physical lock decision
        lives here, not on the device, so revoking a card or letting a
        subscription lapse takes effect instantly without reflashing
        anything.
        """
        try:
            payload = json.loads(
                request.httprequest.get_data(as_text=True) or "{}")
        except (ValueError, TypeError):
            return _json_response(
                {"result": "error", "message": "Invalid JSON body"}, 400)

        env = request.env(su=True)
        bin_rec, err = _authenticate_bin(env, payload)
        if err:
            return err

        card_uid = str(payload.get("card_uid") or "").strip()
        if not card_uid:
            return _json_response(
                {"result": "error", "message": "card_uid required"}, 400)

        weight_kg = None
        raw_weight = payload.get("weight_kg")
        if raw_weight is not None:
            try:
                weight_kg = float(raw_weight)
            except (TypeError, ValueError):
                weight_kg = None

        outcome = bin_rec.check_rfid_access(card_uid, weight_kg=weight_kg)
        return _json_response({"result": "ok", **outcome}, 200)

    @http.route("/api/smart_waste/bin/rfid-close", type="http",
                auth="none", methods=["POST"], csrf=False,
                save_session=False)
    def bin_rfid_close(self, **kwargs):
        """Called by the device the moment it physically re-locks (end
        of its fixed hold-open timer, or an early physical close) with
        the final weight reading. Finalises the open visit immediately
        and returns the bill - weight deposited, amount charged, new
        wallet balance - so the device can show it on-screen right
        away, instead of relying on the session_deadline elapsing
        lazily on some later, unrelated request.

        Safe to call even when nothing was actually open (a staff
        visit, or weight capture was off) - returns has_session: false
        rather than an error.
        """
        try:
            payload = json.loads(
                request.httprequest.get_data(as_text=True) or "{}")
        except (ValueError, TypeError):
            return _json_response(
                {"result": "error", "message": "Invalid JSON body"}, 400)

        env = request.env(su=True)
        bin_rec, err = _authenticate_bin(env, payload)
        if err:
            return err

        weight_kg = None
        raw_weight = payload.get("weight_kg")
        if raw_weight is not None:
            try:
                weight_kg = float(raw_weight)
            except (TypeError, ValueError):
                weight_kg = None

        outcome = bin_rec.close_rfid_session(weight_kg=weight_kg)
        return _json_response({"result": "ok", **outcome}, 200)
