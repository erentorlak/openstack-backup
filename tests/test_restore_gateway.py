from tests.fake_restore_gateway import FakeRestoreGateway


def test_fake_gateway_idempotent_security_group() -> None:
    gw = FakeRestoreGateway()
    a = gw.ensure_security_group("web", "", "pid-1")
    b = gw.ensure_security_group("web", "", "pid-1")
    assert a == b
    assert len(gw.created["security_groups"]) == 1


def test_fake_gateway_creates_distinct_ids() -> None:
    gw = FakeRestoreGateway()
    v1 = gw.create_volume("v1", 10, "ssd", None, None)
    p1 = gw.create_port("n-1", "aa:bb:cc:dd:ee:ff", "10.0.0.5", [], [], "pid-1")
    assert v1 != p1
    assert v1 == "vol-1" and p1 == "port-2"
