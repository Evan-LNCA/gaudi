from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class SessionSnap:
    conversation_id: str
    harness: str
    arm: str
    turns: int


@dataclass(frozen=True)
class QuerySnap:
    conversation_id: str | None
    cmd: str
    emitted_tokens: int
    baseline_tokens: int
    turn: int | None
    oriented: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ReadSnap:
    conversation_id: str
    path: str
    tokens: int
    turn: int | None
    first_read: bool


@dataclass(frozen=True)
class CompactionSnap:
    conversation_id: str
    context_tokens: int | None
    context_window_size: int | None
    message_count: int | None


@dataclass(frozen=True)
class ScorecardInput:
    sessions: tuple[SessionSnap, ...] = ()
    queries: tuple[QuerySnap, ...] = ()
    reads: tuple[ReadSnap, ...] = ()
    compactions: tuple[CompactionSnap, ...] = ()


@dataclass(frozen=True)
class GrossRow:
    cmd: str
    emitted: int
    baseline: int
    saved: int
    pct: float


@dataclass(frozen=True)
class ScorecardReport:
    cache_read_multiplier: float
    session_count: int
    harnesses: tuple[str, ...]
    ledger_hooks: bool
    read_files: int
    read_tokens: int
    first_read_tokens: int
    repeat_read_tokens: int
    gaudi_calls: int
    gaudi_emitted: int
    instruction_sessions: int
    instruction_tokens: float
    compaction_sessions: int
    median_compaction_context: float | None
    avoided_files: int
    avoided_tokens: float
    credit: float
    debit: float
    net: float
    gross: tuple[GrossRow, ...] = ()


@dataclass(frozen=True)
class ArmMedians:
    harness: str
    n_on: int
    n_off: int
    read_on: float | None
    read_off: float | None
    emitted_on: float | None
    emitted_off: float | None
    turns_on: float | None
    turns_off: float | None
    verdict: str | None
    refused: bool


@dataclass(frozen=True)
class AbReport:
    min_sessions: int
    harnesses: tuple[ArmMedians, ...]
    overall: ArmMedians | None


def weighted(tokens: int, t: int, total_turns: int, cache_read_multiplier: float) -> float:
    turn = max(t, 1)
    span = max(total_turns, turn)
    return tokens * (1.0 + (span - turn) * cache_read_multiplier)


def repeat_read_cost(tokens: int, cache_read_multiplier: float) -> float:
    return tokens * cache_read_multiplier


