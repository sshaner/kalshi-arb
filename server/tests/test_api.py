import pytest
from fastapi.testclient import TestClient

from arb import config
from arb.api import create_app
from arb.db import Db


class FakeScanner:
    def __init__(self):
        import asyncio
        self.discovery_now = asyncio.Event()
        self.status = {"discovery": {}, "prices": {}, "settlement": {}}


class FakePusher:
    enabled = False
    last_error = None

    async def send(self, *a, **k):
        return 0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "secret-token")
    db = Db(str(tmp_path / "t.db"))
    db.x("INSERT INTO markets (venue, market_id, event_title, title, open) VALUES ('kalshi', 'K1', 'E', 'A', 1)")
    db.x("INSERT INTO markets (venue, market_id, event_title, title, open) VALUES ('pmus', 'P1', 'E', 'A', 1)")
    db.add_candidates([("K1", "P1", 91.0, 0.98, False)])
    return TestClient(create_app(db, FakeScanner(), FakePusher())), db


AUTH = {"Authorization": "Bearer secret-token"}


def test_requires_token(client):
    c, _ = client
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/status", headers=AUTH).status_code == 200


def test_approve_flow(client):
    c, db = client
    cands = c.get("/api/candidates", headers=AUTH).json()
    assert len(cands) == 1 and cands[0]["kalshi"]["market_id"] == "K1"
    pair = c.post(f"/api/candidates/{cands[0]['id']}/approve", json={"inverted": True, "notes": "n"}, headers=AUTH).json()
    assert pair["inverted"] is True and pair["notes"] == "n"
    assert c.get("/api/candidates", headers=AUTH).json() == []
    assert len(c.get("/api/pairs", headers=AUTH).json()) == 1
    c.patch(f"/api/pairs/{pair['id']}", json={"paused": True}, headers=AUTH)
    assert db.active_pairs() == []


def test_settings_roundtrip(client):
    c, _ = client
    s = c.put("/api/settings", json={"min_edge_cents": 2.5}, headers=AUTH).json()
    assert s["min_edge_cents"] == 2.5
    assert c.put("/api/settings", json={"bogus": 1}, headers=AUTH).status_code == 400


def test_device_register(client):
    c, db = client
    assert c.post("/api/devices", json={"token": "ABCDEF0123"}, headers=AUTH).status_code == 200
    assert db.one("SELECT token FROM devices")["token"] == "abcdef0123"
    assert c.post("/api/devices", json={"token": "not hex!"}, headers=AUTH).status_code == 400


def test_bulk_approve(client):
    c, db = client
    db.add_candidates([("K2", "P2", 99.0, 1.0, True), ("K3", "P3", 85.0, 1.0, False)])
    assert c.post("/api/candidates/approve-bulk?min_score=95", headers=AUTH).json() == {"approved": 1}
    pair = db.one("SELECT * FROM pairs WHERE kalshi_id = 'K2'")
    assert pair["inverted"] == 1
    assert db.one("SELECT status FROM candidates WHERE kalshi_id = 'K3'")["status"] == "pending"
