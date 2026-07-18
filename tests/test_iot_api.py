# Part of Otomater. See LICENSE file for full copyright and licensing details.
import json

from odoo.tests import HttpCase, tagged

URL = "/api/smart_waste/bin/status"


@tagged("post_install", "-at_install", "swm")
class TestIotApi(HttpCase):

    def setUp(self):
        super().setUp()
        self.assoc = self.env["otm.swm.association"].create({
            "name": "API Assoc", "code": "APIA",
        })
        self.bin = self.env["otm.swm.bin"].create({
            "name": "API Bin",
            "association_id": self.assoc.id,
            "bin_height_cm": 100.0,
            "device_id": "ESP32-API-01",
        })

    def _post(self, payload):
        return self.url_open(
            URL, data=json.dumps(payload),
            headers={"Content-Type": "application/json"})

    def test_valid_token_accepted(self):
        resp = self._post({
            "device_id": "ESP32-API-01",
            "bin_code": self.bin.code,
            "api_token": self.bin.api_token,
            "fill_percentage": 42,
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["result"], "ok")
        self.assertEqual(body["bin_code"], self.bin.code)

    def test_invalid_token_rejected(self):
        resp = self._post({
            "device_id": "ESP32-API-01",
            "bin_code": self.bin.code,
            "api_token": "wrong-token",
            "fill_percentage": 42,
        })
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["result"], "error")

    def test_wrong_device_id_rejected(self):
        resp = self._post({
            "device_id": "ESP32-SOMEONE-ELSE",
            "bin_code": self.bin.code,
            "api_token": self.bin.api_token,
            "fill_percentage": 42,
        })
        self.assertEqual(resp.status_code, 401)

    def test_missing_fields_rejected(self):
        resp = self._post({"device_id": "ESP32-API-01"})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_rejected(self):
        resp = self.url_open(
            URL, data="not-json{{",
            headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)

    def test_token_header_accepted(self):
        resp = self.url_open(
            URL,
            data=json.dumps({
                "device_id": "ESP32-API-01",
                "bin_code": self.bin.code,
                "fill_percentage": 50,
            }),
            headers={
                "Content-Type": "application/json",
                "X-SWM-Token": self.bin.api_token,
            })
        self.assertEqual(resp.status_code, 200)

    def test_regenerated_token_invalidates_old(self):
        old = self.bin.api_token
        self.bin.action_regenerate_token()
        self.assertNotEqual(old, self.bin.api_token)
        resp = self._post({
            "device_id": "ESP32-API-01",
            "bin_code": self.bin.code,
            "api_token": old,
            "fill_percentage": 42,
        })
        self.assertEqual(resp.status_code, 401)
