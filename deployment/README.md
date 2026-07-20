# Phase 3 deployment assets

These assets prepare a PAPER-only deployment; they do not deploy one.

- `compose.yaml`: one non-root monitor-only container, read-only root filesystem,
  four named writable volumes, tmpfs, dropped capabilities, liveness and graceful stop.
- `kubernetes/phase3-paper.yaml`: singleton StatefulSet, RWO persistence,
  read-only root, non-root/seccomp/no-new-privileges, liveness/readiness, PDB and
  default-deny network policy. Replace the all-zero image digest before use.
- `terraform/`: provider-free OpenTofu/Terraform contract. It validates immutable
  image/singleton/PAPER/least-privilege inputs and creates no cloud resource.
- `requirements-runtime.lock`: direct runtime versions matching the frozen strategy
  environment. The image build re-verifies the strategy artifact and fails on drift.

The default process is `phase3_supervisor.py`. It monitors status/alerts and writes a
heartbeat; it deliberately processes no market event. Forward stages still require
explicit immutable event metadata through `run_forward_paper.py`. This separation keeps
an infrastructure smoke from being counted as Forward PAPER history.

Local commands when Docker is available:

```bash
docker compose -f deployment/compose.yaml config
docker compose -f deployment/compose.yaml build --pull
docker compose -f deployment/compose.yaml up -d
docker compose -f deployment/compose.yaml ps
docker compose -f deployment/compose.yaml restart phase3-monitor
docker compose -f deployment/compose.yaml down
```

Before Kubernetes use, build/sign the image, replace its template digest, select an
encrypted RWO storage class, run the static validator, and review egress/provider needs.
The checked-in NetworkPolicy denies all egress because no real provider is authorized.

Backup each writable volume with `scripts/phase3_backup.py`. Backup uses SQLite's online
backup API, skips WAL/SHM sidecars, hashes every output, rejects symlinks/unexpected files,
and restores only to a new path with `RESTORE:<manifest_sha256>` confirmation. It never
overwrites an existing target.

Current validation is conditional: this workstation has no Docker/Podman, kubectl, or
Terraform/OpenTofu executable. Static validation and local process/backup smoke can pass,
but image build, orchestrator start, encrypted storage, cloud logging, notifications and
cloud deployment remain unverified/not deployed.