def compute_scorecard(
    data: ScorecardInput,
    *,
    cache_read_multiplier: float,
    instruction_tokens_by_harness: dict[str, int],
    session_start_tokens: int,
) -> ScorecardReport:
    sessions = {s.conversation_id: s for s in data.sessions}
    turns_of = {cid: max(s.turns, 1) for cid, s in sessions.items()}
    read_tokens = 0
    first_read_tokens = 0
    repeat_read_tokens = 0
    read_files = 0
    for row in data.reads:
        read_files += 1
        read_tokens += row.tokens
        if row.first_read:
            first_read_tokens += row.tokens
        else:
            repeat_read_tokens += row.tokens

    gaudi_emitted = sum(q.emitted_tokens for q in data.queries)
    debit = 0.0
    for query in data.queries:
        total = turns_of.get(query.conversation_id or "", 1)
        turn = query.turn if query.turn is not None else 1
        debit += weighted(query.emitted_tokens, turn, total, cache_read_multiplier)

    instruction_total = 0.0
    instruction_sessions = 0
    for session in data.sessions:
        inst = instruction_tokens_by_harness.get(session.harness, 0)
        start = session_start_tokens
        total = max(session.turns, 1)
        if inst:
            instruction_sessions += 1
            instruction_total += weighted(inst, 1, total, cache_read_multiplier)
        debit += weighted(inst, 1, total, cache_read_multiplier)
        debit += weighted(start, 1, total, cache_read_multiplier)

    read_paths: dict[str, set[str]] = {}
    for row in data.reads:
        read_paths.setdefault(row.conversation_id, set()).add(_norm_path(row.path))

    avoided_files = 0
    avoided = 0.0
    seen_avoided: set[tuple[str, str]] = set()
    for query in data.queries:
        cid = query.conversation_id
        if not cid:
            continue
        total = turns_of.get(cid, 1)
        turn = query.turn if query.turn is not None else 1
        already = read_paths.get(cid, set())
        for path, source_tokens in query.oriented:
            key = (cid, _norm_path(path))
            if _norm_path(path) in already or key in seen_avoided:
                continue
            seen_avoided.add(key)
            avoided_files += 1
            avoided += weighted(source_tokens, turn, total, cache_read_multiplier)

    compaction_by_session: dict[str, list[int]] = {}
    for compact in data.compactions:
        if compact.context_tokens is not None:
            compaction_by_session.setdefault(compact.conversation_id, []).append(compact.context_tokens)
    compaction_sessions = len({compact.conversation_id for compact in data.compactions})
    med_ctx: float | None = None
    if compaction_by_session:
        med_ctx = float(median([max(vals) for vals in compaction_by_session.values()]))

    gross_cmds = ("focus", "index", "generate", "where")
    gross_rows: list[GrossRow] = []
    for cmd in gross_cmds:
        rows = [q for q in data.queries if q.cmd == cmd]
        if not rows:
            continue
        emitted = sum(q.emitted_tokens for q in rows)
        baseline = sum(q.baseline_tokens for q in rows)
        saved = max(baseline - emitted, 0)
        pct = (saved / baseline) if baseline else 0.0
        gross_rows.append(GrossRow(cmd=cmd, emitted=emitted, baseline=baseline, saved=saved, pct=pct))

    harnesses = tuple(sorted({s.harness for s in data.sessions if s.harness}))
    return ScorecardReport(
        cache_read_multiplier=cache_read_multiplier,
        session_count=len(data.sessions),
        harnesses=harnesses,
        ledger_hooks=bool(data.reads or data.sessions),
        read_files=read_files,
        read_tokens=read_tokens,
        first_read_tokens=first_read_tokens,
        repeat_read_tokens=repeat_read_tokens,
        gaudi_calls=len(data.queries),
        gaudi_emitted=gaudi_emitted,
        instruction_sessions=instruction_sessions,
        instruction_tokens=instruction_total,
        compaction_sessions=compaction_sessions,
        median_compaction_context=med_ctx,
        avoided_files=avoided_files,
        avoided_tokens=avoided,
        credit=avoided,
        debit=debit,
        net=avoided - debit,
        gross=tuple(gross_rows),
    )


def compute_ab(data: ScorecardInput, *, min_sessions: int) -> AbReport:
    by_harness: dict[str, list[SessionSnap]] = {}
    for session in data.sessions:
        by_harness.setdefault(session.harness or "unknown", []).append(session)
    harness_rows = tuple(
        _arm_medians(name, sessions, data, min_sessions)
        for name, sessions in sorted(by_harness.items())
    )
    overall = None
    if data.sessions:
        overall = _arm_medians("overall", list(data.sessions), data, min_sessions)
        mixed = len(by_harness) > 1
        if mixed:
            any_refused = any(row.refused for row in harness_rows)
            overall = ArmMedians(
                harness="overall",
                n_on=overall.n_on,
                n_off=overall.n_off,
                read_on=None if any_refused else overall.read_on,
                read_off=None if any_refused else overall.read_off,
                emitted_on=None if any_refused else overall.emitted_on,
                emitted_off=None if any_refused else overall.emitted_off,
                turns_on=None if any_refused else overall.turns_on,
                turns_off=None if any_refused else overall.turns_off,
                verdict=None if any_refused else overall.verdict,
                refused=any_refused or overall.refused,
            )
    return AbReport(min_sessions=min_sessions, harnesses=harness_rows, overall=overall)


