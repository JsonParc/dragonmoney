from stockbot.debate.schema import Action, Opinion, Team

C, N = Team.CHART, Team.NEWS
CHART = ["c1", "c2", "c3"]
NEWS = ["n1", "n2", "n3"]
W1 = {s: 1.0 for s in CHART + NEWS}


def op(seat, team, action, round=0, valid=True, **kw):
    return Opinion(seat_id=seat, team=team, round=round, valid=valid, action=Action(action),
                   confidence=kw.pop("confidence", 0.7), rationale=kw.pop("rationale", "r"), **kw)
