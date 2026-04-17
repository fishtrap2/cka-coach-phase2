# Explanation Quality Bar

## Purpose

This document defines the current quality bar for cka-coach explanations.

It exists so we can preserve what is working well as the product evolves:

* explanations should feel clear and trustworthy
* explanations should be useful to **LFS258 / CKA students**
* explanations should let a student keep learning **from inside the pod / cluster context itself**

The goal is not to maximize detail.
The goal is to produce answers that are:

* accurate
* evidence-led
* educational
* light enough to keep reading

---

## Current Reference Standard

The current reference standard is the strong L4.3 / Cilium answer produced from:

> `python src/main.py ask "what does Cilium do?" --allow-host-evidence --allow-web`

Why this answer is our current bar:

* it explains **what Cilium is doing in this cluster**
* it starts with **direct cluster evidence**
* it distinguishes **CNI vs kubelet vs kube-proxy**
* it gives useful background knowledge without becoming a lecture
* it clearly marks what is **not yet proven**
* it gives short, reasonable next steps
* it is readable enough that a student can keep exploring **without leaving the cka-coach environment**

---

## Second Reference Standard

We also now have a second strong reference pattern:

* an L4.3 / Cilium answer where the cluster still indicates Cilium clearly,
  but the health picture is only partially healthy because recent agent
  restarts or readiness failures are present

Why this answer matters:

* it preserves clear CNI identification
* it does not collapse into “healthy” just because the platform is still present
* it does not collapse into “broken” just because some health signals are noisy
* it explains a **partially healthy / degraded-but-present** state in a way a student can understand

This is important because real student clusters are often not perfectly clean.
The explanation quality bar must therefore cover both:

* clean, healthy explanation cases
* partially healthy / unstable explanation cases

---

## Quality Criteria

A strong cka-coach explanation should usually do all of the following:

### 1. Start with the observed cluster

Lead with what the cluster evidence shows now.

Good:

* “From the cluster evidence, Cilium is installed and running in kube-system...”

Avoid:

* leading with generic textbook background before explaining the current cluster

### 2. Explain the role clearly

State what the component does in the Kubernetes system, in plain language.

Good:

* what the CNI is responsible for
* what kubelet does
* what kube-proxy does
* how those roles differ

### 3. Separate evidence from background knowledge

The student should be able to tell:

* what is directly observed from the lab
* what is general Kubernetes knowledge

This keeps the answer trustworthy and teaches good engineering habits.

### 4. Keep uncertainty visible

If something is not directly proven, say so clearly.

Good examples:

* “cannot be claimed here without more evidence”
* “official vendor documentation would still be needed for exact feature confirmation”

Avoid:

* implying a feature is enabled just because it is commonly associated with a platform

### 5. Stay immersive inside the cluster

A student should be able to continue learning from **inside the pod / cluster environment**.

That means the answer should:

* use evidence available from cka-coach’s collected state
* give next steps that the student can realistically run from the current environment
* reduce the need to leave the lab just to understand the concept

This is a core product principle:

> the answer should be right there with the student inside the cluster context

### 6. Be light enough to read

The answer should be substantial but not overpowering.

Good answers:

* explain the important thing first
* use short bullet lists where helpful
* avoid turning every answer into a long essay

### 7. Handle partial health honestly

Strong answers should handle “present but unstable” states well.

Good answers:

* identify the component correctly
* explain that it is still present or active
* describe recent health instability proportionally
* avoid flipping too quickly to either “fully healthy” or “fully broken”

This matters especially for:

* CNI agents with restarts
* readiness probe failures
* control components that are present but not fully healthy

---

## Review Checklist

When reviewing a new explanation behavior, ask:

1. Does it identify the current component/system correctly from evidence?
2. Does it explain the role clearly for a student?
3. Does it separate direct evidence from background knowledge?
4. Does it avoid unsupported claims?
5. Does it help the student keep learning from inside the cluster context?
6. Is it concise enough to stay approachable?
7. If the system is only partially healthy, does the answer describe that state proportionally?

If the answer misses several of these, it is below the current quality bar.

---

## How To Use This Going Forward

This document should guide:

* prompt refinements
* explanation reviews
* future quality checks or fixtures
* demo-readiness decisions

Future branches should be compared against this standard, especially for:

* L4.3 CNI explanations
* connectivity explanations
* policy-aware explanations

The rule of thumb is:

> if a student can stay inside cka-coach, understand the current system better, and know what to check next, the explanation is doing its job