def _arm_medians(
    harness: str,
    sessions: list[SessionSnap],
    data: ScorecardInput,
    min_sessions: int,
) -> ArmMedians:
    on = [s for s in sessions if s.arm == "on"]
    off = [s for s in sessions if s.arm == "off"]
    read_on = _median_reads(on, data)
    read_off = _median_reads(off, data)
    emitted_on = _median_emitted(on, data)
    emitted_off = _median_emitted(off, data)
    turns_on = _median_turns(on)
    turns_off = _median_turns(off)
    refused = len(on) < min_sessions or len(off) < min_sessions
    verdict = None
    if not refused and read_on is not None and read_off is not None:
        if read_on < read_off:
            verdict = "on"
        elif read_off < read_on:
            verdict = "off"
        else:
            verdict = "tie"
    return ArmMedians(
        harness=harness,
        n_on=len(on),
        n_off=len(off),
        read_on=read_on,
        read_off=read_off,
        emitted_on=emitted_on,
        emitted_off=emitted_off,
        turns_on=turns_on,
        turns_off=turns_off,
        verdict=verdict,
        refused=refused,
    )


def _median_reads(sessions: list[SessionSnap], data: ScorecardInput) -> float | None:
    if not sessions:
        return None
    ids = {s.conversation_id for s in sessions}
    totals = {cid: 0 for cid in ids}
    for row in data.reads:
        if row.conversation_id in totals:
            totals[row.conversation_id] += row.tokens
    return float(median(list(totals.values())))


def _median_emitted(sessions: list[SessionSnap], data: ScorecardInput) -> float | None:
    if not sessions:
        return None
    ids = {s.conversation_id for s in sessions}
    totals = {cid: 0 for cid in ids}
    for row in data.queries:
        if row.conversation_id in totals:
            totals[row.conversation_id] += row.emitted_tokens
    return float(median(list(totals.values())))


def _median_turns(sessions: list[SessionSnap]) -> float | None:
    if not sessions:
        return None
    return float(median([max(s.turns, 0) for s in sessions]))


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def fmt_tokens(n: float) -> str:
    value = abs(n)
    sign = "-" if n < 0 else ""
    if value >= 100_000:
        return f"{sign}{value / 1000:.0f}k"
    if value >= 1000:
        text = f"{value / 1000:.1f}k"
        if text.endswith(".0k"):
            text = f"{int(value / 1000)}k"
        return sign + text
    return f"{sign}{int(round(n))}"


def render_scorecard(report: ScorecardReport) -> str:
    harness = ",".join(report.harnesses) if report.harnesses else "none"
    hooks = "ledger hooks on" if report.ledger_hooks else "CLI estimates only"
    lines = [
        "Gaudi scorecard — chars/4 estimate, not billed tokens",
        "",
        f"MEASURED ({report.session_count} sessions, {hooks}, harness={harness})",
        (
            f"  reads         {report.read_files} files   {fmt_tokens(report.read_tokens)} tokens   "
            f"(first {fmt_tokens(report.first_read_tokens)} / repeat {fmt_tokens(report.repeat_read_tokens)})"
        ),
        f"  gaudi output  {report.gaudi_calls} calls    {fmt_tokens(report.gaudi_emitted)} tokens",
        (
            f"  instruction  {report.instruction_sessions} sessions "
            f"{fmt_tokens(report.instruction_tokens)} tokens"
        ),
    ]
    if report.compaction_sessions:
        med = (
            fmt_tokens(report.median_compaction_context)
            if report.median_compaction_context is not None
            else "n/a"
        )
        lines.append(
            f"  compactions   {report.compaction_sessions} sessions had 1+ (median context {med})"
        )
    else:
        lines.append("  compactions   0 sessions had 1+")
    lines.extend(
        [
            "",
            "ATTRIBUTED (counterfactual)",
            (
                f"  surfaced, never read   {report.avoided_files} files   "
                f"{fmt_tokens(report.avoided_tokens)} tokens"
            ),
            "",
            f"NET (cache_read_multiplier {report.cache_read_multiplier})",
            (
                f"  credit {fmt_tokens(report.credit)}  debit {fmt_tokens(report.debit)}  "
                f"net {fmt_tokens(report.net)} input tokens avoided"
            ),
            "",
            "GROSS COMPRESSION (rtk gain comparable)",
        ]
    )
    if report.gross:
        for row in report.gross:
            pct = f"{row.pct * 100:.0f}%"
            lines.append(
                f"  {row.cmd:<6} {row.emitted} emitted / {fmt_tokens(row.baseline)} baseline  {pct}"
            )
    else:
        lines.append("  (no gaudi queries recorded)")
    lines.extend(
        [
            "",
            "Not measurable locally: dollars, output tokens, turn-count effects. Run `gaudi stats --ab`.",
            "",
        ]
    )
    return "\n".join(lines)


