from datetime import timedelta

from news_helpers import dt, item

from stockbot.data.news import NewsStore
from stockbot.data.verify import ClusterRow, NewsVerifier, cluster, digest_line, independent_sources, verify

TIERS = {"sec.gov": 0, "cnbc.com": 1, "marketwatch.com": 1, "smallblog.net": 3, "yahoo.com": 2}


def test_single_low_tier_is_unconfirmed():
    g = [item(domain="smallblog.net", title="Apple CEO to resign tomorrow")]
    assert verify(g, TIERS) == "unconfirmed"


def test_two_independent_reputable_confirm():
    g = [item(domain="cnbc.com", title="Oil jumps 10% after strike on refinery"),
         item(domain="marketwatch.com", title="Oil prices jump 10% after refinery strike")]
    assert verify(g, TIERS) == "confirmed" and independent_sources(g) == 2


def test_two_blogs_do_not_confirm():
    g = [item(domain="smallblog.net", title="X"), item(domain="otherblog.io", title="X story")]
    assert verify(g, TIERS) == "unconfirmed"


def test_syndicated_copies_count_once():
    g = [item(domain="yahoo.com", wire="AP", title="X"), item(domain="cnbc.com", wire="AP", title="X")]
    assert independent_sources(g) == 1


def test_primary_source_confirms_alone():
    assert verify([item(domain="sec.gov", title="8-K: CEO departure")], TIERS) == "confirmed"


def test_denial_contradicts():
    g = [item(domain="smallblog.net", title="Nvidia to be banned from China"),
         item(domain="cnbc.com", title="Nvidia denies report of China ban")]
    assert verify(g, TIERS) == "contradicted"


def test_cluster_groups_same_event_only():
    items = [item(title="Oil jumps 10% after refinery strike", published_at=dt(2024, 9, 1, 1)),
             item(title="Oil prices jump 10% after strike on refinery", published_at=dt(2024, 9, 1, 3)),
             item(title="Apple unveils new iPhone", published_at=dt(2024, 9, 1, 2))]
    assert sorted(len(g) for g in cluster(items)) == [1, 2]


def test_cluster_respects_window():
    items = [item(title="Oil jumps 10% after refinery strike", published_at=dt(2024, 9, 1)),
             item(title="Oil jumps 10% after refinery strike again", published_at=dt(2024, 9, 3))]
    assert len(cluster(items, window_hours=24)) == 2


def test_denial_joins_rumor_cluster():
    items = [item(title="Nvidia to be banned from China", tickers=["NVDA"]),
             item(title="Nvidia denies report of China ban", tickers=["NVDA"], domain="marketwatch.com")]
    assert len(cluster(items)) == 1


def test_digest_line():
    row = ClusterRow(id=1, headline="Oil surges", tickers=[], tags=[], verification="confirmed",
                     independent_sources=5, best_tier=1, severity=4, first_seen=dt(2024, 1, 1), last_seen=dt(2024, 1, 1))
    assert digest_line(row).startswith("[확인됨·출처 5곳]")


def test_verifier_upgrades_cluster(session_factory):
    store = NewsStore(session_factory)
    v = NewsVerifier(session_factory, TIERS)
    store.add([item(title="Strike hits Nvidia supplier factory", domain="smallblog.net", tickers=["NVDA"])])
    first = v.update(dt(2024, 3, 1, 13))
    assert [c.verification for c in first] == ["unconfirmed"]
    store.add([item(title="Strike hits Nvidia supplier factory, company says", domain="cnbc.com", tickers=["NVDA"]),
               item(title="Nvidia supplier factory hit by strike", domain="marketwatch.com", tickers=["NVDA"])])
    changed = v.update(dt(2024, 3, 1, 14))
    assert len(changed) == 1 and changed[0].verification == "confirmed" and changed[0].id == first[0].id
    assert v.update(dt(2024, 3, 1, 14) + timedelta(minutes=10)) == []
