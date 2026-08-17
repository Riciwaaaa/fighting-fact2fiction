# Experiment registry

Tracked experiment intentions and milestone outcomes live here; large and potentially sensitive
runtime artifacts remain under Git-ignored `artifacts/`.

## Separation of concerns

- `registry.json`: stable experiment IDs, dependencies, status, and result-document pointers.
- `docs/EXPERIMENT_LOG.md`: human-readable chronological decisions and findings.
- `artifacts/runs/progress/<experiment>.json`: current machine-readable progress snapshot.
- `artifacts/runs/progress/<experiment>.events.jsonl`: append-only runtime event history.
- `artifacts/runs/<stage>/...`: manifests, sanitized packets, private traces, and model outputs.
- `artifacts/evaluation/...`: gold-joined results. Inference code must never read these files.

Run `python scripts/show_experiment_progress.py` for the current local runtime state. A tracked
status is updated only at scientific milestones so it does not create one Git diff per endpoint.
