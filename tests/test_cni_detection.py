import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import dashboard_presenters
import state_collector


class TestCniDetection(unittest.TestCase):
    def test_default_cni_config_dir_behavior(self):
        with patch.dict(os.environ, {}, clear=True):
            result = state_collector._resolve_cni_config_dir()

        self.assertEqual(result["directory"], state_collector.DEFAULT_CNI_CONFIG_DIR)
        self.assertEqual(result["directory_source"], "default")
        self.assertFalse(result["host_evidence_enabled"])
        self.assertFalse(result["configured_override_ignored"])

    def test_env_var_override_behavior_requires_host_evidence_opt_in(self):
        with patch.dict(
            os.environ,
            {"CKA_COACH_CNI_CONFIG_DIR": "/tmp/cni-copy"},
            clear=True,
        ):
            disabled = state_collector._resolve_cni_config_dir()
            enabled = state_collector._resolve_cni_config_dir(allow_host_evidence=True)

        self.assertEqual(disabled["directory"], state_collector.DEFAULT_CNI_CONFIG_DIR)
        self.assertTrue(disabled["configured_override_ignored"])
        self.assertEqual(enabled["directory"], "/tmp/cni-copy")
        self.assertEqual(enabled["directory_source"], "env_override")
        self.assertTrue(enabled["host_evidence_enabled"])

    def test_missing_cni_directory_behavior(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=False,
        ):
            result = state_collector._inspect_cni_config_dir()

        self.assertEqual(result["directory_status"], "directory_missing")
        self.assertEqual(result["filenames"], [])

    def test_unreadable_cni_directory_behavior(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            side_effect=PermissionError,
        ):
            result = state_collector._inspect_cni_config_dir()

        self.assertEqual(result["directory_status"], "unreadable")
        self.assertEqual(result["filenames"], [])

    def test_dashboard_wording_for_not_directly_observed_host_evidence(self):
        state = {
            "summary": {"versions": {"cni_config_spec_version": "unknown"}},
            "evidence": {
                "cni": {
                    "node_level": {
                        "config_dir": "/host/etc/cni/net.d",
                    }
                }
            },
        }

        result = dashboard_presenters.cni_config_spec_display(state)

        self.assertEqual(result["label"], "not directly observed*")
        self.assertFalse(result["observed"])
        self.assertIn("does not use sudo by design", result["note"])
        self.assertIn("--allow-host-evidence", result["note"])

    def test_detect_cni_config_spec_version_from_selected_config_content(self):
        config_content = """
        {
          "cniVersion": "0.3.1",
          "name": "cilium",
          "plugins": [{"type": "cilium-cni"}]
        }
        """

        result = state_collector._detect_cni_config_spec_version(
            config_content,
            "05-cilium.conflist",
        )

        self.assertEqual(result["value"], "0.3.1")
        self.assertEqual(result["source"], "selected_cni_config_content")
        self.assertEqual(result["file"], "05-cilium.conflist")

    def test_detect_cni_config_spec_version_absent_without_trustworthy_content(self):
        result = state_collector._detect_cni_config_spec_version(
            "",
            "05-cilium.conflist",
        )

        self.assertEqual(result["value"], "unknown")
        self.assertEqual(result["source"], "missing_cni_config_content")
        self.assertEqual(result["file"], "05-cilium.conflist")

    def test_detect_cni_version_from_image_tag_when_trustworthy(self):
        cluster_detection = {
            "cni": "cilium",
            "matched_pods": ["cilium-abcde", "cilium-operator-12345"],
            "selected_pod": "cilium-abcde",
            "confidence": "high",
        }
        kube_system_pods_json = """
        {
          "items": [
            {
              "metadata": {"name": "cilium-abcde"},
              "spec": {"containers": [{"image": "quay.io/cilium/cilium:v1.16.3"}]}
            },
            {
              "metadata": {"name": "cilium-operator-12345"},
              "spec": {"containers": [{"image": "quay.io/cilium/operator-generic:v1.16.3"}]}
            }
          ]
        }
        """

        result = state_collector._detect_cni_version_from_pod_images(
            "cilium",
            cluster_detection,
            kube_system_pods_json,
        )

        self.assertEqual(result["value"], "v1.16.3")
        self.assertEqual(result["source"], "kube_system_pod_image_tag")
        self.assertEqual(result["pod"], "cilium-abcde")
        self.assertEqual(result["image"], "quay.io/cilium/cilium:v1.16.3")

    def test_detect_cni_version_absent_when_no_single_trustworthy_tag_exists(self):
        cluster_detection = {
            "cni": "cilium",
            "matched_pods": ["cilium-abcde", "cilium-operator-12345"],
            "selected_pod": "cilium-abcde",
            "confidence": "high",
        }
        kube_system_pods_json = """
        {
          "items": [
            {
              "metadata": {"name": "cilium-abcde"},
              "spec": {"containers": [{"image": "quay.io/cilium/cilium:v1.16.3"}]}
            },
            {
              "metadata": {"name": "cilium-operator-12345"},
              "spec": {"containers": [{"image": "quay.io/cilium/operator-generic:v1.16.4"}]}
            }
          ]
        }
        """

        result = state_collector._detect_cni_version_from_pod_images(
            "cilium",
            cluster_detection,
            kube_system_pods_json,
        )

        self.assertEqual(result["value"], "unknown")
        self.assertEqual(result["source"], "no_single_trustworthy_image_tag")

    def test_recognized_cni_filename(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            return_value=["10-calico.conflist"],
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "calico")
        self.assertEqual(result["filenames"], ["10-calico.conflist"])
        self.assertEqual(result["selected_file"], "10-calico.conflist")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["config_dir"], state_collector.DEFAULT_CNI_CONFIG_DIR)
        self.assertEqual(result["directory_status"], "readable")

    def test_unknown_generic_filename(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            return_value=["10-containerd-net.conflist"],
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "10-containerd-net.conflist")
        self.assertEqual(result["filenames"], ["10-containerd-net.conflist"])
        self.assertEqual(result["selected_file"], "10-containerd-net.conflist")
        self.assertEqual(result["confidence"], "medium")

    def test_empty_cni_directory(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            return_value=[],
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "unknown")
        self.assertEqual(result["filenames"], [])
        self.assertEqual(result["selected_file"], "")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["directory_status"], "readable_empty")

    def test_multiple_config_files_prefers_recognized_match(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            return_value=["00-loopback.conf", "10-flannel.conflist", "99-extra.conf"],
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
        ), patch.object(
            state_collector,
            "_detect_cni_version_from_pod_images",
            return_value={
                "value": "v3.30.0",
                "source": "kube_system_pod_image_tag",
                "pod": "calico-node-abcde",
                "image": "docker.io/calico/node:v3.30.0",
            },
        ), patch.object(
            state_collector,
            "_read_selected_cni_config",
            return_value='{"cniVersion": "0.3.1", "name": "calico"}',
        ):
            state = state_collector.collect_state(allow_host_evidence=True)

        self.assertEqual(state["summary"]["versions"]["cni"], "calico")
        self.assertEqual(state["summary"]["versions"]["cni_version"], "v3.30.0")
        self.assertEqual(state["summary"]["versions"]["cni_config_spec_version"], "0.3.1")
        self.assertEqual(state["evidence"]["cni"]["node_level"], node_detection)
        self.assertEqual(state["evidence"]["cni"]["cluster_level"], cluster_detection)
        self.assertEqual(state["evidence"]["cni"]["confidence"], "high")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "agree")
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["summary"], "policy-capable dataplane likely")
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["status"], "unknown")
        self.assertEqual(state["evidence"]["cni"]["version"]["value"], "v3.30.0")
        self.assertEqual(state["evidence"]["cni"]["config_spec_version"]["value"], "0.3.1")
        self.assertIn('"cniVersion": "0.3.1"', state["evidence"]["cni"]["config_content"])
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

    def test_collect_state_marks_single_source_cni_as_unknown_health(self):
        node_detection = {
            "cni": "unknown",
            "filenames": [],
            "selected_file": "",
            "confidence": "low",
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
        ), patch.object(
            state_collector,
            "_detect_cni_version_from_pod_images",
            return_value={
                "value": "unknown",
                "source": "no_single_trustworthy_image_tag",
                "pod": "",
                "image": "",
            },
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "cilium")
        self.assertEqual(state["summary"]["versions"]["cni_version"], "unknown")
        self.assertEqual(state["summary"]["versions"]["cni_config_spec_version"], "unknown")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "single_source")
        self.assertEqual(state["health"]["cni_ok"], "unknown")

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
