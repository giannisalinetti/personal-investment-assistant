# PIA documentation

Operator and architecture guides for Personal Investment Assistant.

| Guide | Audience |
|-------|----------|
| [agent_architecture.md](agent_architecture.md) | How Monitor (LangGraph) and Advisor work |
| [compose.md](compose.md) | Home packaging — Docker / Podman Compose (host Ollama default) |
| [kubernetes.md](kubernetes.md) | Kubernetes (kind, GPU, cloud-only) |
| [openshift.md](openshift.md) | OpenShift + OpenShift AI (vLLM serving) |
| [plans/get_performance_tool.md](plans/get_performance_tool.md) | Advisor `get_performance` / `rank_performance` |
| [plans/get_risk_tool.md](plans/get_risk_tool.md) | Advisor `get_risk` (std / beta / max drawdown) |
| [plans/allocation_advisor.md](plans/allocation_advisor.md) | Stated-capital allocation + investor preferences |

Deep product specification remains in [`../SPEC.md`](../SPEC.md). Env template: [`../.env.example`](../.env.example).

## Keep docs in sync

When you change any of the following, update the matching file under `docs/` in the **same** change set:

| Change area | Update |
|-------------|--------|
| Monitor graph, nodes, state, skills, Advisor prompts / tools | `agent_architecture.md` |
| Compose files, profiles, Ofelia, host Ollama URLs | `compose.md` |
| `deploy/k8s/` manifests, CronJobs, overlays | `kubernetes.md` |
| OpenShift Routes, RHOAI / InferenceService wiring | `openshift.md` |
| LLM provider env vars | all deploy guides that mention providers + `.env.example` |
