import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import dashboard_presenters
import state_collector


class TestCniDetection(unittest.TestCase):
    def test_parse_calico_bird_protocols_established(self):
        output = (
            'Defaulted container "calico-node" out of: calico-node, install-cni (init)\n'
            "BIRD v0.3.3+birdv1.6.8 ready.\n"
            "name     proto    table    state  since       info\n"
            "Mesh_10_2_0_3 BGP      master   up     16:03:24    Established\n"
        )

        result = state_collector._parse_calico_bird_protocols(output)

        self.assertEqual(result["status"], "established")
        self.assertTrue(result["bird_ready"])
        self.assertEqual(result["established_peers"], 1)
        self.assertEqual(result["summary"], "BGP peers established=1")

    def test_collect_calico_runtime_evidence_from_bird_exec(self):
        cluster_detection = {
            "cni": "calico",
            "matched_pods": ["calico-node-46g9k", "calico-kube-controllers-12345"],
            "selected_pod": "calico-node-46g9k",
            "confidence": "high",
        }
        bird_output = (
            "BIRD v0.3.3+birdv1.6.8 ready.\n"
            "Mesh_10_2_0_3 BGP      master   up     16:03:24    Established\n"
        )

        with patch.object(state_collector, "_safe_kubectl", return_value=bird_output):
            result = state_collector._collect_calico_runtime_evidence(cluster_detection)

        self.assertEqual(result["status"], "established")
        self.assertEqual(result["pod"], "calico-node-46g9k")
        self.assertEqual(result["source"], "kubectl_exec_birdcl")
        self.assertEqual(result["established_peers"], 1)

    def test_kubelet_health_ignores_cleanup_noise_when_service_and_nodes_are_healthy(self):
        runtime = {
            "pods": (
                "NAMESPACE NAME READY STATUS RESTARTS AGE IP NODE NOMINATED NODE READINESS GATES\n"
                "kube-system calico-node-abcde 1/1 Running 0 1h 10.0.0.1 cp <none> <none>\n"
            ),
            "events": "",
            "nodes": (
                "NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP OS-IMAGE KERNEL-VERSION CONTAINER-RUNTIME\n"
                "cp Ready control-plane 58d v1.33.1 10.2.0.2 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
                "worker1 Ready <none> 58d v1.33.1 10.2.0.3 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
            ),
            "kubelet": (
                "kubelet.service - kubelet\n"
                "   Active: active (running)\n"
                "DeleteContainer for container not found\n"
                "orphaned pod volume paths are still present\n"
                "failed to get container status for already removed pod\n"
            ),
            "containerd": "",
        }
        versions = {"api": "", "runc": "", "kernel": "", "cni": "calico"}
        evidence = {"cni": {"reconciliation": "single_source", "cluster_footprint": {"summary": "cluster footprint not directly observed", "daemonsets": []}}}

        result = state_collector._health_flags(runtime, versions, evidence)

        self.assertTrue(result["kubelet_ok"])
        self.assertTrue(result["kubelet_cleanup_noise"])
        self.assertIn("cleanup/history messages", result["kubelet_transitional_note"])

    def test_kubelet_health_stays_unhealthy_for_real_service_failure(self):
        runtime = {
            "pods": "",
            "events": "",
            "nodes": (
                "NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP OS-IMAGE KERNEL-VERSION CONTAINER-RUNTIME\n"
                "cp NotReady control-plane 58d v1.33.1 10.2.0.2 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
            ),
            "kubelet": "kubelet.service - kubelet\n   Active: failed",
            "containerd": "",
        }
        versions = {"api": "", "runc": "", "kernel": "", "cni": "unknown"}

        result = state_collector._health_flags(runtime, versions, {})

        self.assertFalse(result["kubelet_ok"])
        self.assertFalse(result["kubelet_cleanup_noise"])
        self.assertEqual(result["kubelet_transitional_note"], "")

    def test_containerd_health_ignores_cleanup_noise_when_service_and_nodes_are_healthy(self):
        runtime = {
            "pods": (
                "NAMESPACE NAME READY STATUS RESTARTS AGE IP NODE NOMINATED NODE READINESS GATES\n"
                "default testpod 1/1 Running 0 1h 10.0.0.9 worker1 <none> <none>\n"
            ),
            "events": "",
            "nodes": (
                "NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP OS-IMAGE KERNEL-VERSION CONTAINER-RUNTIME\n"
                "cp Ready control-plane 58d v1.33.1 10.2.0.2 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
                "worker1 Ready <none> 58d v1.33.1 10.2.0.3 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
            ),
            "kubelet": "",
            "containerd": (
                "containerd.service - containerd\n"
                "   Active: active (running)\n"
                "failed to delete task: not found\n"
                "cleanup completed for already removed container\n"
            ),
        }
        versions = {"api": "", "runc": "", "kernel": "", "cni": "unknown"}

        result = state_collector._health_flags(runtime, versions, {})

        self.assertTrue(result["containerd_ok"])
        self.assertTrue(result["containerd_cleanup_noise"])
        self.assertIn("cleanup/history messages", result["containerd_transitional_note"])

    def test_containerd_health_stays_unhealthy_for_real_service_failure(self):
        runtime = {
            "pods": "",
            "events": "",
            "nodes": (
                "NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP OS-IMAGE KERNEL-VERSION CONTAINER-RUNTIME\n"
                "cp NotReady control-plane 58d v1.33.1 10.2.0.2 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
            ),
            "kubelet": "",
            "containerd": "containerd.service - containerd\n   Active: failed",
        }
        versions = {"api": "", "runc": "", "kernel": "", "cni": "unknown"}

        result = state_collector._health_flags(runtime, versions, {})

        self.assertFalse(result["containerd_ok"])
        self.assertFalse(result["containerd_cleanup_noise"])
        self.assertEqual(result["containerd_transitional_note"], "")

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

    def test_detect_cni_from_generic_filename_uses_config_content_for_calico(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "state_collector.os.path.exists",
            return_value=True,
        ), patch(
            "state_collector.os.path.isdir",
            return_value=True,
        ), patch(
            "state_collector.os.listdir",
            return_value=["10-generic.conflist"],
        ), patch.object(
            state_collector,
            "_read_selected_cni_config",
            return_value='{"name": "k8s-pod-network", "plugins": [{"type": "calico"}]}',
        ):
            result = state_collector._detect_cni()

        self.assertEqual(result["cni"], "calico")
        self.assertEqual(result["selected_file"], "10-generic.conflist")
        self.assertEqual(result["confidence"], "high")

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

    def test_detect_cni_from_pods_recognizes_explicit_calico_signals(self):
        pods_text = (
            "NAMESPACE NAME READY STATUS RESTARTS AGE IP NODE NOMINATED NODE READINESS GATES\n"
            "kube-system calico-node-abcde 1/1 Running 0 1h 10.0.0.1 node1 <none> <none>\n"
            "kube-system calico-kube-controllers-12345 1/1 Running 0 1h 10.0.0.2 node1 <none> <none>\n"
        )

        result = state_collector._detect_cni_from_pods(pods_text)

        self.assertEqual(result["cni"], "calico")
        self.assertEqual(result["selected_pod"], "calico-node-abcde")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(
            result["matched_pods"],
            ["calico-node-abcde", "calico-kube-controllers-12345"],
        )

    def test_infer_cni_capabilities_for_calico(self):
        result = state_collector._infer_cni_capabilities("calico")

        self.assertEqual(result["network_policy"], True)
        self.assertEqual(result["policy_model"], "Kubernetes + Calico extensions")
        self.assertEqual(result["inference_basis"], "detected_cni_name")

    def test_infer_cni_capabilities_preserves_generic_default_behavior(self):
        result = state_collector._infer_cni_capabilities("10-containerd-net.conflist")

        self.assertEqual(result["summary"], "unknown")
        self.assertIsNone(result["network_policy"])
        self.assertEqual(result["policy_model"], "unknown")
        self.assertEqual(result["inference_basis"], "insufficient_cni_evidence")

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

    def test_summarize_cni_cluster_footprint_for_cilium(self):
        cluster_detection = {
            "cni": "cilium",
            "matched_pods": [
                "cilium-envoy-fnqpp",
                "cilium-gqtd7",
                "cilium-operator-69bcbb6469-d4qkp",
            ],
            "selected_pod": "cilium-envoy-fnqpp",
            "confidence": "high",
        }
        daemonsets_text = (
            "NAME DESIRED CURRENT READY UP-TO-DATE AVAILABLE NODE SELECTOR AGE\n"
            "cilium 2 2 2 2 2 kubernetes.io/os=linux 58d\n"
            "cilium-envoy 2 2 2 2 2 kubernetes.io/os=linux 58d\n"
            "kube-proxy 2 2 2 2 2 kubernetes.io/os=linux 58d\n"
        )

        result = state_collector._summarize_cni_cluster_footprint(
            "cilium",
            cluster_detection,
            daemonsets_text,
        )

        self.assertTrue(result["operator_present"])
        self.assertEqual(result["daemonset_count"], 2)
        self.assertEqual(result["summary"], "operator present, daemonsets=2")

    def test_summarize_cni_cluster_footprint_for_calico(self):
        cluster_detection = {
            "cni": "calico",
            "matched_pods": [
                "calico-node-abcde",
                "calico-kube-controllers-12345",
            ],
            "selected_pod": "calico-node-abcde",
            "confidence": "high",
        }
        daemonsets_text = (
            "NAME DESIRED CURRENT READY UP-TO-DATE AVAILABLE NODE SELECTOR AGE\n"
            "calico-node 2 2 2 2 2 kubernetes.io/os=linux 20d\n"
        )

        result = state_collector._summarize_cni_cluster_footprint(
            "calico",
            cluster_detection,
            daemonsets_text,
        )

        self.assertFalse(result["operator_present"])
        self.assertEqual(result["daemonset_count"], 1)
        self.assertEqual(result["summary"], "daemonsets=1")

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
        ), patch.object(
            state_collector,
            "_collect_calico_runtime_evidence",
            return_value={
                "status": "established",
                "pod": "calico-node-abcde",
                "bird_ready": True,
                "established_peers": 1,
                "protocol_lines": ["Mesh_10_2_0_3 BGP master up Established"],
                "summary": "BGP peers established=1",
                "source": "kubectl_exec_birdcl",
                "raw_output": "BIRD ready",
            },
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
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["network_policy"], True)
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["policy_model"], "Kubernetes + Calico extensions")
        self.assertEqual(
            state["evidence"]["cni"]["cluster_footprint"]["summary"],
            "pods present; daemonset footprint not directly observed",
        )
        self.assertEqual(state["evidence"]["cni"]["policy_presence"]["status"], "unknown")
        self.assertEqual(state["evidence"]["cni"]["version"]["value"], "v3.30.0")
        self.assertEqual(state["evidence"]["cni"]["calico_runtime"]["status"], "established")
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

    def test_collect_state_treats_env_override_stale_cni_conflict_as_unknown_not_degraded(self):
        node_detection = {
            "cni": "cilium",
            "filenames": ["05-cilium.conflist"],
            "selected_file": "05-cilium.conflist",
            "confidence": "high",
            "config_dir_source": "env_override",
            "config_dir": "/home/student/cni-config",
            "directory_status": "readable",
            "host_evidence_enabled": True,
            "configured_override_ignored": False,
        }
        cluster_detection = {
            "cni": "calico",
            "matched_pods": ["calico-node-46g9k", "calico-kube-controllers-12345"],
            "selected_pod": "calico-node-46g9k",
            "confidence": "high",
        }

        def fake_safe_kubectl(command: str) -> str:
            if command == "kubectl get daemonsets -n kube-system":
                return (
                    "NAME DESIRED CURRENT READY UP-TO-DATE AVAILABLE NODE SELECTOR AGE\n"
                    "calico-node 2 2 2 2 2 kubernetes.io/os=linux 58d\n"
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
        ), patch.object(
            state_collector,
            "_collect_calico_runtime_evidence",
            return_value={
                "status": "established",
                "pod": "calico-node-46g9k",
                "bird_ready": True,
                "established_peers": 1,
                "protocol_lines": ["Mesh_10_2_0_3 BGP master up Established"],
                "summary": "BGP peers established=1",
                "source": "kubectl_exec_birdcl",
                "raw_output": "BIRD ready",
            },
        ):
            state = state_collector.collect_state(allow_host_evidence=True)

        self.assertEqual(state["summary"]["versions"]["cni"], "calico")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "conflict")
        self.assertEqual(state["health"]["cni_ok"], "unknown")

    def test_collect_state_marks_partial_calico_evidence_as_unknown_health(self):
        node_detection = {
            "cni": "unknown",
            "filenames": [],
            "selected_file": "",
            "confidence": "low",
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
            "_collect_calico_runtime_evidence",
            return_value={
                "status": "established",
                "pod": "calico-node-abcde",
                "bird_ready": True,
                "established_peers": 1,
                "protocol_lines": ["Mesh_10_2_0_3 BGP master up Established"],
                "summary": "BGP peers established=1",
                "source": "kubectl_exec_birdcl",
                "raw_output": "BIRD ready",
            },
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "calico")
        self.assertEqual(state["evidence"]["cni"]["confidence"], "medium")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "single_source")
        self.assertEqual(state["health"]["cni_ok"], "healthy")
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["network_policy"], True)

    def test_collect_state_preserves_cilium_capability_behavior(self):
        node_detection = {
            "cni": "cilium",
            "filenames": ["05-cilium.conflist"],
            "selected_file": "05-cilium.conflist",
            "confidence": "high",
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
        self.assertEqual(state["evidence"]["cni"]["confidence"], "high")
        self.assertEqual(state["evidence"]["cni"]["capabilities"]["network_policy"], True)
        self.assertEqual(
            state["evidence"]["cni"]["cluster_footprint"]["summary"],
            "pods present; daemonset footprint not directly observed",
        )
        self.assertEqual(
            state["evidence"]["cni"]["capabilities"]["policy_model"],
            "Kubernetes + Cilium policy features likely",
        )

    def test_collect_state_marks_cilium_unknown_when_operator_remains_but_dataplane_daemonset_missing(self):
        node_detection = {
            "cni": "cilium",
            "filenames": ["05-cilium.conflist"],
            "selected_file": "05-cilium.conflist",
            "confidence": "high",
        }
        cluster_detection = {
            "cni": "cilium",
            "matched_pods": ["cilium-operator-12345"],
            "selected_pod": "cilium-operator-12345",
            "confidence": "high",
        }

        def fake_safe_kubectl(command: str) -> str:
            if command == "kubectl get daemonsets -n kube-system":
                return (
                    "NAME DESIRED CURRENT READY UP-TO-DATE AVAILABLE NODE SELECTOR AGE\n"
                    "kube-proxy 2 2 2 2 2 kubernetes.io/os=linux 58d\n"
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
        ), patch.object(
            state_collector,
            "_collect_calico_runtime_evidence",
            return_value={
                "status": "established",
                "pod": "calico-node-abcde",
                "bird_ready": True,
                "established_peers": 1,
                "protocol_lines": ["Mesh_10_2_0_3 BGP master up Established"],
                "summary": "BGP peers established=1",
                "source": "kubectl_exec_birdcl",
                "raw_output": "BIRD ready",
            },
        ):
            state = state_collector.collect_state()

        self.assertEqual(state["summary"]["versions"]["cni"], "cilium")
        self.assertEqual(state["evidence"]["cni"]["reconciliation"], "agree")
        self.assertEqual(
            state["evidence"]["cni"]["cluster_footprint"]["summary"],
            "operator present",
        )
        self.assertEqual(state["health"]["cni_ok"], "unknown")

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

    def test_classify_cni_state_healthy_calico(self):
        runtime = {"nodes": "cp Ready\nworker1 Ready\n", "pods": "kube-system calico-node-abcde Running\n", "nodes_json": "{}", "network": ""}
        versions = {"cni": "calico"}
        evidence = {
            "confidence": "high",
            "reconciliation": "agree",
            "migration_note": "Cluster-level and node-level evidence agree on the current CNI.",
            "node_level": {"cni": "calico"},
            "cluster_level": {"cni": "calico"},
            "cluster_footprint": {"daemonsets": [{"name": "calico-node"}]},
            "calico_runtime": {"status": "established"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "healthy"})

        self.assertEqual(result["state"], "healthy_calico")

    def test_classify_cni_state_healthy_cilium(self):
        runtime = {"nodes": "cp Ready\nworker1 Ready\n", "pods": "kube-system cilium-abcde Running\n", "nodes_json": "{}", "network": ""}
        versions = {"cni": "cilium"}
        evidence = {
            "confidence": "high",
            "reconciliation": "agree",
            "migration_note": "Cluster-level and node-level evidence agree on the current CNI.",
            "node_level": {"cni": "cilium"},
            "cluster_level": {"cni": "cilium"},
            "cluster_footprint": {"daemonsets": [{"name": "cilium"}]},
            "calico_runtime": {"status": "not_applicable"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "healthy"})

        self.assertEqual(result["state"], "healthy_cilium")

    def test_classify_cni_state_generic_cni(self):
        runtime = {"nodes": "cp Ready\nworker1 Ready\n", "pods": "default app 1/1 Running\n", "nodes_json": "{}", "network": ""}
        versions = {"cni": "unknown"}
        evidence = {
            "confidence": "low",
            "reconciliation": "unknown",
            "migration_note": "",
            "node_level": {"cni": "unknown"},
            "cluster_level": {"cni": "unknown"},
            "cluster_footprint": {"daemonsets": []},
            "calico_runtime": {"status": "unknown"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "generic_cni")

    def test_classify_cni_state_node_level_calico_without_cluster_footprint_is_not_generic(self):
        runtime = {"nodes": "cp Ready\nworker1 Ready\n", "pods": "default app 1/1 Running\n", "nodes_json": "{}", "network": ""}
        versions = {"cni": "calico"}
        evidence = {
            "confidence": "medium",
            "reconciliation": "single_source",
            "migration_note": "Only one evidence source identifies the current CNI, so the result remains partially unverified.",
            "node_level": {"cni": "calico"},
            "cluster_level": {"cni": "unknown"},
            "cluster_footprint": {"daemonsets": []},
            "calico_runtime": {"status": "unknown"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "stale_node_config")

    def test_classify_cni_state_node_level_cilium_without_cluster_footprint_is_not_generic(self):
        runtime = {"nodes": "cp Ready\nworker1 Ready\n", "pods": "default app 1/1 Running\n", "nodes_json": "{}", "network": ""}
        versions = {"cni": "cilium"}
        evidence = {
            "confidence": "medium",
            "reconciliation": "single_source",
            "migration_note": "Only one evidence source identifies the current CNI, so the result remains partially unverified.",
            "node_level": {"cni": "cilium"},
            "cluster_level": {"cni": "unknown"},
            "cluster_footprint": {"daemonsets": []},
            "calico_runtime": {"status": "not_applicable"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "stale_node_config")

    def test_classify_cni_state_no_cni(self):
        runtime = {"nodes": "cp NotReady\n", "pods": "", "nodes_json": "{}", "network": ""}
        versions = {"cni": "unknown"}
        evidence = {
            "confidence": "low",
            "reconciliation": "unknown",
            "migration_note": "",
            "node_level": {"cni": "unknown"},
            "cluster_level": {"cni": "unknown"},
            "cluster_footprint": {"daemonsets": []},
            "calico_runtime": {"status": "unknown"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "no_cni")

    def test_classify_cni_state_mixed_or_transitional(self):
        runtime = {"nodes": "cp Ready\n", "pods": "", "nodes_json": "{}", "network": ""}
        versions = {"cni": "calico"}
        evidence = {
            "confidence": "medium",
            "reconciliation": "single_source",
            "migration_note": "Only one evidence source identifies the current CNI, so the result remains partially unverified.",
            "node_level": {"cni": "unknown"},
            "cluster_level": {"cni": "calico"},
            "cluster_footprint": {"daemonsets": []},
            "calico_runtime": {"status": "unknown"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "mixed_or_transitional")

    def test_classify_cni_state_stale_node_config(self):
        runtime = {"nodes": "cp Ready\n", "pods": "", "nodes_json": "{}", "network": ""}
        versions = {"cni": "calico"}
        evidence = {
            "confidence": "medium",
            "reconciliation": "conflict",
            "migration_note": "Mixed CNI evidence detected.",
            "node_level": {"cni": "cilium"},
            "cluster_level": {"cni": "calico"},
            "cluster_footprint": {"daemonsets": [{"name": "calico-node"}]},
            "calico_runtime": {"status": "established"},
        }

        result = state_collector._classify_cni_state(runtime, versions, evidence, {"cni_ok": "unknown"})

        self.assertEqual(result["state"], "stale_node_config")

    def test_summarize_cni_event_history_treats_events_as_historical_context(self):
        events_text = (
            "kube-system calico-node-abcde Readiness probe failed: BGP not established\n"
            "kube-system calico-kube-controllers-12345 Started container\n"
        )

        result = state_collector._summarize_cni_event_history(events_text, "calico")

        self.assertEqual(result["basis"], "historical_context")
        self.assertIn("historical", result["summary"])
        self.assertEqual(len(result["relevant_lines"]), 2)

    def test_load_cni_provenance_missing_is_graceful(self):
        result = state_collector._load_cni_provenance("Error from server (NotFound): configmaps \"cka-coach-provenance\" not found")

        self.assertFalse(result["available"])
        self.assertEqual(result["current_detected_cni"], "unknown")

    def test_load_cni_provenance_present(self):
        configmap_json = json.dumps(
            {
                "data": {
                    "current_detected_cni": "calico",
                    "previous_detected_cni": "cilium",
                    "last_cleaned_at": "2026-04-18T12:00:00Z",
                    "cleaned_by": "student",
                    "last_install_observed_at": "2026-04-18T12:05:00Z",
                    "evidence_basis": "manual lab cleanup + install",
                }
            }
        )

        result = state_collector._load_cni_provenance(configmap_json)

        self.assertTrue(result["available"])
        self.assertEqual(result["current_detected_cni"], "calico")
        self.assertEqual(result["previous_detected_cni"], "cilium")

    def test_dump_state_like_structure_contains_classification_and_provenance(self):
        fake_state = {
            "summary": {"cni_classification": "healthy_calico"},
            "evidence": {"cni": {"classification": {"state": "healthy_calico"}, "provenance": {"available": False}}},
            "runtime": {},
            "versions": {},
            "health": {},
        }

        output = io.StringIO()
        with redirect_stdout(output):
            print(json.dumps(fake_state))

        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["summary"]["cni_classification"], "healthy_calico")
        self.assertIn("provenance", parsed["evidence"]["cni"])


if __name__ == "__main__":
    unittest.main()
