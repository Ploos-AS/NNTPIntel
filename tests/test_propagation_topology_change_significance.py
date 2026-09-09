from nntpintel.propagation_topology_change_significance import classify_change_significance


def test_significance_marks_critical_risk_crossing():
    result = classify_change_significance(
        [
            {
                "code": "risk",
                "before": 68.0,
                "after": 82.0,
                "delta": 14.0,
                "summary": "Risk 68.0→82.0",
            },
            {
                "code": "risk_level",
                "before": "high",
                "after": "critical",
                "summary": "Risk level high→critical",
            },
        ]
    )
    assert result["level"] == "critical"
    assert result["rank"] == 3
    assert "risk level entered critical" in result["reasons"]


def test_significance_marks_evidence_collapse_important():
    result = classify_change_significance(
        [
            {
                "code": "evidence_level",
                "before": "high",
                "after": "low",
                "summary": "Evidence high→low",
            }
        ]
    )
    assert result["level"] == "important"
    assert result["operator_confirmed"] is False


def test_significance_marks_confidence_drop_important():
    result = classify_change_significance(
        [
            {
                "code": "edge_confidence",
                "before": 0.91,
                "after": 0.68,
                "delta": -0.23,
                "summary": "Edge confidence 0.91→0.68",
            }
        ]
    )
    assert result["level"] == "important"
    assert "edge confidence dropped by at least 0.20" in result["reasons"]


def test_significance_keeps_sample_growth_informational():
    result = classify_change_significance(
        [
            {
                "code": "presence_observations",
                "before": 3,
                "after": 5,
                "delta": 2,
                "summary": "+2 presence observations (3→5)",
            }
        ]
    )
    assert result["level"] == "informational"
    assert result["reasons"] == ["+2 presence observations (3→5)"]
