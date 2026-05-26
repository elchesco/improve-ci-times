# Code companion — backend CI optimisation post

Stand-alone, copy-pasteable files for every code block in
[`docs/blog-backend-ci-optimization.md`](../blog-backend-ci-optimization.md). 

Each folder maps to one round of the blog narrative:

```
00-starting-point/   the test job, Dockerfile, conftest before any work
01-uv/               drop pip for uv (Dockerfile + CI snippet)
02-buildkit/         BuildKit cache mounts + setup-buildx + --push
03-xdist-traps/      per-worker DB + DATABASE_URL alignment
04-template-db/      Postgres template DB + pg_advisory_lock
                     (plus the filelock dead-end as documentation)
05-diagnostic/       the measurement step that broke the assumption
06-final/            final shape — 4 matrix shards, no xdist, cumulative
                     Dockerfile + complete conftest
```

## Suggested reading order

1. **`00-starting-point/`** — what we had.
2. Each round folder in order — the post's narrative.
3. **`06-final/`** — the result.

## Notes

* The xdist code (`03`, `04`) is still present in `06-final/conftest.py`
  for local `pytest -n N` runs even though the CI dropped xdist in
  favour of serial matrix shards.
* `04-template-db/filelock-attempt-DEAD-END.py` is kept around so
  future-you (or the next contributor) doesn't relitigate the
  filelock-vs-advisory-lock choice from scratch.
* `05-diagnostic/` is a one-off — drop the step from CI once the
  measurements have shaped the decision.
* The full final workflow includes more than the test job (lint,
  build-and-deploy, etc.). `06-final/deploy-backend.yml` contains
  only the `test` + `coverage` jobs since those are what the post
  focuses on.

## Pin versions used in the post

| Tool | Version |
| --- | --- |
| `uv` (Astral) | `0.5.11` |
| `astral-sh/setup-uv` | `v6` |
| `docker/setup-buildx-action` | `v3` |
| `coverage` (combine job) | `7.6.1` |
| `pytest` | `8.2.0` |
| `pytest-xdist` | `3.6.1` |
| `pytest-split` | `0.9.0` |
| Postgres (CI service) | `15` |
| Python (backend) | `3.11` |
