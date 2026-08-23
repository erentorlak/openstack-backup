from osbak.discovery.gateway import parse_host


def test_full_host() -> None:
    h = parse_host("node1@rbd-1#pool-a")
    assert h.host == "node1"
    assert h.driver == "rbd-1"
    assert h.pool == "pool-a"


def test_no_pool() -> None:
    h = parse_host("node1@ontap_fc")
    assert h.host == "node1"
    assert h.driver == "ontap_fc"
    assert h.pool is None


def test_plain_hostname() -> None:
    h = parse_host("somehost")
    assert h.host == "somehost"
    assert h.driver is None
    assert h.pool is None


def test_netapp_flexvol_sample() -> None:
    h = parse_host("netapp-fc@ontap_fc#flexvol_openstack_01")
    assert h.driver == "ontap_fc"
    assert h.pool == "flexvol_openstack_01"