def render_ab(report: AbReport) -> str:
    lines = [
        "Gaudi A/B — per-session medians, measured only",
        f"min_sessions per arm per harness: {report.min_sessions}",
        "",
    ]
    rows = list(report.harnesses)
    if report.overall is not None:
        rows.append(report.overall)
    for row in rows:
        lines.append(f"harness={row.harness}  on n={row.n_on}  off n={row.n_off}")
        lines.append(
            f"  read tokens     on {_fmt_opt(row.read_on)}  off {_fmt_opt(row.read_off)}"
        )
        lines.append(
            f"  gaudi emitted   on {_fmt_opt(row.emitted_on)}  off {_fmt_opt(row.emitted_off)}"
        )
        lines.append(
            f"  turns           on {_fmt_opt(row.turns_on)}  off {_fmt_opt(row.turns_off)}"
        )
        if row.refused:
            lines.append(
                "  verdict refused: need more sessions per arm before comparing this harness."
            )
        elif row.verdict == "on":
            lines.append("  verdict: on arm read fewer tokens (median).")
        elif row.verdict == "off":
            lines.append("  verdict: off arm read fewer tokens (median).")
        elif row.verdict == "tie":
            lines.append("  verdict: tie on median read tokens.")
        else:
            lines.append("  verdict refused.")
        lines.append("")
    return "\n".join(lines)


def scorecard_json(report: ScorecardReport) -> dict:
    return {
        "tier": {
            "measured": {
                "sessions": report.session_count,
                "harnesses": list(report.harnesses),
                "ledger_hooks": report.ledger_hooks,
                "reads": {
                    "files": report.read_files,
                    "tokens": report.read_tokens,
                    "first": report.first_read_tokens,
                    "repeat": report.repeat_read_tokens,
                },
                "gaudi_output": {"calls": report.gaudi_calls, "tokens": report.gaudi_emitted},
                "instruction": {
                    "sessions": report.instruction_sessions,
                    "tokens": report.instruction_tokens,
                },
                "compactions": {
                    "sessions": report.compaction_sessions,
                    "median_context": report.median_compaction_context,
                },
            },
            "attributed": {
                "surfaced_never_read": {
                    "files": report.avoided_files,
                    "tokens": report.avoided_tokens,
                }
            },
            "not_measurable": ["dollars", "output_tokens", "turn_count_effects"],
        },
        "net": {
            "cache_read_multiplier": report.cache_read_multiplier,
            "credit": report.credit,
            "debit": report.debit,
            "net": report.net,
        },
        "gross": [
            {
                "cmd": row.cmd,
                "emitted": row.emitted,
                "baseline": row.baseline,
                "saved": row.saved,
                "pct": row.pct,
            }
            for row in report.gross
        ],
    }


def ab_json(report: AbReport) -> dict:
    def _row(row: ArmMedians) -> dict:
        return {
            "harness": row.harness,
            "n_on": row.n_on,
            "n_off": row.n_off,
            "read_on": row.read_on,
            "read_off": row.read_off,
            "emitted_on": row.emitted_on,
            "emitted_off": row.emitted_off,
            "turns_on": row.turns_on,
            "turns_off": row.turns_off,
            "verdict": row.verdict,
            "refused": row.refused,
        }

    return {
        "min_sessions": report.min_sessions,
        "harnesses": [_row(row) for row in report.harnesses],
        "overall": _row(report.overall) if report.overall else None,
    }


def _fmt_opt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return fmt_tokens(value)
