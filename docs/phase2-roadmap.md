# cka-coach Phase 2 Roadmap

## 1. Product Overview

cka-coach Phase 2 transforms the project into a:

> **CNI-aware Kubernetes networking and security learning assistant**

It operates from inside the cluster and helps students understand:

* where workloads live (ELS model)
* how networking works across layers
* how connectivity behaves
* how policy influences traffic

---

## 2. Problem Statement

Students preparing for LFS258 / CKA often:

* memorize commands without understanding system behavior
* struggle to visualize:

  * pod networking
  * CNI responsibilities
  * service routing
* cannot explain:

  * why traffic works or fails
  * where policy applies

The Kubernetes networking layer remains **invisible and abstract**.

---

## 3. Product Goals

### Primary goal

Make Kubernetes networking **visible, explainable, and intuitive** from inside the cluster.

### Secondary goals

* Reinforce the ELS model through real system observation
* Provide safe introduction to network policy and Zero Trust concepts
* Support learning across different cluster configurations

---

## 4. Non-Goals (Important)

* Not a full observability platform
* Not a replacement for kubectl or dashboards
* Not a network automation tool
* Not tied to any single CNI plugin

---

## 5. Core Concepts

### ELS Model (unchanged foundation)

* Execution (workloads, pods)
* Location (node, cluster)
* Structure (control plane, services)

### New in Phase 2

#### Networking Layer

* CNI responsibility
* pod-to-pod communication
* node routing
* service path

#### Connectivity Reasoning

* path explanation
* success/failure reasoning
* layer attribution

#### Policy (minimal, educational)

* allow / deny reasoning
* basic policy awareness
* staged vs enforced (when available)

---

## 6. Key Features

### 6.1 CNI Detection & Abstraction

System should:

* detect CNI plugin where possible
* classify confidence (high / medium / low)
* identify capabilities:

  * policy support
  * observability signals

Output shape:

```
{
  cni: "...",
  confidence: "...",
  evidence: [...],
  capabilities: {...}
}
```

---

### 6.2 Network Diagram

Visual representation of:

* Pod
* Node
* CNI layer (explicitly shown)
* Service routing
* Destination

Goals:

* show where traffic flows
* highlight responsibility boundaries
* reinforce ELS mapping

---

### 6.3 Connectivity Explainer

User can ask:

* “Can pod A talk to pod B?”
* “Why is this failing?”

System responds with:

1. expected path
2. observed/inferred behavior
3. responsible layer
4. explanation
5. uncertainty (if any)

---

### 6.4 CNI Comparison & Migration Guidance

Explain:

* current CNI capabilities
* differences vs target CNI
* implications:

  * networking model
  * policy support
  * observability
* migration risks

Goal:

> teach decision-making, not automate changes

---

### 6.5 Progressive Enhancement Layer

When advanced signals are available:

* richer connectivity explanations
* policy reasoning improvements
* “what-if” analysis (e.g. staged vs enforced)

These are **optional enhancements**.

---

## 7. Milestones

### Milestone 1 — Foundation

* README + roadmap
* CNI detection (basic)
* networking overview panel
* “where this app lives” panel

---

### Milestone 2 — Visualization

* network diagram (v1)
* ELS-integrated view
* basic datapath explanation

---

### Milestone 3 — Connectivity Reasoning

* pod-to-pod explanation
* service path reasoning
* basic allow/deny explanation

---

### Milestone 4 — Migration Guidance

* CNI comparison module
* migration explanation workflow
* risk and safety explanations

---

### Milestone 5 — Enhanced Visibility (Hackathon layer)

* advanced signal interpretation (if present)
* richer explanation quality
* one polished demo scenario:

  * connectivity failure explanation

---

## 8. UX Principles

Every explanation should answer:

1. What I found
2. Why I think that
3. What layer owns this
4. What you should learn
5. What I am not sure about

---

## 9. Success Criteria

* Student can explain pod-to-pod communication clearly
* Student understands role of CNI
* Student can reason about connectivity failures
* Student gains intuition, not just commands

---

## 10. Guiding Principle

> Do not add features unless they improve understanding of how Kubernetes actually works.

