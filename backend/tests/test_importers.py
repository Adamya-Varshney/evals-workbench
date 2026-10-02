import json

from app.importers.normalize import (
    SkipRecord, apply_redaction, guess_mapping, normalize_record, parse_file,
)

import pytest

OPENAI = {
    "id": "t1", "channel": "SMS", "user_feedback": "thumbs_down", "latency_ms": 1200,
    "messages": [
        {"role": "system", "content": "You are a bot."},
        {"role": "user", "content": "2br under 1500?"},
        {"role": "assistant", "content": "Checking.", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "check_availability", "arguments": "{\"bedrooms\": 2}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{\"units\": []}"},
        {"role": "assistant", "content": "**None** right now."},
    ],
}

ANTHROPIC = {
    "trace_id": "a1",
    "metadata": {"channel": "chat", "property": "Commons"},
    "system": "Be helpful.",
    "messages": [
        {"role": "user", "content": "book a tour"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Sure."},
            {"type": "tool_use", "id": "tu1", "name": "schedule_tour", "input": {"tour_type": "in_person"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": [{"type": "text", "text": "ok"}]}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Booked your virtual tour."}]},
    ],
}


def test_openai_style():
    recs, fmt, errs = parse_file(json.dumps(OPENAI) + "\n", "x.jsonl")
    assert fmt == "jsonl" and not errs
    m = guess_mapping(recs)
    assert m["mode"] == "messages" and m["messages"] == "messages" and m["id"] == "id" and m["channel"] == "channel"
    t = normalize_record(recs[0], m)
    roles = [e["role"] for e in t.events]
    assert roles == ["user", "assistant", "tool_call", "tool_result", "assistant"]
    assert t.system_prompt == "You are a bot."
    assert t.channel == "sms"
    assert t.events[2]["tool_name"] == "check_availability" and t.events[2]["tool_args"] == {"bedrooms": 2}
    assert t.events[3]["tool_name"] == "check_availability"
    assert t.meta["user_feedback"] == "thumbs_down" and t.meta["latency_ms"] == 1200
    assert t.external_id == "t1" and t.n_tool_calls == 1


def test_anthropic_blocks_and_nested_metadata():
    recs, fmt, _ = parse_file(json.dumps([ANTHROPIC]), "x.json")
    assert fmt == "json"
    m = guess_mapping(recs)
    assert m["id"] == "trace_id" and m["channel"] == "metadata.channel" and m["system"] == "system"
    t = normalize_record(recs[0], m)
    assert [e["role"] for e in t.events] == ["user", "assistant", "tool_call", "tool_result", "assistant"]
    assert t.events[2]["tool_args"] == {"tour_type": "in_person"}
    assert t.events[3]["tool_result"] == "ok" and t.events[3]["tool_name"] == "schedule_tour"
    assert t.system_prompt == "Be helpful."
    assert t.channel == "chat" and t.meta["property"] == "Commons"


def test_csv_input_output():
    csv_text = "id,input,output,channel,property\nr1,hi is the pool open,Yes 8am-10pm,sms,Heights\nr2,,,sms,Heights\n"
    recs, fmt, _ = parse_file(csv_text, "x.csv")
    assert fmt == "csv" and len(recs) == 2
    m = guess_mapping(recs)
    assert m["mode"] == "input_output" and m["input"] == "input" and m["output"] == "output"
    t = normalize_record(recs[0], m)
    assert [e["role"] for e in t.events] == ["user", "assistant"]
    assert t.meta["property"] == "Heights"
    with pytest.raises(SkipRecord):
        normalize_record(recs[1], m)


def test_csv_with_json_message_column():
    msgs = json.dumps([{"role": "user", "content": "hey"}, {"role": "assistant", "content": "hello!"}])
    import csv, io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "conversation", "env"])
    w.writerow(["z9", msgs, "prod"])
    recs, fmt, _ = parse_file(buf.getvalue(), "export.csv")
    m = guess_mapping(recs)
    assert m["mode"] == "messages" and m["messages"] == "conversation" and m["id"] == "run_id"
    t = normalize_record(recs[0], m)
    assert [e["content"] for e in t.events] == ["hey", "hello!"]
    assert t.meta == {"env": "prod", "channel": "chat"}


def test_langsmith_like_nested_paths():
    rec = {"id": "ls1", "inputs": {"messages": [{"type": "human", "content": "hi"}]},
           "outputs": {"messages": [{"type": "ai", "content": "hello"}]}, "extra": {"metadata_env": "prod"}}
    m = {"mode": "input_output", "input": "inputs.messages", "output": "outputs.messages", "id": "id"}
    t = normalize_record(rec, m)
    assert [(e["role"], e["content"]) for e in t.events] == [("user", "hi"), ("assistant", "hello")]


def test_bad_lines_are_reported_not_fatal():
    text = json.dumps(OPENAI) + "\n{not json\n[1,2]\n" + json.dumps({**OPENAI, "id": "t2"}) + "\n"
    recs, fmt, errs = parse_file(text, "x.jsonl")
    assert len(recs) == 2 and len(errs) == 2
    assert errs[0]["line"] == 2


def test_missing_messages_skips_with_reason():
    m = guess_mapping([OPENAI])
    with pytest.raises(SkipRecord, match="no message array"):
        normalize_record({"id": "x", "messages": []}, m)


def test_redaction():
    rec = {**OPENAI, "messages": [{"role": "user", "content": "call me 512-555-0199 or mail a.b@x.io, acct 99-123"},
                                  {"role": "assistant", "content": "ok"}]}
    t = normalize_record(rec, guess_mapping([rec]))
    t = apply_redaction(t, {"emails": True, "phones": True, "custom": [r"\d{2}-\d{3}"]})
    assert t.events[0]["content"] == "call me [PHONE] or mail [EMAIL], acct [REDACTED]"
    assert "512-555-0199" not in json.dumps(t.raw)
