from app import checks


def T(channel="sms", assistant=("hi",), tools=(), meta=None, tid=1):
    ev = []
    for a in assistant:
        ev.append({"role": "user", "content": "q"})
        ev.append({"role": "assistant", "content": a})
    for name, args in tools:
        ev.append({"role": "tool_call", "content": "", "tool_name": name, "tool_args": args})
    return {"id": tid, "channel": channel, "meta": meta or {}, "events": ev}


def test_markdown_preset_and_scope():
    rule = {"type": "markdown", "scope": {"facet": "channel", "values": ["sms"]}}
    assert checks.run_rule(rule, T(assistant=["**Booked!** see you"]))[0] is True
    assert checks.run_rule(rule, T(assistant=["Here:\n- unit 1\n- unit 2"]))[0] is True
    assert checks.run_rule(rule, T(assistant=["[Apply](https://x.com)"]))[0] is True
    assert checks.run_rule(rule, T(assistant=["Booked! Unit C-104, $1,385/mo. Text back to change."]))[0] is False
    assert checks.run_rule(rule, T(assistant=["call check_availability or schedule_tour"]))[0] is False
    # out of scope: chat may use markdown
    assert checks.run_rule(rule, T(channel="chat", assistant=["**ok**"]))[0] is False


def test_regex_present_absent():
    present = {"type": "regex", "pattern": "virtual tour", "mode": "present", "flags": "i"}
    assert checks.run_rule(present, T(assistant=["Your Virtual Tour is booked"]))[0]
    assert not checks.run_rule(present, T(assistant=["in person"]))[0]
    absent = {"type": "regex", "pattern": r"confirmation", "mode": "absent"}
    assert checks.run_rule(absent, T(assistant=["booked"]))[0]
    assert not checks.run_rule(absent, T(assistant=["confirmation TR-1"]))[0]


def test_tool_rules():
    t = T(tools=[("schedule_tour", {"property": "A", "datetime": ""}), ("schedule_tour", {"property": "B", "datetime": "x"})])
    assert checks.run_rule({"type": "tool_called", "tool": "handoff_to_human", "expect": "called"}, t)[0]
    assert not checks.run_rule({"type": "tool_called", "tool": "handoff_to_human", "expect": "not_called"}, t)[0]
    assert checks.run_rule({"type": "tool_count_max", "tool": "schedule_tour", "max": 1}, t)[0]
    assert not checks.run_rule({"type": "tool_count_max", "tool": "schedule_tour", "max": 2}, t)[0]
    failed, why = checks.run_rule({"type": "tool_args_required", "tool": "schedule_tour", "args": ["datetime"]}, t)
    assert failed and "datetime" in why


def test_length_and_json_schema():
    assert checks.run_rule({"type": "length", "max": 10}, T(assistant=["x" * 11]))[0]
    assert not checks.run_rule({"type": "length", "max": 10, "min": 1}, T(assistant=["ok"]))[0]
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    assert not checks.run_rule({"type": "json_schema", "schema": schema}, T(assistant=['{"a": 1}']))[0]
    assert checks.run_rule({"type": "json_schema", "schema": schema}, T(assistant=['{"a": "x"}']))[0]
    assert checks.run_rule({"type": "json_schema", "schema": schema}, T(assistant=["not json"]))[0]


def test_run_rules_any_failure_fails():
    rules = [{"type": "markdown"}, {"type": "length", "max": 1000}]
    assert checks.run_rules(rules, T(assistant=["**x**"]))[0]
    assert not checks.run_rules(rules, T(assistant=["fine"]))[0]


def test_python_escape_hatch_with_timeout_and_errors():
    code = "def check(trace):\n    names = [e.get('tool_name') for e in trace['events']]\n    return not ('schedule_tour' in names and 'lookup_tours' in names)\n"
    traces = [T(tid=1, tools=[("lookup_tours", {}), ("schedule_tour", {})]), T(tid=2, tools=[("schedule_tour", {})])]
    res = checks.run_definition({"kind": "python", "code": code}, traces)
    assert res[1][0] is True and res[2][0] is False
    slow = checks.run_python("def check(trace):\n    while True: pass\n", traces, timeout=2)
    assert all(v[0] and "timed out" in v[1] for v in slow.values())
    boom = checks.run_python("def check(trace):\n    return 1/0\n", traces)
    assert all(v[0] and "ZeroDivisionError" in v[1] for v in boom.values())
    bad = checks.run_python("def check(trace) return 1", traces)
    assert all(v[0] and "could not load" in v[1] for v in bad.values())


def test_validate_definition():
    assert checks.validate_definition({"kind": "rules", "rules": []})
    assert checks.validate_definition({"kind": "rules", "rules": [{"type": "regex", "pattern": "("}]})
    assert checks.validate_definition({"kind": "python", "code": "x = 1"})
    assert checks.validate_definition({"kind": "rules", "rules": [{"type": "markdown"}]}) == []
