import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import lessons


def _base_state() -> dict:
    return {
        "runtime": {
            "hostname": "cp",
            "nodes": (
                "NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP OS-IMAGE KERNEL-VERSION CONTAINER-RUNTIME\n"
                "cp Ready control-plane 58d v1.33.1 10.2.0.2 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
                "worker1 Ready <none> 58d v1.33.1 10.2.0.3 <none> Ubuntu 24.04 6.17.0 containerd://2.2.1\n"
            ),
            "nodes_json": (
                '{"items": ['
                '{"metadata": {"name": "cp"}},'
                '{"metadata": {"name": "worker1"}}'
                "]}"
            ),
            "pods": "",
            "network": "",
            "iptables": "",
        },
        "versions": {"cni": "unknown"},
        "summary": {"versions": {"cni": "unknown"}},
        "evidence": {
            "cni": {
                "classification": {
                    "state": "no_cni",
                    "reason": "No cluster-level or node-level CNI signals were detected.",
                    "notes": [],
                    "previous_detected_cni": "unknown",
                    "stale_taint": {
                        "detected": False,
                        "taints": [],
                        "summary": "no stale CNI taints detected",
                    },
                    "stale_interfaces": {
                        "detected": False,
                        "interfaces": [],
                        "summary": "no stale CNI interfaces detected",
                    },
                },
                "provenance": {
                    "available": False,
                    "current_detected_cni": "unknown",
                    "previous_detected_cni": "unknown",
                },
                "node_level": {
                    "cni": "unknown",
                    "config_dir": "/etc/cni/net.d",
                    "selected_file": "",
                },
                "cluster_level": {"cni": "unknown"},
            }
        },
    }


