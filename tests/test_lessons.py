import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import lessons


def _base_state() -> dict:
    return {
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

        lesson = lessons.build_lesson_run("reset_networking_lab", state)

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

        self.assertEqual(lesson["status"], "needs_student_action")
        self.assertEqual(lesson["steps"][1]["status"], "needs_student_action")
        self.assertIn("sudo mv", "\n".join(lesson["steps"][1]["commands"]))
        self.assertFalse(lesson["baseline_ready"])

    def test_cleanup_lesson_requires_student_action_for_stale_taint(self):
        state = _base_state()
        state["evidence"]["cni"]["classification"]["state"] = "stale_taint"
        state["evidence"]["cni"]["classification"]["stale_taint"] = {
            "detected": True,
            "taints": [{"node": "cp", "key": "node.cilium.io/agent-not-ready"}],
            "summary": "stale taints detected (1)",
        }

        lesson = lessons.build_lesson_run("reset_networking_lab", state)

        self.assertEqual(lesson["steps"][2]["status"], "needs_student_action")
        self.assertIn("kubectl taint nodes cp node.cilium.io/agent-not-ready-", lesson["steps"][2]["commands"])


if __name__ == "__main__":
    unittest.main()
