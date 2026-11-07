import importlib.util
import unittest
from agent_lab import Inbox, Denied


@unittest.skipUnless(importlib.util.find_spec('langgraph'), 'Optional LangGraph not installed')
class GraphAcceptance(unittest.TestCase):
    def setUp(self):
        from langgraph_demo import build
        self.box = Inbox()
        self.case = self.box.create('alice', 'Synthetic graph request')
        self.graph = build(self.box, 'alice')
        self.config = {'configurable': {'thread_id': 'test'}}
        self.paused = self.graph.invoke({'case_id': self.case, 'preview': {},
                                         'approved': False, 'delivery': ''}, self.config)

    def tearDown(self):
        self.box.close()

    def test_interrupt_is_before_delivery(self):
        self.assertTrue(self.paused['__interrupt__'])
        self.assertEqual(0, self.box.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])

    def test_resume_approval_delivers(self):
        from langgraph.types import Command
        result = self.graph.invoke(Command(resume={'approve': True}), self.config)
        self.assertEqual('accepted', result['delivery'])

    def test_decline_does_not_queue(self):
        from langgraph.types import Command
        result = self.graph.invoke(Command(resume={'approve': False}), self.config)
        self.assertEqual('cancelled', result['delivery'])
        self.assertEqual(0, self.box.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])

    def test_delivery_is_bound_to_this_case(self):
        from langgraph.types import Command
        other = self.box.create('bob', 'Another synthetic case')
        self.box.approve('bob', self.box.preview('bob', other))
        self.graph.invoke(Command(resume={'approve': True}), self.config)
        self.assertEqual('queued', self.box.status('bob', other))
        self.assertEqual('accepted', self.box.status('alice', self.case))

    def test_edited_snapshot_cannot_be_approved_after_resume(self):
        from langgraph.types import Command
        self.box.edit('alice', self.case, 'Changed after preview')
        with self.assertRaises(Denied):
            self.graph.invoke(Command(resume={'approve': True}), self.config)
