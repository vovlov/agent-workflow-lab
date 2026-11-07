"""Offline teaching implementation: proposals are data, authority stays in code.

The caller supplies an authenticated principal. This is a library API, not an
authentication service. No network, model credentials, or production data.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol


class Denied(ValueError):
    pass


@dataclass(frozen=True)
class Preview:
    case_id: str
    revision: int
    text: str
    digest: str
    expires_at: float


class Inbox:
    """Single-process demo. Transactions serialize transitions across connections."""

    def __init__(self, path: str = ':memory:', clock: Callable = time.time):
        self.clock = clock
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY, principal TEXT NOT NULL, text TEXT NOT NULL,
            revision INTEGER NOT NULL, status TEXT NOT NULL,
            digest TEXT, expires REAL);
          CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL,
            text TEXT NOT NULL, status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, case_id TEXT, kind TEXT, at REAL);
        ''')

    def close(self):
        self.db.close()

    def _event(self, case_id: str, kind: str):
        # Event metadata deliberately excludes message bodies and identities.
        self.db.execute('INSERT INTO events(case_id,kind,at) VALUES(?,?,?)',
                        (case_id, kind, self.clock()))

    def _owned(self, principal: str, case_id: str):
        row = self.db.execute('SELECT * FROM cases WHERE id=? AND principal=?',
                              (case_id, principal)).fetchone()
        if row is None:
            raise Denied('Case unavailable')
        return row

    def _transaction(self, action):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = action()
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @staticmethod
    def _text(text: str):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise Denied('Expected 1–4000 characters')

    def create(self, principal: str, text: str) -> str:
        self._text(text)
        if not principal:
            raise Denied('Authenticated principal required')
        case_id = uuid.uuid4().hex
        def action():
            self.db.execute('INSERT INTO cases VALUES(?,?,?,1,?,NULL,NULL)',
                            (case_id, principal, text, 'draft'))
            self._event(case_id, 'created')
        self._transaction(action)
        return case_id

    def edit(self, principal: str, case_id: str, text: str):
        self._text(text)
        def action():
            row = self._owned(principal, case_id)
            if row['status'] != 'draft':
                raise Denied('Already confirmed')
            self.db.execute('UPDATE cases SET text=?,revision=revision+1,digest=NULL,expires=NULL WHERE id=?', (text, case_id))
            self._event(case_id, 'edited')
        self._transaction(action)

    def preview(self, principal: str, case_id: str) -> Preview:
        def action():
            row = self._owned(principal, case_id)
            if row['status'] != 'draft':
                raise Denied('Already confirmed')
            expires = self.clock() + 900
            digest = hashlib.sha256(json.dumps(
                [case_id, row['revision'], row['text'], expires]
            ).encode()).hexdigest()
            self.db.execute('UPDATE cases SET digest=?,expires=? WHERE id=?',
                            (digest, expires, case_id))
            return Preview(case_id, row['revision'], row['text'], digest, expires)
        return self._transaction(action)

    def approve(self, principal: str, preview: Preview) -> str:
        def action():
            row = self._owned(principal, preview.case_id)
            if (row['revision'] != preview.revision or row['digest'] != preview.digest
                    or row['text'] != preview.text):
                raise Denied('Preview changed')
            existing = self.db.execute('SELECT id FROM outbox WHERE case_id=?',
                                       (row['id'],)).fetchone()
            if existing:
                return existing['id']  # Replayed approval creates no second action.
            if row['status'] != 'draft' or row['expires'] <= self.clock():
                raise Denied('Preview expired or unavailable')
            job = uuid.uuid4().hex
            self.db.execute('INSERT INTO outbox VALUES(?,?,?,?)',
                            (job, row['id'], row['text'], 'queued'))
            self.db.execute("UPDATE cases SET status='queued' WHERE id=?", (row['id'],))
            self._event(row['id'], 'approved')
            return job
        return self._transaction(action)

    def dispatch(self, send: Callable[[str, str], str], case_id: str | None = None) -> str | None:
        def claim():
            row = self.db.execute("SELECT * FROM outbox WHERE status='queued' AND (? IS NULL OR case_id=?) ORDER BY rowid LIMIT 1", (case_id, case_id)).fetchone()
            if row:
                self.db.execute("UPDATE outbox SET status='sending' WHERE id=?", (row['id'],))
            return row
        row = self._transaction(claim)
        if row is None:
            return None
        try:
            result = send(row['id'], row['text'])
            status = result if result in ('accepted', 'rejected') else 'unknown'
        except Exception:
            status = 'unknown'  # The remote side may have completed the operation.
        def finish():
            self.db.execute('UPDATE outbox SET status=? WHERE id=?', (status, row['id']))
            self.db.execute('UPDATE cases SET status=? WHERE id=?', (status, row['case_id']))
            self._event(row['case_id'], status)
        self._transaction(finish)
        return status

    def recover_after_worker_exit(self):
        """Only after the previous worker is known dead; not concurrent lease recovery."""
        def action():
            rows = self.db.execute("SELECT case_id FROM outbox WHERE status='sending'").fetchall()
            for row in rows:
                self.db.execute("UPDATE cases SET status='unknown' WHERE id=?", (row['case_id'],))
                self._event(row['case_id'], 'unknown')
            self.db.execute("UPDATE outbox SET status='unknown' WHERE status='sending'")
        self._transaction(action)

    def status(self, principal: str, case_id: str) -> str:
        return self._owned(principal, case_id)['status']


class Planner(Protocol):
    def __call__(self, observations: list[str]) -> dict: ...


def discuss(question: str, planner: Planner | None = None, max_steps: int = 3) -> str:
    """Bounded agent loop. Only a read-only FAQ tool; cannot approve or send.

    Real adapters also need hard provider deadlines, input limits and a durable
    cost budget. This offline example intentionally implements none of those.
    """
    fallback = 'I can prepare a message for your review. Nothing is sent yet.'
    if planner is None:
        return fallback
    observations = [question[:4000]]
    facts = {'contact': 'Prepare a message, review its full text, then confirm.',
             'privacy': 'Use synthetic information in this teaching demo.'}
    for _ in range(max(0, min(max_steps, 8))):
        try:
            proposal = planner(observations.copy())
            if not isinstance(proposal, dict):
                return fallback
            if proposal.get('action') == 'faq' and proposal.get('key') in facts:
                observations.append(facts[proposal['key']])
            elif proposal.get('action') == 'answer' and isinstance(proposal.get('text'), str):
                return proposal['text'][:1000]  # Untrusted text; UI must escape it.
            else:
                return fallback
        except Exception:
            return fallback
    return fallback


def main():
    box = Inbox()
    try:
        case = box.create('demo-visitor', 'Hello! I would like to discuss a project.')
        preview = box.preview('demo-visitor', case)
        print('PREVIEW:', preview.text)
        # This script simulates an explicit visitor approval, not an LLM decision.
        box.approve('demo-visitor', preview)
        print('DELIVERY:', box.dispatch(lambda job, body: 'accepted'))
        print('AGENT:', discuss('How do I contact someone?'))
    finally:
        box.close()


if __name__ == '__main__':
    main()
