from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from app.cloud.local.provider import LocalCloudProvider
from app.core.clock import ManualClock
from app.core.config import Settings
from app.db import Base
from app.main import create_app
from fastapi.testclient import TestClient

PASSWORDS = {
    "admin": "admin-test-pass-123",
    "sre": "sre-test-pass-123",
    "developer": "dev-test-pass-123",
    "viewer": "viewer-test-pass-123",
}


def make_settings(**overrides) -> Settings:
    base = dict(
        database_url=os.environ.get("TEST_DATABASE_URL", "sqlite://"),
        jwt_secret="test-secret-" + "x" * 40,
        environment="test",
        run_control_loop=False,
        simulation_seed=11,
        tick_seconds=2.0,
        seed_demo_users=True,
        seed_admin_password=PASSWORDS["admin"],
        seed_sre_password=PASSWORDS["sre"],
        seed_developer_password=PASSWORDS["developer"],
        seed_viewer_password=PASSWORDS["viewer"],
        login_rate_limit_per_minute=1000,
        bcrypt_rounds=4,
        ai_rate_limit_per_minute=1000,
        llm_provider="none",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class Harness:
    def __init__(self, client: TestClient, clock: ManualClock):
        self.client = client
        self.clock = clock
        self.app = client.app
        self.cp = client.app.state.cp
        self._tokens: dict[str, str] = {}

    def token(self, user: str) -> str:
        if user not in self._tokens:
            r = self.client.post("/api/auth/login", json={"username": user, "password": PASSWORDS[user]})
            assert r.status_code == 200, r.text
            self._tokens[user] = r.json()["access_token"]
        return self._tokens[user]

    def h(self, user: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user)}"}

    def get(self, path: str, user: str = "viewer", **kw):
        return self.client.get(path, headers=self.h(user), **kw)

    def post(self, path: str, json=None, user: str = "sre", **kw):
        return self.client.post(path, json=json, headers=self.h(user), **kw)

    def put(self, path: str, json=None, user: str = "admin", **kw):
        return self.client.put(path, json=json, headers=self.h(user), **kw)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.clock.advance(self.cp.settings.tick_seconds)
            self.cp.step()

    def tick_until(self, predicate: Callable[[], bool], max_ticks: int = 60) -> int:
        for i in range(max_ticks):
            if predicate():
                return i
            self.tick()
        raise AssertionError(f"condition not met within {max_ticks} ticks")


@pytest.fixture
def harness_factory() -> Iterator[Callable[..., Harness]]:
    clients: list[TestClient] = []

    def make(**overrides) -> Harness:
        settings = make_settings(**overrides)
        clock = ManualClock()
        provider = LocalCloudProvider(
            clock, seed=settings.simulation_seed, tick_seconds=settings.tick_seconds
        )
        app = create_app(settings, clock=clock, provider=provider, create_schema=True)
        if not settings.database_url.startswith("sqlite"):
            Base.metadata.drop_all(app.state.engine)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return Harness(client, clock)

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def harness(harness_factory) -> Harness:
    h = harness_factory()
    h.tick(60)  # establish baselines (2 simulated minutes)
    return h