class TestLessons(unittest.TestCase):
    def test_lesson_catalog_has_one_available_lesson_and_future_placeholders(self):
        catalog = lessons.lesson_catalog()

        self.assertTrue(any(item["available"] for item in catalog))
        self.assertTrue(any(not item["available"] for item in catalog))

    def test_cleanup_lesson_marks_known_good_baseline_completed(self):
        state = _base_state()
        state["versions"]["cni"] = "calico"
        state["summary"]["versions"]["cni"] = "calico"
        state["evidence"]["cni"]["classification"]["state"] = "healthy_calico"
        state["evidence"]["cni"]["classification"]["reason"] = (
            "Calico daemonset/runtime evidence is present with no conflicting CNI signal."
        )

        progress = lessons.default_lesson_progress()
        progress.update(
            {
                "inspect_ran": True,
                "classify_ran": True,
                "scripts_generated": True,
                "student_confirmed": True,
                "recheck_ran": True,
                "baseline_confirmed": True,
                "current_step": 5,
            }
        )

        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)

        self.assertTrue(lesson["baseline_ready"])
        self.assertEqual(lesson["status"], "completed")
        self.assertEqual(lesson["steps"][-1]["status"], "completed")
        self.assertEqual(lesson["completion_percentage"], 100)

    def test_cleanup_lesson_requires_student_action_for_stale_node_config(self):
        state = _base_state()
        state["versions"]["cni"] = "calico"
        state["summary"]["versions"]["cni"] = "calico"
        state["evidence"]["cni"]["classification"]["state"] = "stale_node_config"
        state["evidence"]["cni"]["classification"]["reason"] = (
            "Cluster evidence indicates calico, but node-level config still references cilium."
        )
        state["evidence"]["cni"]["classification"]["previous_detected_cni"] = "cilium"
        state["evidence"]["cni"]["node_level"]["cni"] = "cilium"
        state["evidence"]["cni"]["node_level"]["selected_file"] = "05-cilium.conflist"
        state["evidence"]["cni"]["cluster_level"]["cni"] = "calico"

        lesson = lessons.build_lesson_run("reset_networking_lab", state)

        self.assertEqual(lesson["status"], "paused")
        self.assertEqual(lesson["steps"][0]["status"], "waiting_for_coach")
        self.assertIn("cp", lesson["cleanup_target_nodes"])
        self.assertFalse(lesson["baseline_ready"])

        progress = lessons.default_lesson_progress()
        progress.update({"inspect_ran": True, "classify_ran": True, "scripts_generated": True, "current_step": 3})
        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)
        self.assertEqual(lesson["steps"][3]["status"], "waiting_for_student")
        self.assertIn("cp", lesson["steps"][3]["target_nodes"])

    def test_cleanup_lesson_requires_student_action_for_stale_taint(self):
        state = _base_state()
        state["evidence"]["cni"]["classification"]["state"] = "stale_taint"
        state["evidence"]["cni"]["classification"]["stale_taint"] = {
            "detected": True,
            "taints": [{"node": "cp", "key": "node.cilium.io/agent-not-ready"}],
            "summary": "stale taints detected (1)",
        }

        progress = lessons.default_lesson_progress()
        progress.update({"inspect_ran": True, "classify_ran": True, "scripts_generated": True, "current_step": 2})
        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)

        self.assertIn("cp", lesson["cleanup_target_nodes"])
        self.assertIn("cp", lesson["remediation_scripts"]["cp"]["content"])
        self.assertIn("kubectl taint nodes cp", lesson["remediation_scripts"]["cp"]["content"])

    def test_cleanup_lesson_per_node_status_marks_local_residue(self):
        state = _base_state()
        state["evidence"]["cni"]["classification"]["state"] = "stale_interfaces"
        state["evidence"]["cni"]["classification"]["stale_interfaces"] = {
            "detected": True,
            "interfaces": ["tunl0"],
            "summary": "stale interfaces detected (tunl0)",
        }
        state["runtime"]["network"] = "33: tunl0@NONE: <NOARP,UP,LOWER_UP> mtu 1440"

        lesson = lessons.build_lesson_run("reset_networking_lab", state)

        local_entry = next(entry for entry in lesson["per_node_status"] if entry["node"] == "cp")
        self.assertTrue(local_entry["cleanup_required"])
        self.assertIn("stale_interfaces", local_entry["residue_types"])

    def test_safe_residual_interface_script_contains_actual_delete(self):
        state = _base_state()
        state["evidence"]["cni"]["classification"]["state"] = "stale_interfaces"
        state["evidence"]["cni"]["classification"]["stale_interfaces"] = {
            "detected": True,
            "interfaces": ["tunl0"],
            "summary": "stale interfaces detected (tunl0)",
        }
        state["runtime"]["network"] = "33: tunl0@NONE: <NOARP,UP,LOWER_UP> mtu 1440"

        progress = lessons.default_lesson_progress()
        progress.update({"inspect_ran": True, "classify_ran": True, "scripts_generated": True, "current_step": 2})
        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)

        self.assertIn("sudo ip link delete tunl0", lesson["remediation_scripts"]["cp"]["content"])

    def test_cleanup_lesson_keeps_local_cleanup_target_when_hostname_does_not_match_node_name(self):
        state = _base_state()
        state["runtime"]["hostname"] = "student-lab-host"
        state["evidence"]["cni"]["classification"]["state"] = "stale_interfaces"
        state["evidence"]["cni"]["classification"]["stale_interfaces"] = {
            "detected": True,
            "interfaces": ["tunl0"],
            "summary": "stale interfaces detected (tunl0)",
        }
        state["runtime"]["network"] = "33: tunl0@NONE: <NOARP,UP,LOWER_UP> mtu 1440"

        progress = lessons.default_lesson_progress()
        progress.update({"inspect_ran": True, "classify_ran": True, "scripts_generated": True, "current_step": 2})
        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)

        self.assertIn("student-lab-host", lesson["cleanup_target_nodes"])
        self.assertIn("student-lab-host", lesson["remediation_scripts"])

    def test_resolve_local_node_prefers_internal_ip_match_over_hostname(self):
        state = _base_state()
        state["runtime"]["hostname"] = "lfs258.master"
        state["runtime"]["network"] = (
            "2: ens4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1460\n"
            "    inet 10.2.0.2/32 metric 100 scope global dynamic ens4\n"
        )

        resolved = lessons._resolve_local_node(["cp", "worker1"], state["runtime"])

        self.assertEqual(resolved, "cp")

    def test_student_remediation_step_targets_one_node_at_a_time(self):
        state = _base_state()
        state["runtime"]["network"] = "33: tunl0@NONE: <NOARP,UP,LOWER_UP> mtu 1440"
        state["evidence"]["cni"]["classification"]["state"] = "stale_interfaces"
        state["evidence"]["cni"]["classification"]["stale_interfaces"] = {
            "detected": True,
            "interfaces": ["tunl0"],
            "summary": "stale interfaces detected (tunl0)",
        }

        progress = lessons.default_lesson_progress()
        progress.update(
            {
                "inspect_ran": True,
                "classify_ran": True,
                "scripts_generated": True,
                "current_step": 3,
                "current_target_index": 0,
            }
        )
        lesson = lessons.build_lesson_run("reset_networking_lab", state, progress)

        self.assertEqual(lesson["current_remediation_target"], "cp")
        self.assertEqual(lesson["steps"][3]["target_nodes"], ["cp"])
        self.assertIn("cleanup-cni-residuals-cp.sh", lesson["steps"][3]["student_action"])


if __name__ == "__main__":
    unittest.main()
