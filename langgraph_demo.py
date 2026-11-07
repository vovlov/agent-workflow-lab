"""Optional graph orchestration, entirely offline. Python 3.10+."""
from typing import TypedDict
from dataclasses import asdict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from agent_lab import Inbox, Preview


class State(TypedDict):
    case_id: str
    preview: dict
    approved: bool
    delivery: str


def build(box: Inbox, principal: str):
    def prepare(state: State):
        return {'preview': asdict(box.preview(principal, state['case_id']))}

    def review(state: State):
        # No external side effect before interrupt; this node runs again on resume.
        decision = interrupt(state['preview'])
        if decision.get('approve') is not True:
            return {'approved': False}
        # Check the preview actually shown, not a new one generated on resume.
        shown = Preview(**state['preview'])
        if shown.case_id != state['case_id']:
            raise ValueError('Case mismatch')
        box.approve(principal, shown)
        return {'approved': True}

    def deliver(state: State):
        if not state['approved']:
            return {'delivery': 'cancelled'}
        return {'delivery': box.dispatch(lambda *_: 'accepted', state['case_id']) or 'no pending job'}

    graph = StateGraph(State)
    graph.add_node('prepare', prepare)
    graph.add_node('review', review)
    graph.add_node('deliver', deliver)
    graph.add_edge(START, 'prepare')
    graph.add_edge('prepare', 'review')
    graph.add_edge('review', 'deliver')
    graph.add_edge('deliver', END)
    return graph.compile(checkpointer=InMemorySaver())


def main():
    box = Inbox()
    try:
        case = box.create('demo-visitor', 'Hello from the graph')
        graph = build(box, 'demo-visitor')
        config = {'configurable': {'thread_id': 'synthetic-thread'}}
        paused = graph.invoke({'case_id': case, 'preview': {}, 'approved': False, 'delivery': ''}, config)
        shown = paused['__interrupt__'][0].value
        print('PAUSED:', shown['text'])
        result = graph.invoke(Command(resume={'approve': True}), config)
        assert result['delivery'] == 'accepted', result
        print('DELIVERY:', result['delivery'])
    finally:
        box.close()


if __name__ == '__main__':
    main()
