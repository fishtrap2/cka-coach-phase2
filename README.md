# cka-coach Phase 2

**Private development repo for the next evolution of cka-coach**

---

## Vision

> Why leave the cluster to learn Kubernetes networking… when the cluster can teach you from inside?

cka-coach Phase 2 evolves the project into an **in-cluster learning assistant** that helps students understand:

* where applications live (ELS model)
* how Kubernetes networking actually works
* how traffic flows between workloads
* why connectivity succeeds or fails
* how policy affects behavior

All **from inside the cluster itself**.

---

## Who this is for

Prospective and active **LFS258 / CKA students** who:

* understand basic Kubernetes objects
* struggle with *where things actually live*
* want to build intuition for:

  * pod networking
  * CNI responsibilities
  * service routing
  * network policy and Zero Trust concepts

---

## What is new in Phase 2

Phase 2 introduces a **networking and security learning layer** on top of the existing ELS model.

### Core capabilities

* **CNI-aware cluster understanding**

  * Detect and interpret the cluster networking layer
  * Work across *any CNI plugin*

* **Network diagram (in-cluster perspective)**

  * Visualize pod → node → CNI → service → destination
  * Show where the application actually lives in the ELS stack

* **Connectivity explanation**

  * Explain why traffic is allowed or denied
  * Identify which layer is responsible
  * Provide evidence and confidence

* **CNI comparison & migration guidance**

  * Help students understand differences between CNIs
  * Explain implications of migrating (e.g. bridge → Calico)

* **Progressive visibility**

  * Works generically across clusters
  * Enhances explanations when richer signals are available

---

## CNI-agnostic by design

cka-coach Phase 2 is built to work across:

* default / bridge-based networking
* advanced CNIs such as Calico or Cilium

The goal is not to teach a specific plugin, but to teach:

> **how Kubernetes networking works, regardless of implementation**

---

## Enhanced capabilities (when available)

When advanced networking platforms are present, cka-coach can provide:

* richer traffic reasoning
* policy-aware explanations
* safer “what-if” reasoning about connectivity

These are **enhancements**, not requirements.

---

## Product philosophy

cka-coach is not a dashboard.

It is a **learning system** that:

1. explains what it sees
2. explains why it thinks that
3. maps everything back to the ELS model
4. highlights uncertainty when present

---

## Phase 2 focus areas

* CNI detection and abstraction layer
* Network diagram and datapath explanation
* Connectivity reasoning (pod ↔ pod / service)
* Introductory policy reasoning (allow/deny)
* CNI comparison and migration guidance

---

## Status

Phase 2 is under active development in this private repository.

The public Phase 1 prototype is available here:
https://github.com/fishtrap2/cka-coach

---

## Guiding idea

> Kubernetes networking is the invisible layer students struggle with most.
> cka-coach makes that layer visible, explainable, and learnable.

