import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

import pytest

from nntpintel.api import make_server
from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.storage import Storage


def _record_pair(storage, first, second, index, delay_seconds):
    message_id = f"<topology-{index}@example.test>"
    create_campaign(storage, message_id, [first, second], stop_after_visible=2)
    base = datetime(2026, 9, 9, index, 0, tzinfo=UTC)
    record_presence(
        storage,
        message_id,
        first,
        observed_at=base.isoformat(),
        present=True,
        response_code=223,
    )
    record_presence(
        storage,
        message_id,
        second,
        observed_at=(base + timedelta(seconds=delay_seconds)).isoformat(),
        present=True,
        response_code=223,
    )


def _topology_storage(tmp_path):
    storage = Storage(tmp_path / "topology.db")
    early = storage.ensure_endpoint("early.example.test")
    late = storage.ensure_endpoint("late.example.test")
    for index, delay in enumerate((30, 40, 50), start=1):
        _record_pair(storage, early, late, index, delay)
    return storage


def test_topology_infers_repeated_precedence_without_claiming_peering(tmp_path):
    storage = _topology_storage(tmp_path)

    topology = inferred_propagation_topology(storage)
    assert topology["authoritative_topology"] is False
    assert "do not prove direct NNTP peering" in topology["disclaimer"]
    assert topology["edge_count"] == 1
    edge = topology["edges"][0]
    assert edge["source_host"] == "early.example.test"
    assert edge["target_host"] == "late.example.test"
    assert edge["relation"] == "observed_precedence"
    assert edge["inference"] is True
    assert edge["sample_count"] == 3
    assert edge["forward_count"] == 3
    assert edge["reverse_count"] == 0
    assert edge["confidence"] == 1.0
    assert edge["median_lead_seconds"] == 40.0


def test_topology_suppresses_weak_or_undersampled_direction(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    left = storage.ensure_endpoint("left.example.test")
    right = storage.ensure_endpoint("right.example.test")

    _record_pair(storage, left, right, 1, 30)
    _record_pair(storage, right, left, 2, 30)
    topology = inferred_propagation_topology(storage, min_samples=2, min_confidence=0.67)
    assert topology["edge_count"] == 0

    sparse = Storage(tmp_path / "sparse.db")
    first = sparse.ensure_endpoint("first.example.test")
    second = sparse.ensure_endpoint("second.example.test")
    _record_pair(sparse, first, second, 1, 10)
    _record_pair(sparse, first, second, 2, 20)
    assert inferred_propagation_topology(sparse)["edge_count"] == 0


def test_topology_collapses_multiple_endpoints_to_server_first_seen(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    a_plain = storage.ensure_endpoint("a.example.test", port=119)
    a_tls = storage.ensure_endpoint("a.example.test", port=563, transport="tls")
    b = storage.ensure_endpoint("b.example.test", port=119)

    for index in range(1, 4):
        message_id = f"<multi-{index}@example.test>"
        create_campaign(storage, message_id, [a_plain, a_tls, b], stop_after_visible=3)
        base = datetime(2026, 9, 9, index, 0, tzinfo=UTC)
        record_presence(storage, message_id, a_tls, observed_at=base.isoformat(), present=True, response_code=223)
        record_presence(storage, message_id, a_plain, observed_at=(base + timedelta(seconds=5)).isoformat(), present=True, response_code=223)
        record_presence(storage, message_id, b, observed_at=(base + timedelta(seconds=20)).isoformat(), present=True, response_code=223)

    topology = inferred_propagation_topology(storage)
    assert topology["node_count"] == 2
    assert topology["edge_count"] == 1
    assert topology["edges"][0]["median_lead_seconds"] == 20.0


def test_topology_validates_thresholds(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with pytest.raises(ValueError, match="min_samples"):
        inferred_propagation_topology(storage, min_samples=0)
    with pytest.raises(ValueError, match="min_confidence"):
        inferred_propagation_topology(storage, min_confidence=0.4)


def test_topology_api_and_web(tmp_path):
    storage = _topology_storage(tmp_path)
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology", timeout=2) as response:
            payload = json.load(response)
        assert payload["authoritative_topology"] is False
        assert payload["edge_count"] == 1
        assert payload["edges"][0]["source_host"] == "early.example.test"
        assert payload["edges"][0]["target_host"] == "late.example.test"

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Inferred propagation topology" in html
        assert "Inference only" in html
        assert "early.example.test" in html
        assert "late.example.test" in html
        assert "Observed precedence edges" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
