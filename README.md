# Clearance · Review Gateway for Chinese Ops Backoffices

[中文版](README.zh-CN.md)

Submit → decide → auto-approve / auto-reject / human. For articles, comments,
and tickets in Chinese-language backoffices. Wrong auto-pass is treated as more
expensive than human review, so `auto_err` must stay 0.

## Principles

1. **Semantic events**: business semantics only; payloads over 4KB are rejected,
   large objects by reference (`body_ref` + `context.get`).
2. **Minimum sufficient context** per decision.
3. **AI holds no execution power**: engine output must pass registry validation
   and gating; it cannot be bypassed.
4. **Confidence gating**: auto-execute only above threshold, otherwise human.
   With no model engine available the heuristic still auto-blocks spam/fraud but
   never auto-approves — a fallback engine may block, never pass (offline-first,
   execution fail-closed).
5. **Everything auditable**: append-only audit log; terminal states
   (`pending` → `approved` / `rejected`) never transition back.

## Quickstart

```bash
./start.sh                 # sidecar :8685 + API :8686 + web :5173, Ctrl-C stops all
NO_SIDECAR=1 ./start.sh    # skip sidecar, heuristic-only instant start
```

Requires `python3` + `node` + `pnpm`. The core is stdlib-only Python; `uv` is
used when present, system python otherwise. If a port is taken the script
aborts with the pid (`./start.sh --force` to reclaim).

```bash
python3 -m unittest discover -s tests -v   # self-check
python3 -m core.cli demo                    # end-to-end sample run
```

Frontend: `cd web && pnpm install && pnpm dev` (`/api` proxied to `:8686`).

## Engines (swappable)

| Engine | Nature | When absent |
|---|---|---|
| `rules` | Deterministic rules, no model | Never absent |
| `laya:sidecar` | Self-hosted Laya ($0), separate process, `multilingual` default | Skipped |
| `jev` | TypeSafe cloud API (`TYPESAFE_API_KEY` required) | Skipped |
| `heuristic` | Keyword fallback | Always on |

Order is overridable via `ENGINE_ORDER` (cost-first by default).
Compare: `python3 -m eval.sweep samples.jsonl --engine {rules,laya:sidecar,jev,heuristic}`.

## Calibration & labels

```bash
python3 -m eval.sweep eval/samples_example.jsonl  # synthetic samples, chain check only
python3 -m eval.export --out eval/samples.jsonl   # accumulate labels from audit + resolutions
python3 -m eval.calibrate --samples eval/samples.jsonl --out eval/calibration.json
```

Temperature fitting works with dozens of samples; fine-tuning needs 500+
(open the Kaggle notebook then, swap checkpoint via `MODEL_DIR`, A/B with sweep).
Rows with `expected==review` are skipped. Synthetic samples never go into a
fitted table.

## API & config

| Endpoint | Purpose |
|---|---|
| `POST /api/review/submit` | Submit `{kind,title,body,meta?}` (large bodies stored by reference) |
| `POST /api/review/<id>/resolve` | Human decision `{outcome, actor}` |
| `POST /api/context/get` | Fetch referenced fields, `["*"]` forbidden |
| `GET /api/queue?state=` · `GET /api/stats` · `GET /api/health` | Queue / stats / engine status |
| `GET /api/events` | SSE stream (hello + accepted/running/terminal/submitted/resolved/stats) |

| Env | Default | Meaning |
|---|---|---|
| `ENGINE_ORDER` | rules,laya:sidecar,jev,heuristic | Cascade order |
| `LAYA_SIDECAR_URL` / `LAYA_SIDECAR_TIMEOUT` | 127.0.0.1:8685 / 15s | Sidecar address and timeout |
| `TYPESAFE_API_KEY` / `JEV_MODEL` | empty / jev-latest | Jev cloud key and model |
| `LAYA_DEFAULT` / `LAYA_PRELOAD` / `LAYA_HEAD_MAX_LEN` | multilingual / english,multilingual / empty | Routing default / preload list / option budget |
| `MODEL_DIR` / `CALIBRATION_FILE` | Hub default / eval/calibration.json | Fine-tuned checkpoint / temperature table (hot-reloaded) |
| `COD_BLOB_THRESHOLD` | 2048 chars | Body spill threshold |
| `PORT` / `CLEARANCE_DATA_DIR` | 8686 / data/ | API port / data dir |

## Layout (repo root is the product)

```
├── core/               engine slots + gateway + store + services
├── vendor/
│   ├── laya_sidecar/   isolated Laya service (torch deps, tracked)
│   └── laya/           upstream checkout (read-only, ignored)
├── eval/               sweep + fitting + label export + samples
├── web/                frontend (pnpm + Vite + React + TS)
├── tests/              unittest (stdlib)   ·   data/ runtime data
└── start.sh            one-command startup
```

Action registry (7 actions; idempotency/risk declared only in `gateway.py:REGISTRY`):
`context.get`(L0), `review.defer`(L1), `human.task.create`(L1),
`review.approve`(L2), `review.reject`(L2), `notify.send`(L2),
`session.complete`(L0). L3/L4 do not exist — anything irreversible goes to a human.

## Non-goals

Recording / desktop automation / browser scraping / low-code canvas /
Electron / screenshots into the protocol.

## Roadmap

- [ ] 500+ real labels → first fine-tune + A/B regression (`MODEL_DIR`)
- [ ] `cancelled` state (expired/withdrawn human tasks)
- [ ] Structured rejection reasons (trainable feedback)
- [ ] Threshold presets (strict/balanced/lenient)
- [ ] Fully async submit (202 + poll; SSE progress events suffice for now)

## License / history

MIT (see `LICENSE`). Legacy RPA assets are archived on the `archive/apa-rpa`
branch. Behavior is defined by code and tests.
