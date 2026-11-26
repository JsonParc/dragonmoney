"""Weighted vote counting. Pure functions."""
from __future__ import annotations

from collections import defaultdict

from stockbot.debate.schema import Direction, Opinion, PersuasionRecord, ResolvedAction, Team


def _w(weights: dict[str, float], seat: str) -> float:
    return weights.get(seat, 1.0)


def _shares(opinions: list[Opinion], weights: dict[str, float]) -> dict[Direction, float]:
    tot: dict[Direction, float] = defaultdict(float)
    for o in opinions:
        if o.valid:
            tot[o.direction] += _w(weights, o.seat_id)
    total = sum(tot.values())
    return {d: (tot[d] / total if total else 0.0) for d in Direction}


def team_position(opinions: list[Opinion], weights: dict[str, float], team: Team) -> Direction | None:
    tot: dict[Direction, float] = defaultdict(float)
    for o in opinions:
        if o.valid and o.team == team:
            tot[o.direction] += _w(weights, o.seat_id)
    if not tot:
        return None
    best = max(tot.values())
    winners = [d for d, v in tot.items() if v == best]
    return winners[0] if len(winners) == 1 else None


def direction_vote(opinions: list[Opinion], weights: dict[str, float]) -> tuple[Direction | None, dict[Direction, float]]:
    shares = _shares(opinions, weights)
    for d, s in shares.items():
        if s > 0.5:
            return d, shares
    return None, shares


def _weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    pairs = sorted((v, w) for v, w in pairs if v is not None)
    if not pairs:
        return None
    half = sum(w for _, w in pairs) / 2
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def resolve_details(opinions: list[Opinion], weights: dict[str, float], direction: Direction) -> ResolvedAction:
    side = [o for o in opinions if o.valid and o.direction == direction]
    by_action: dict = defaultdict(float)
    for o in side:
        by_action[o.action] += _w(weights, o.seat_id)
    action = max(by_action, key=lambda a: by_action[a])
    chosen = [o for o in side if o.action == action]

    def med(field: str) -> float | None:
        return _weighted_median([(getattr(o, field), _w(weights, o.seat_id)) for o in chosen
                                 if getattr(o, field) is not None])

    switch_votes: dict[str, float] = defaultdict(float)
    for o in chosen:
        if o.switch_to:
            switch_votes[o.switch_to.upper()] += _w(weights, o.seat_id)
    return ResolvedAction(action=action, size_pct=med("size_pct"), target_price=med("target_price"),
                          rebuy_price=med("rebuy_price"),
                          switch_to=max(switch_votes, key=lambda k: switch_votes[k]) if switch_votes else None)


def detect_persuasion(round0: list[Opinion], final: list[Opinion], final_direction: Direction | None) -> PersuasionRecord:
    if final_direction is None:
        return PersuasionRecord()
    start = {o.seat_id: o for o in round0 if o.valid}
    end = {o.seat_id: o for o in final if o.valid}
    switched = sorted(s for s, o in end.items()
                      if o.direction == final_direction and s in start and start[s].direction != final_direction)
    if not switched:
        return PersuasionRecord()
    neutral_w: dict[str, float] = {}
    pos = {t: team_position(round0, neutral_w, t) for t in Team}
    owners = [t for t in Team if pos[t] == final_direction and all(pos[u] != final_direction for u in Team if u != t)]
    return PersuasionRecord(persuading_team=owners[0] if owners else None, switched_seats=switched)
