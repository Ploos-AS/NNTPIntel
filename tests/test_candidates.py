from nntpintel.candidates import (
    classify_observation,
    due_candidates,
    list_candidate_qualifications,
    qualify_candidates,
)
from nntpintel.discovery import import_seeds
from nntpintel.probe import ProbeObservation
from nntpintel.storage import Storage


def _observation(*, code=200, error=None):
    return ProbeObservation(
        observed_at="2026-09-09T01:00:00+00:00",
        host="news.example.test",
        port=119,
        transport="tcp",
        greeting_code=code,
        greeting=None if code is None else f"{code} test greeting",
        capabilities=["VERSION 2"] if error is None else [],
        error=error,
    )


def test_classify_observation():
    assert classify_observation(_observation())[0] == "reachable"
    assert classify_observation(_observation(code=480, error="NNTPProtocolError: unexpected greeting code 480"))[0] == "auth_required"
    assert classify_observation(_observation(code=None, error="NNTPProtocolError: invalid NNTP status line"))[0] == "not_nntp"
    assert classify_observation(_observation(code=None, error="ConnectionRefusedError: refused"))[0] == "dead"
    assert classify_observation(_observation(code=None, error="SSLError: certificate verify failed"))[0] == "tls_error"


def test_qualification_keeps_candidate_disabled(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")

    candidates = due_candidates(storage)
    assert len(candidates) == 1
    assert candidates[0]["host"] == "news.example.test"

    def fake_probe(*args, **kwargs):
        return _observation()

    results = qualify_candidates(storage, probe_func=fake_probe)
    assert results[0]["classification"] == "reachable"

    with storage.connect() as conn:
        enabled = conn.execute(
            "SELECT enabled FROM servers WHERE host = 'news.example.test'"
        ).fetchone()["enabled"]
    assert enabled == 0

    history = list_candidate_qualifications(storage)
    assert len(history) == 1
    assert history[0]["classification"] == "reachable"


def test_qualification_history_rotates_candidates(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(
        storage,
        ["one.example.test", "two.example.test"],
        source="test-source",
    )

    def fake_probe(host, **kwargs):
        return ProbeObservation(
            observed_at="2026-09-09T01:00:00+00:00",
            host=host,
            port=119,
            transport="tcp",
            greeting_code=200,
            greeting="200 ready",
        )

    first = qualify_candidates(storage, limit=1, probe_func=fake_probe)
    second = qualify_candidates(storage, limit=1, probe_func=fake_probe)
    assert first[0]["host"] != second[0]["host"]
