import json

from osbak.discovery.gateway import (
    FlavorInfo,
    PortInfo,
    ProjectInfo,
    SecurityGroupInfo,
    SecurityGroupRule,
    ServerGroupInfo,
    ServerInfo,
)
from osbak.manifest.builder import ManifestBuilder
from tests.fake_gateway import FakeGateway


def _fake_gateway() -> FakeGateway:
    server = ServerInfo(
        id="i-1", name="web-1", project_id="pid-1", status="ACTIVE",
        flavor_id="f-1", key_name="kp-1", availability_zone="nova-1",
        metadata={"env": "prod"}, tags=("t1",),
        addresses={"private": [{"addr": "10.0.0.5"}]},
    )
    return FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="proj-a")],
        servers={"pid-1": [server]},
        volumes={},
        ports={"pid-1": [PortInfo(id="p-1", network_id="n-1",
                                  mac_address="aa:bb:cc:dd:ee:ff",
                                  device_id="i-1",
                                  security_group_ids=("sg-1",))]},
        security_groups={"pid-1": [
            SecurityGroupInfo(id="sg-1", name="default", description="",
                              project_id="pid-1", rules=(
                                  SecurityGroupRule(id="r-1", direction="ingress",
                                                    protocol="tcp", port_range_min=22,
                                                    port_range_max=22),)),
        ]},
        server_groups={"pid-1": [ServerGroupInfo(id="g-1", name="web",
                                                 project_id="pid-1",
                                                 policies=("affinity",),
                                                 member_ids=("i-1",))]},
        flavors={"f-1": FlavorInfo(id="f-1", name="m1.small", vcpus=1, ram=1024,
                                   disk=20, ephemeral=0, swap=0, is_public=True,
                                   extra_specs={"hw:numa_nodes": "1"})},
    )


def test_manifest_structure() -> None:
    gateway = _fake_gateway()
    server = gateway.list_servers("pid-1")[0]
    manifest = ManifestBuilder(gateway).build("pid-1", server)
    assert manifest["schema_version"] == 1
    assert manifest["project_id"] == "pid-1"
    assert manifest["instance"]["name"] == "web-1"
    assert manifest["instance"]["metadata"] == {"env": "prod"}
    assert manifest["flavor"]["extra_specs"]["hw:numa_nodes"] == "1"
    assert manifest["flavor"]["ram"] == 1024
    assert manifest["block_device_mapping"] == []
    assert manifest["network"]["ports"][0]["id"] == "p-1"
    assert manifest["network"]["ports"][0]["security_group_ids"] == ["sg-1"]
    assert manifest["security_groups"][0]["rules"][0]["protocol"] == "tcp"
    assert manifest["server_groups"][0]["policies"] == ["affinity"]


def test_manifest_is_json_serializable() -> None:
    gateway = _fake_gateway()
    server = gateway.list_servers("pid-1")[0]
    json.dumps(ManifestBuilder(gateway).build("pid-1", server))  # no exception


def test_manifest_flavor_none_when_missing() -> None:
    gateway = _fake_gateway()
    gateway._flavors.clear()
    server = gateway.list_servers("pid-1")[0]
    assert ManifestBuilder(gateway).build("pid-1", server)["flavor"] is None


def test_manifest_top_level_keys_pinned() -> None:
    gateway = _fake_gateway()
    server = gateway.list_servers("pid-1")[0]
    manifest = ManifestBuilder(gateway).build("pid-1", server)
    assert set(manifest.keys()) == {
        "schema_version", "captured_at", "project_id", "instance", "flavor",
        "block_device_mapping", "network", "security_groups", "server_groups",
    }
