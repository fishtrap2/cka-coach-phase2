import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import state_collector


class TestCniDetection(unittest.TestCase):
    def test_recognized_cni_filename(self):
        with patch.object(state_collector, "_command_exists", return_value=True), patch.object(
            state_collector, "_run_command", return_value="10-calico.conflist\n"
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "calico")
        self.assertEqual(result["filenames"], ["10-calico.conflist"])
        self.assertEqual(result["selected_file"], "10-calico.conflist")
        self.assertEqual(result["confidence"], "high")

    def test_unknown_generic_filename(self):
        with patch.object(state_collector, "_command_exists", return_value=True), patch.object(
            state_collector, "_run_command", return_value="10-containerd-net.conflist\n"
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "10-containerd-net.conflist")
        self.assertEqual(result["filenames"], ["10-containerd-net.conflist"])
        self.assertEqual(result["selected_file"], "10-containerd-net.conflist")
        self.assertEqual(result["confidence"], "medium")

    def test_empty_cni_directory(self):
        with patch.object(state_collector, "_command_exists", return_value=True), patch.object(
            state_collector, "_run_command", return_value=""
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "unknown")
        self.assertEqual(result["filenames"], [])
        self.assertEqual(result["selected_file"], "")
        self.assertEqual(result["confidence"], "low")

    def test_multiple_config_files_prefers_recognized_match(self):
        listing = "00-loopback.conf\n10-flannel.conflist\n99-extra.conf\n"
        with patch.object(state_collector, "_command_exists", return_value=True), patch.object(
            state_collector, "_run_command", return_value=listing
        ):
            result = state_collector._detect_cni()

        self.assertEqual(
            result["filenames"],
            ["00-loopback.conf", "10-flannel.conflist", "99-extra.conf"],
        )
        self.assertEqual(result["cni"], "flannel")
        self.assertEqual(result["selected_file"], "10-flannel.conflist")
        self.assertEqual(result["confidence"], "high")

    def test_collect_state_exposes_summary_and_evidence_for_recognized_cni(self):
        cni_detection = {
            "cni": "calico",
            "filenames": ["10-calico.conflist"],
            "selected_file": "10-calico.conflist",
            "confidence": "high",
        }
        with patch.object(state_collector, "_safe_kubectl", return_value=""), patch.object(
            state_collector, "_safe_systemctl", return_value=""
        ), patch.object(state_collector, "_safe_crictl", return_value=""), patch.object(
            state_collector, "_safe_ip", return_value=""
        ), patch.object(
            state_collector, "_run_command", return_value=""
        ), patch.object(
            state_collector, "_safe_kubectl_version_short", return_value=""
        ), patch.object(
            state_collector, "_safe_kubectl_version_json", return_value=""
        ), patch.object(
            state_collector, "_safe_uname", return_value=""
        ), patch.object(
            state_collector, "_safe_containerd_version", return_value=""
        ), patch.object(
            state_collector, "_safe_kubelet_version", return_value=""
        ), patch.object(
            state_collector, "_safe_runc_version", return_value=""
        ), patch.object(
            state_collector, "_detect_cni", return_value=cni_detection
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "calico")
        self.assertEqual(state["evidence"]["cni"], cni_detection)
        self.assertEqual(state["versions"]["cni"], "calico")
        self.assertEqual(state["health"]["cni_ok"], "healthy")

    def test_collect_state_marks_generic_cni_as_degraded(self):
        cni_detection = {
            "cni": "10-containerd-net.conflist",
            "filenames": ["10-containerd-net.conflist"],
            "selected_file": "10-containerd-net.conflist",
            "confidence": "medium",
        }
        with patch.object(state_collector, "_safe_kubectl", return_value=""), patch.object(
            state_collector, "_safe_systemctl", return_value=""
        ), patch.object(state_collector, "_safe_crictl", return_value=""), patch.object(
            state_collector, "_safe_ip", return_value=""
        ), patch.object(
            state_collector, "_run_command", return_value=""
        ), patch.object(
            state_collector, "_safe_kubectl_version_short", return_value=""
        ), patch.object(
            state_collector, "_safe_kubectl_version_json", return_value=""
        ), patch.object(
            state_collector, "_safe_uname", return_value=""
        ), patch.object(
            state_collector, "_safe_containerd_version", return_value=""
        ), patch.object(
            state_collector, "_safe_kubelet_version", return_value=""
        ), patch.object(
            state_collector, "_safe_runc_version", return_value=""
        ), patch.object(
            state_collector, "_detect_cni", return_value=cni_detection
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "10-containerd-net.conflist")
        self.assertEqual(state["evidence"]["cni"]["confidence"], "medium")
        self.assertEqual(state["health"]["cni_ok"], "degraded")


if __name__ == "__main__":
    unittest.main()
