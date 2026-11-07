# Agent Workflow Lab

An offline, executable companion to an article about accountable AI agents.
Study the boundary between a planner's proposal and an authorized action.
No API keys, model calls, real messaging, accounts or private data are needed.

[Русское описание](README.ru.md)

## Run

Use Python 3.10 or later. The core uses only the standard library.

```sh
python3 agent_lab.py
python3 -m unittest -v
```

Expected demonstration: a synthetic preview, `DELIVERY: accepted`, and an
algorithmic reply. Delivery is simulated; nothing is sent to another person.

Optional LangGraph orchestration:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-graph.txt
.venv/bin/python langgraph_demo.py
.venv/bin/python -m unittest -v
```

The optional example pauses for approval and resumes the same graph thread.
It also runs entirely offline after dependencies have been installed.
`requirements-graph.txt` pins the top-level package; it is not a complete
transitive lockfile. Tested locally with Python 3.12 and LangGraph 1.2.20.

## Read the implementation

- `agent_lab.py`: library API, ownership checks, versioned preview, expiry,
  atomic approval/outbox insertion, delivery outcomes, metadata-only events.
- `discuss`: bounded proposal/observation loop with a read-only FAQ tool.
  A scripted planner can demonstrate the control flow without impersonating a
  real language model. Proposals cannot invoke sending or approvals.
- `langgraph_demo.py`: the same domain code orchestrated as prepare → review
  (`interrupt`) → deliver. Preview creation is outside the replayed review node.
- Tests: stale and forged previews, cross-principal access, replay, expiry,
  restart, uncertain network outcomes, competing claims and planner limits.

```python
from agent_lab import Inbox

box = Inbox('demo.sqlite')
case = box.create('authenticated-demo-user', 'A synthetic inquiry')
preview = box.preview('authenticated-demo-user', case)
print(preview.text)
# Only after explicit approval by that authenticated user:
box.approve('authenticated-demo-user', preview)
box.dispatch(lambda action_id, text: 'accepted')  # simulated transport
box.close()
```

`approve` is an application API, not an HTTP authentication boundary. The
embedding adapter must establish the principal independently of message text.
Never trust a caller-supplied name as authentication in a public application.

## Failure semantics

`queued → sending → accepted | rejected | unknown`

An exception during a send leaves `unknown`: the destination might already
have accepted it. There is no automatic retry of unknown outcomes. A crashed
worker's `sending` rows may be reconciled only after the old worker is known
dead. Recovery is explicit, not run by each new worker on startup.

Approval replay is idempotent within this database. This is **not** a claim of
exactly-once delivery across a network. Transport acknowledgment is not human
read receipt. The sample has no public reconciliation API or delivery SLA.

## Deliberate limits

This is teaching software, not a production service or a clone of a personal
assistant. It has no HTTP server, Telegram adapter, real model provider,
encryption, retention/deletion controls, monetary ledger, monitoring daemon,
backups or multi-tenant deployment. Do not put real personal data in it.

The SQLite connection is used synchronously, one per caller. Transactions
serialize transitions; this is not a distributed worker lease design.
The LangGraph example uses `InMemorySaver`: graph state does not survive process
exit. The outbox can be durable when using a file, but that does not make the
in-memory graph durable. Plain model answers remain untrusted; a real UI must
escape them. A real provider adapter needs schema validation, deadlines and a
durable budget in addition to the step limit shown here.

## Exercises

1. Edit after preview and try to confirm the old version.
2. Simulate a transport that accepts, then raises a timeout.
3. Replace the scripted planner with an adapter, keeping the executor's
   authority unchanged. Do not add paid calls without an explicit budget.
4. Add a durable graph checkpointer and test a process restart.
5. Design an authenticated channel adapter and test its principal boundary.

MIT licensed. Contributions should use synthetic data and include failure-case
tests. Never submit tokens, personal conversations or deployment configuration.
