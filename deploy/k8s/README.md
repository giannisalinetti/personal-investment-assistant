# Kubernetes deploy (Phase 5b)

**Full guide:** [docs/kubernetes.md](../../docs/kubernetes.md)

OpenShift + OpenShift AI: [docs/openshift.md](../../docs/openshift.md). Architecture: [docs/agent_architecture.md](../../docs/agent_architecture.md). Compose: [docs/compose.md](../../docs/compose.md).

## Layout

```
deploy/k8s/
  base/                 # namespace, PVCs, pia-web, pia-bot, CronJobs, watchlists ConfigMap
  overlays/
    stub/               # OpenAI-compatible stub as Service vllm (kind / no GPU)
    gpu/                # real vLLM Deployment (NVIDIA)
    cloud-only/         # no vLLM; Anthropic/OpenAI via Secret
```

CronJobs own the Monitor schedule; Deployments set `PIA_MONITOR_SCHEDULER=false`.

## Quick stub apply (kind)

```bash
kubectl apply -k deploy/k8s/overlays/stub
kubectl -n pia create job --from=cronjob/pia-run-manual "pia-run-manual-$(date +%s)"
kubectl -n pia port-forward svc/pia-web 8765:8765
```

See [docs/kubernetes.md](../../docs/kubernetes.md) for secrets, GPU Layer 3, cloud-only, and troubleshooting.
