from __future__ import annotations

from gaudi.scorecard import (
    QuerySnap,
    ReadSnap,
    ScorecardInput,
    SessionSnap,
    compute_ab,
    compute_scorecard,
    fmt_tokens,
    repeat_read_cost,
    weighted,
)


def test_weighted_and_repeat() -> None:
    assert weighted(100, 1, 5, 0.1) == 100 * (1 + 4 * 0.1)
    assert weighted(50, 5, 5, 0.1) == 50
    assert repeat_read_cost(80, 0.1) == 8.0


def test_scorecard_net_and_gross() -> None:
    data = ScorecardInput(
        sessions=(SessionSnap("s1", "cursor", "on", 3),),
        queries=(
            QuerySnap("s1", "focus", 10, 100, 1, (("a.py", 40), ("b.py", 60))),
        ),
        reads=(ReadSnap("s1", "a.py", 40, 2, True),),
    )
    report = compute_scorecard(
        data,
        cache_read_multiplier=0.1,
        instruction_tokens_by_harness={"cursor": 20},
        session_start_tokens=10,
    )
    assert report.read_files == 1
    assert report.first_read_tokens == 40
    assert report.avoided_files == 1
    assert report.gross[0].cmd == "focus"
    assert report.gross[0].saved == 90
    assert report.gross[0].pct == 0.9
    # emitted 10 at t=1 T=3, instruction 20, session start 10, avoided b.py 60 at t=1
    emitted_w = weighted(10, 1, 3, 0.1)
    inst_w = weighted(20, 1, 3, 0.1)
    start_w = weighted(10, 1, 3, 0.1)
    avoided_w = weighted(60, 1, 3, 0.1)
    assert report.debit == emitted_w + inst_w + start_w
    assert report.credit == avoided_w
    assert report.net == avoided_w - report.debit
    assert "cursor" in report.harnesses


def test_instruction_only_for_session_harness() -> None:
    data = ScorecardInput(
        sessions=(SessionSnap("s1", "claude", "on", 1),),
        queries=(),
        reads=(),
    )
    report = compute_scorecard(
        data,
        cache_read_multiplier=0.1,
        instruction_tokens_by_harness={"cursor": 999, "claude": 12},
        session_start_tokens=0,
    )
    assert report.instruction_tokens == 12
    assert report.debit == 12


def test_ab_refuses_below_min_sessions() -> None:
    sessions = [
        SessionSnap(f"on-{i}", "cursor", "on", 2) for i in range(3)
    ] + [
        SessionSnap(f"off-{i}", "cursor", "off", 4) for i in range(3)
    ]
    data = ScorecardInput(sessions=tuple(sessions))
    report = compute_ab(data, min_sessions=10)
    row = report.harnesses[0]
    assert row.refused is True
    assert row.verdict is None
    assert row.n_on == 3
    assert row.n_off == 3


def test_ab_verdict_within_harness() -> None:
    on = [SessionSnap(f"on-{i}", "cursor", "on", 2) for i in range(10)]
    off = [SessionSnap(f"off-{i}", "cursor", "off", 5) for i in range(10)]
    reads = tuple(
        [ReadSnap(s.conversation_id, "a.py", 10, 1, True) for s in on]
        + [ReadSnap(s.conversation_id, "a.py", 50, 1, True) for s in off]
    )
    data = ScorecardInput(sessions=tuple(on + off), reads=reads)
    report = compute_ab(data, min_sessions=10)
    row = report.harnesses[0]
    assert row.refused is False
    assert row.verdict == "on"
    assert row.read_on == 10
    assert row.read_off == 50


def test_ab_does_not_mix_harnesses_when_one_is_short() -> None:
    cursor_on = [SessionSnap(f"c-on-{i}", "cursor", "on", 1) for i in range(10)]
    cursor_off = [SessionSnap(f"c-off-{i}", "cursor", "off", 1) for i in range(10)]
    copilot_on = [SessionSnap("p-on-0", "copilot", "on", 1)]
    copilot_off = [SessionSnap("p-off-0", "copilot", "off", 1)]
    data = ScorecardInput(sessions=tuple(cursor_on + cursor_off + copilot_on + copilot_off))
    report = compute_ab(data, min_sessions=10)
    by_name = {row.harness: row for row in report.harnesses}
    assert by_name["cursor"].refused is False
    assert by_name["copilot"].refused is True
    assert report.overall is not None
    assert report.overall.refused is True


def test_fmt_tokens() -> None:
    assert fmt_tokens(12) == "12"
    assert fmt_tokens(7100) == "7.1k"
    assert fmt_tokens(412_000) == "412k"
