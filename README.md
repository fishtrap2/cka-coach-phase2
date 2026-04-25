# cka-coach — Phase 2

> "What is actually happening inside your Kubernetes cluster?"

cka-coach is a **Kubernetes learning system** that turns a running cluster into a **teaching instrument panel**.

It helps CKA / LFS258 students understand:

- where workloads live (ELS model)
- how Kubernetes networking actually works
- how packets move between pods and nodes
- how policy and dataplane decisions affect traffic
- how to debug and reason about cluster state

---

## Phase 2 — Networking Visibility Milestone (v0.6.0)

Phase 2 introduces a **complete networking understanding layer** grounded in real cluster evidence.

### Networking Panel (Source of Truth)

- Detects active CNI (Calico, Cilium, etc.)
- Confidence-based interpretation (not guesses)
- Policy awareness (NetworkPolicy presence)
- Observability integration (Goldmane + Whisker)
- Node-scoped evidence (per-node visibility)
- Version provenance (from actual running components)

### Network Visual Panel (NEW)

A **first-of-its-kind in-cluster network diagram** showing:

- Pod -> veth -> host -> overlay -> remote node
- VXLAN / BGP transport
- Pod CIDRs and node IPs
- Kernel / namespace reality (netns, veth pairs)
- Policy + observability plane

This is the "pay dirt" of cka-coach: where abstraction meets reality.

### CNI State Provenance

- Multi-source detection (cluster + node)
- Distinguishes:
  - active CNI
  - residual artifacts
  - unknown states
- Prevents false conclusions during migrations

### Known-Good Baseline + Cleanup Lesson

- First **active coaching workflow**
- Guides student through:
  - removing stale CNI state
  - restoring cluster baseline
- Node-scoped remediation scripts
- Introduces real-world debugging mindset

### Correct Architecture Representation

cka-coach correctly models:

- **Operator plane** (Tigera Operator)
- **DaemonSet dataplane** (`calico-node`)
- **Control components** (controllers, apiserver)

This avoids a major learning gap in most tools.

---

## The ELS Model (Everything Lives Somewhere)

cka-coach is built around the ELS model:

Applications  
↓  
Pods  
↓  
Kubernetes Objects (desired state)  
↓  
Controllers / Operators  
↓  
Node Agents (kubelet, kube-proxy, CNI)  
↓  
Container Runtime (containerd)  
↓  
OCI Runtime (runc)  
↓  
Linux Kernel (namespaces, cgroups)  
↓  
Infrastructure

Every explanation maps back to **where something actually lives**.

---

## Who this is for

- CKA / LFS258 students
- Engineers learning Kubernetes networking
- Anyone asking:
  - "why is this not working?"
  - "where is this actually happening?"

---

## Example: What you can now see

- Calico running with VXLAN CrossSubnet
- Pod CIDRs across nodes
- Node-to-node overlay transport
- Policy plane (Goldmane / Whisker)
- Kernel-level networking constructs
- Real dataplane (`iptables`)

---

## Product Philosophy

cka-coach is not a dashboard.

It is a **teaching system** that:

1. Shows current state
2. Explains why
3. Provides evidence
4. Highlights uncertainty
5. Guides the student forward

---

## How to run

### From source

```bash
git clone https://github.com/fishtrap2/cka-coach-phase2.git
cd cka-coach-phase2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key_here
streamlit run ui/dashboard.py
```

---

## Roadmap

Next steps:

- Guided install lessons (Calico, Cilium)
- Policy reasoning (allow/deny simulation)
- Multi-CNI comparison mode
- Agent-driven troubleshooting workflows
- MCP / tool integration for deeper system introspection

---

## Status

- Phase 1: completed (public repo)
- Phase 2: networking foundation complete in this release
- Phase 2+: active coaching and deeper reasoning in progress

---

## Related

Phase 1 repo:

[https://github.com/fishtrap2/cka-coach](https://github.com/fishtrap2/cka-coach)
