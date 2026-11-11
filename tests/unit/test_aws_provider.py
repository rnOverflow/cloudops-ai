"""AWSProvider against moto's ECS mock (no real AWS calls)."""

import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

from app.cloud.aws import AWSProvider  # noqa: E402
from app.cloud.base import ProviderError  # noqa: E402
from app.core.clock import ManualClock  # noqa: E402


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        session = boto3.Session(region_name="us-east-1")
        ecs = session.client("ecs")
        ecs.create_cluster(clusterName="cloudops")
        for rev in (1, 2):
            ecs.register_task_definition(
                family="payment",
                containerDefinitions=[{"name": "app", "image": f"repo/payment:v{rev}", "memory": 512}],
            )
        ecs.create_service(
            cluster="cloudops", serviceName="payment-svc", taskDefinition="payment:2", desiredCount=2
        )
        yield (
            AWSProvider(
                ManualClock(), "cloudops", {"payment-service": "payment-svc"}, "us-east-1", session=session
            ),
            ecs,
        )


def test_scale_and_state(aws):
    provider, ecs = aws
    assert provider.deployment_state("payment-service")["replicas"] == 2
    assert provider.scale_deployment("payment-service", 4).ok
    assert (
        ecs.describe_services(cluster="cloudops", services=["payment-svc"])["services"][0]["desiredCount"]
        == 4
    )


def test_rollback_moves_to_previous_revision(aws):
    provider, ecs = aws
    res = provider.rollback_deployment("payment-service")
    assert res.ok, res.message
    assert ecs.describe_services(cluster="cloudops", services=["payment-svc"])["services"][0][
        "taskDefinition"
    ].endswith("payment:1")


def test_restart_service_and_unsupported_actions(aws):
    provider, _ = aws
    assert provider.restart_service("payment-service").ok
    assert not provider.clear_failed_job("payment-service", "job-1").ok
    assert not provider.deploy("payment-service", "v9.9.9", defective=True).ok
    with pytest.raises(ProviderError):
        provider.inject_fault("high_cpu")


def test_collect_reports_gaps_instead_of_inventing(aws):
    provider, _ = aws
    snap = provider.collect()
    m = snap.metrics["payment-service"]
    assert m["replicas"] == 2.0
    assert m["cpu_percent"] == 0.0  # no CloudWatch datapoints in the mock -> zero, not fabricated
    assert provider.cluster_status()["simulated"] is False
