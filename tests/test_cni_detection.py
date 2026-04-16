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

    def test_detect_cni_from_pods_recognizes_kube_system_plugin_pods(self):
        pods_text = (
            "NAMESPACE NAME READY STATUS RESTARTS AGE IP NODE NOMINATED NODE READINESS GATES\n"
            "kube-system cilium-abcde 1/1 Running 0 1h 10.0.0.1 node1 <none> <none>\n"
            "kube-system cilium-operator-12345 1/1 Running 0 1h 10.0.0.2 node1 <none> <none>\n"
        )
        result = state_collector._detect_cni_from_pods(pods_text)

        self.assertEqual(result["cni"], "cilium")
        self.assertEqual(result["selected_pod"], "cilium-abcde")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(
            result["matched_pods"],
            ["cilium-abcde", "cilium-operator-12345"],
        )

    def test_network_policy_summary_detects_present_policies(self):
        policies_text = (
            "NAMESPACE NAME POD-SELECTOR AGE\n"
            "default allow-web app=web 1d\n"
            "payments deny-all <none> 4h\n"
        )
        result = state_collector._summarize_network_policy_presence(policies_text)

        self.assertEqual(result["status"], "present")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["namespaces"], ["default", "payments"])

    def test_collect_state_reconciles_agreeing_sources_as_healthy(self):
        node_detection = {
            "cni": "calico",
            "filenames": ["10-calico.conflist"],
            "selected_file": "10-calico.conflist",
            "confidence": "high",
        }
        cluster_detection = {
            "cni": "calico",
            "matched_pods": ["calico-node-abcde", "calico-kube-controllers-12345"],
            "selected_pod": "calico-node-abcde",
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
            state_collector, "_detect_cni", return_value=node_detection
        ), patch.object(
            state_collector, "_detect_cni_from_pods", return_value=cluster_detection
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "calico")
        self.assertEqual(state["evidence"]["cni"]["node_level"], node_detection)
        self.assertEqual(state["evidence"]["cni"]["cluster_level"], cluster_detection)
        self.assertEqual(state["evidence"]["cni"]["confidence"], "high")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "agree")
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["summary"], "policy-capable dataplane likely")
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["status"], "unknown")
        self.assertEqual(
            state["evidence"]["cni"]["migration_note"],
            "Cluster-level and node-level evidence agree on the current CNI.",
        )
        self.assertEqual(state["versions"]["cni"], "calico")
        self.assertEqual(state["health"]["cni_ok"], "healthy")

    def test_collect_state_marks_conflicting_sources_as_degraded(self):
        node_detection = {
            "cni": "10-containerd-net.conflist",
            "filenames": ["10-containerd-net.conflist"],
            "selected_file": "10-containerd-net.conflist",
            "confidence": "medium",
        }
        cluster_detection = {
            "cni": "cilium",
            "matched_pods": ["cilium-abcde", "cilium-operator-12345"],
            "selected_pod": "cilium-abcde",
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
            state_collector, "_detect_cni", return_value=node_detection
        ), patch.object(
            state_collector, "_detect_cni_from_pods", return_value=cluster_detection
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "cilium")
        self.assertEqual(state["evidence"]["cni"]["confidence"], "medium")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "conflict")
        self.assertEqual(state["health"]["cni_ok"], "degraded")

    def test_collect_state_includes_policy_presence_when_network_policy_exists(self):
        node_detection = {
            "cni": "calico",
            "filenames": ["10-calico.conflist"],
            "selected_file": "10-calico.conflist",
            "confidence": "high",
        }
        cluster_detection = {
            "cni": "calico",
            "matched_pods": ["calico-node-abcde"],
            "selected_pod": "calico-node-abcde",
            "confidence": "high",
        }

        def fake_safe_kubectl(command: str) -> str:
            if command == "kubectl get networkpolicy -A":
                return (
                    "NAMESPACE NAME POD-SELECTOR AGE\n"
                    "default allow-web app=web 1d\n"
                )
            return ""

        with patch.object(state_collector, "_safe_kubectl", side_effect=fake_safe_kubectl), patch.object(
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
            state_collector, "_detect_cni", return_value=node_detection
        ), patch.object(
            state_collector, "_detect_cni_from_pods", return_value=cluster_detection
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["runtime"]["network_policies"].splitlines()[1], "default allow-web app=web 1d")
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["status"], "present")
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["count"], 1)
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["namespaces"], ["default"])
        self.assertEqual(
            state["evidence"]["cni"]["capabilities"]["policy_support"],
            "platform likely supports network policy features",
        )


if __name__ == "__main__":
    unittest.main()
