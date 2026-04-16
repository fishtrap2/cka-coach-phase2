# Learning Moment: Structured Branching for Safe Feature Development

## Context

During Phase 2 development of cka-coach, we transitioned from working on a single branch to using a structured branching model to safely build and test new features.

This shift was necessary as the system evolved from simple detection logic into a more complex, user-facing product with UI, explainability, and multiple interacting features.

---

## What We Did

We introduced a three-level branching model:

### 1. Stable baseline (`main`)

* Represents a known, working version of the application
* Tagged as `v0.5.0-phase2-foundation`
* Used for stability, demos, and rollback

### 2. Integration branch (`feature/networking-phase2`)

* Acts as the working “Phase 2” environment
* Combines completed features before promoting them to `main`
* Allows multiple features to be integrated safely without breaking the stable version

### 3. Feature branches (small, focused changes)

Examples:

* `feature/l43-capabilities-policy-summary`
* `feature/cni-version-evidence`

Each branch:

* starts from the integration branch
* implements a single, well-defined change
* is tested independently
* is merged back only when correct

---

## Example Flow

1. Start from integration branch:

   ```
   feature/networking-phase2
   ```

2. Create a feature branch:

   ```
   feature/l43-capabilities-policy-summary
   ```

3. Implement and fix issues:

   * add capability inference
   * add policy summary
   * fix health and wording issues

4. Merge back into integration branch:

   ```
   feature/networking-phase2
   ```

5. Create next small feature branch:

   ```
   feature/cni-version-evidence
   ```

6. Add one new commit:

   ```
   feat: add direct CNI version evidence
   ```

---

## What the Git History Shows

A simplified view:

```
main (stable baseline)
   ↓
feature/networking-phase2 (integration)
   ↓
feature/cni-version-evidence (new work)
```

Each new feature is layered cleanly on top of the previous work.

---

## Key Lessons

### 1. A branch is just a pointer

Creating a branch does not create work — it only creates a label for where work will occur.

### 2. Commits are the real progress

A branch without commits ahead of its parent has no functional difference.

### 3. Small branches reduce risk

By limiting each branch to one concern:

* bugs are easier to isolate
* testing is simpler
* merges are safer

### 4. Integration branches enable safe iteration

Working in an integration branch allows:

* multiple features to evolve together
* stability in `main`
* controlled promotion of features

### 5. Remote tracking matters

When working across machines:

* branches must track their remote counterparts
* otherwise `git pull` and `git push` will not behave as expected

---

## Product Insight

This workflow mirrors good product development:

* **Feature branches = individual ideas**
* **Integration branch = working product iteration**
* **Main branch = released experience**

It ensures that:

> we improve the system without breaking the user experience.

---

## Summary

We learned to move from:

> “make changes and hope they work”

to:

> “build, test, and integrate features in controlled layers”

This is essential for scaling both:

* code complexity
* product quality
