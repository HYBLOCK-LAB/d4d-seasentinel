from fastapi.testclient import TestClient

from mda.api.app import app

client = TestClient(app)


def test_health_db_true() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["db"] is True


def test_meta_shape() -> None:
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["regions"], list)
    assert "start" in body["window"]
    assert "end" in body["window"]
    assert isinstance(body["counts"], dict)


def test_ontology_tables_includes_vessel() -> None:
    response = client.get("/api/ontology/tables")
    assert response.status_code == 200
    tables = [row["table"] for row in response.json()]
    assert "vessel" in tables


def test_ontology_vessel_limit() -> None:
    response = client.get("/api/ontology/vessel", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) <= 5


def test_ontology_unknown_table_404() -> None:
    response = client.get("/api/ontology/nope")
    assert response.status_code == 404


def test_threats_sorted_by_score() -> None:
    response = client.get("/api/threats")
    assert response.status_code == 200
    scores = [t["score"] or 0 for t in response.json()["threats"]]
    assert scores == sorted(scores, reverse=True)


def test_timeline_day_buckets() -> None:
    response = client.get("/api/timeline", params={"bucket": "day"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["buckets"], list)
