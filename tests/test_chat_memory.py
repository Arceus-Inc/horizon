"""Theme D, slice D2: the CEO's layered memory + its wiring into the chat.

Deterministic — recall ranking is a pure function of text/importance/recency, and the chat's memory
read/write is exercised with a scripted substrate.
"""

from __future__ import annotations

import json

import pytest

from horizon import Horizon
from horizon.chat import CeoChat, CeoMemory
from horizon.generation import ProposalStore
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import (
    FakeGoalStore,
    FakeIntakePort,
    FakeOutcomeFeed,
    FakeSubstrate,
    SequenceSubstrate,
)


def _mem(tmp_path, *, clock=None):
    return CeoMemory(tmp_path / "mem.json", now=clock or (lambda: "2026-07-10T00:00:00+00:00"))


def _horizon(tmp_path):
    return Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(),
        decisions=DecisionStore(tmp_path / "d.json"), strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"), default_assignee="moe",
    )


def _step(*, tool="", args=None, answer="", cites=None):
    return json.dumps(
        {"thought": "…", "tool": tool, "args_json": json.dumps(args) if args else "",
         "answer_text": answer, "citations": cites or []}
    )


# --- memory store ------------------------------------------------------------


def test_memory_write_get_and_layer_filter(tmp_path):
    mem = _mem(tmp_path)
    e = mem.write("directives", "Always prioritise the deliverable over analysis polish.", importance=0.9)
    assert e.id.startswith("mem_")
    assert mem.get(e.id).text.startswith("Always prioritise")
    mem.write("org-facts", "We build an AI coding assistant.")
    assert {x.layer for x in mem.all()} == {"directives", "org-facts"}
    assert len(mem.all(layer="directives")) == 1


def test_memory_rejects_unknown_layer(tmp_path):
    with pytest.raises(ValueError, match="unknown memory layer"):
        _mem(tmp_path).write("nonsense", "x")


def test_recall_ranks_by_keyword_overlap(tmp_path):
    mem = _mem(tmp_path)
    mem.write("org-facts", "Our target segment is mid-market platform teams.")
    mem.write("org-facts", "The office coffee machine is broken.")
    hits = mem.recall("what segment do we target", limit=1)
    assert len(hits) == 1
    assert "mid-market" in hits[0].text


def test_recall_skips_superseded(tmp_path):
    mem = _mem(tmp_path)
    old = mem.write("directives", "focus on enterprise accounts")
    mem.write("directives", "focus on mid-market accounts")
    mem.supersede(old.id)
    hits = mem.recall("what accounts should we focus on", limit=5)
    assert all(h.id != old.id for h in hits)
    assert any("mid-market" in h.text for h in hits)


def test_recall_can_scope_to_layers(tmp_path):
    mem = _mem(tmp_path)
    mem.write("org-facts", "pricing is usage-based")
    mem.write("conversation", "we chatted about pricing yesterday")
    hits = mem.recall("pricing", layers=("org-facts",), limit=5)
    assert all(h.layer == "org-facts" for h in hits)


# --- chat <-> memory wiring --------------------------------------------------


def test_chat_writes_the_exchange_to_conversation_memory(tmp_path):
    mem = _mem(tmp_path)
    chat = CeoChat(
        reasoner=SequenceSubstrate([_step(answer="We target mid-market.", cites=["dec_1"])]),
        horizon=_horizon(tmp_path), memory=mem,
    )
    chat.ask("who do we target?")
    convo = mem.all(layer="conversation")
    assert len(convo) == 1
    assert "who do we target?" in convo[0].text and "mid-market" in convo[0].text


def test_chat_injects_recalled_memory_into_the_prompt(tmp_path):
    mem = _mem(tmp_path)
    mem.write("directives", "Never greenlight a decision without at least three evidence sources.",
              importance=0.9)
    reasoner = SequenceSubstrate([_step(answer="Understood.", cites=[])])
    chat = CeoChat(reasoner=reasoner, horizon=_horizon(tmp_path), memory=mem)
    chat.ask("what's our rule on evidence before greenlighting?")
    assert "three evidence sources" in reasoner.calls[0]  # recalled memory was in the prompt


def test_chat_exposes_a_recall_memory_tool(tmp_path):
    mem = _mem(tmp_path)
    mem.write("decision-log", "Chose mid-market on 2026-07-10 because inbound signal was strongest.",
              importance=0.8)
    reasoner = SequenceSubstrate(
        [_step(tool="recall_memory", args={"query": "why mid-market"}),
         _step(answer="Because inbound was strongest.", cites=[])]
    )
    chat = CeoChat(reasoner=reasoner, horizon=_horizon(tmp_path), memory=mem)
    ans = chat.ask("remind me why we chose mid-market")
    assert "mid-market" in ans.steps[0].observation
    assert ans.steps[0].tool == "recall_memory"


def test_chat_without_memory_has_no_recall_tool(tmp_path):
    chat = CeoChat(reasoner=FakeSubstrate(_step(answer="hi")), horizon=_horizon(tmp_path))
    assert "recall_memory" not in chat._tools
