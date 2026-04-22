# Calico Known-Good Baseline

## Purpose

This runbook captures the known-good Calico baseline for the `cka-coach-phase2` lab / hackathon environment after cleaning the old CNI state and reinstalling Calico successfully.

Use this document to:
- restore the cluster to a working Calico baseline
- verify that Layer 4.3 should resolve to **Calico** in cka-coach
- avoid repeating earlier cleanup / install mistakes

---

## Environment

- Cluster type: kubeadm-style lab / LFS258 environment
- Nodes:
  - `cp` (`10.2.0.2`)
  - `lfs258-k8sfunda-worker1` (`10.2.0.3`)
- Kubernetes version: `v1.33.1`
- Container runtime: `containerd://2.2.1`
- Pod CIDR: `192.168.0.0/16`
- Per-node pod CIDRs observed:
  - `cp` → `192.168.0.0/24`
  - `lfs258-k8sfunda-worker1` → `192.168.1.0/24`

---

## Pre-install clean baseline

Before installing Calico, the cluster should be in a clean **no-CNI** state.

Expected characteristics:
- no active Cilium or Calico pods
- kubelet may report `NetworkPluginNotReady` / `cni plugin not initialized`
- nodes may not be fully Ready for pod networking until the new CNI is installed
- old residual `.bak` files are acceptable if they are not active CNI config

Important lesson learned:
- do **not** treat `tunl0` by itself as a cleanup blocker
- `tunl0` is not a reliable success/failure gate for cleanup
- the real baseline blockers are active CNI config, active `cali*` interfaces, mixed dataplane ownership, or live Calico/Cilium control-plane artifacts

---

## Local manifest handling

If using direct URLs with `kubectl create -f <url>`, the manifests are **not** stored locally.

To keep a local copy for review:

```bash
curl -O https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/tigera-operator.yaml
curl -O https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/custom-resources.yaml
```

`custom-resources.yaml` should be edited/reviewed locally before applying.

---

## Calico install steps

### 1. Install the Tigera Operator

```bash
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/tigera-operator.yaml
```

### 2. Confirm pod CIDR in `custom-resources.yaml`

The default IP pool must match the cluster pod network:

```yaml
spec:
  calicoNetwork:
    ipPools:
    - cidr: 192.168.0.0/16
```

### 3. Apply `custom-resources.yaml`

```bash
kubectl create -f custom-resources.yaml
```

---

## Important installation correction discovered during bring-up

The initial install came up partially, but `calico-node` was not ready because BGP peering was not establishing.

Observed failure pattern:
- `calico-node` readiness blocked on BIRD
- log message indicated `BGP not established`
- the Installation used:
  - `encapsulation: VXLANCrossSubnet`
  - `bgp: Enabled`

For this lab baseline, **BGP needed to be disabled**.

### Fix applied

```bash
kubectl patch installation default --type merge -p '
spec:
  calicoNetwork:
    bgp: Disabled
'
```

Then recycle `calico-node`:

```bash
kubectl delete pod -n calico-system -l k8s-app=calico-node
```

---

## IPPool / operator reconciliation issue encountered

After Calico itself became healthy, `ippools` remained degraded even though the IPPool object existed and looked correct.

Observed pattern:
- `calico` healthy
- `apiserver` healthy
- `goldmane` healthy
- `whisker` healthy
- `ippools` degraded due to operator/API reconciliation issue

### Recovery actions used

```bash
kubectl rollout restart deploy/calico-apiserver -n calico-system
kubectl rollout restart deploy/calico-kube-controllers -n calico-system
kubectl rollout restart deploy/tigera-operator -n tigera-operator
```

---

## Known-good Installation shape

This is the important part of the resulting Installation:

```yaml
spec:
  calicoNetwork:
    bgp: Disabled
    ipPools:
    - cidr: 192.168.0.0/16
      encapsulation: VXLANCrossSubnet
      natOutgoing: Enabled
      nodeSelector: all()
    linuxDataplane: Iptables
  cni:
    type: Calico
```

---

## Known-good verification commands

### Cluster status

```bash
kubectl get tigerastatus
kubectl get pods -A
kubectl get installation default -o yaml
kubectl get ippools.crd.projectcalico.org -o yaml
```

### Expected healthy outcome

`kubectl get tigerastatus` should show all major components healthy, including:
- `apiserver`
- `calico`
- `goldmane`
- `ippools`
- `whisker`

### Helpful detailed checks

```bash
kubectl get pods -n calico-system -o wide
kubectl get nodes -o wide
kubectl get installation default -o yaml
kubectl get ippools.crd.projectcalico.org -o yaml
```

---

## Whisker access

```bash
kubectl port-forward -n calico-system service/whisker 8081:8081
```

Then open:

```text
http://localhost:8081
```

---

## cka-coach expectations at this baseline

Once this baseline is healthy, cka-coach should report Layer 4.3 approximately as:
- `CNI: Calico`
- `confidence: high`
- `health/status: working` or `healthy`
- policy capability present

If cka-coach still shows `unknown`, that is now a **dashboard evidence / reconciliation bug**, not a cluster install problem.

---

## Lessons learned

1. Do not over-focus on `tunl0` during cleanup.
2. A clean no-CNI baseline is easier than trying to recover a mixed dataplane.
3. In this lab, VXLAN with BGP disabled was the right bring-up choice.
4. `calico-node` readiness issues should be debugged from the actual readiness/log reason first.
5. If `ippools` is the only degraded status, the dataplane may already be healthy and the issue may be limited to operator/API reconciliation.
6. cka-coach should distinguish:
   - cleanup blockers
   - kernel plumbing
   - current active dataplane owner

---

## Suggested snapshot artifact after successful install

Save the outputs of:

```bash
kubectl get tigerastatus
kubectl get pods -A
kubectl get installation default -o yaml
kubectl get ippools.crd.projectcalico.org -o yaml
```

This becomes the reference for future restore / demo prep.
