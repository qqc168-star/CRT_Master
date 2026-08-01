from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSurfaceTests(unittest.TestCase):
    def test_scripts_do_not_contain_account_or_order_actions(self):
        text = "\n".join(path.read_text() for path in (ROOT / "scripts").glob("*.sh")).lower()
        for forbidden in ("place_order", "create_order", "cancel_order", "api_key", "secret_key"):
            self.assertNotIn(forbidden, text)

    def test_docker_uses_non_root_user_and_persistent_volume(self):
        text = (ROOT / "deploy" / "docker" / "Dockerfile").read_text()
        self.assertIn("USER crt", text)
        self.assertIn('VOLUME ["/var/lib/crt-radar"]', text)

    def test_compose_is_read_only_and_has_no_ports(self):
        text = (ROOT / "deploy" / "docker" / "docker-compose.shadow.yml").read_text()
        self.assertIn("read_only: true", text)
        self.assertNotIn("ports:", text)

    def test_systemd_template_uses_no_new_privileges(self):
        text = (ROOT / "deploy" / "systemd" / "crt-radar-liquidation-live-shadow.service.template").read_text()
        self.assertIn("NoNewPrivileges=true", text)
        self.assertIn("ProtectSystem=strict", text)

    def test_policy_keeps_external_authority_none(self):
        text = (ROOT / "CONFIG" / "LIVE_SHADOW_POLICY_V1.json").read_text()
        self.assertIn('"external_action_authority": "NONE"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
