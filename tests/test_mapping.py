import pytest

from osbak.discovery.gateway import (
    flavor_from_dict,
    port_from_dict,
    project_from_dict,
    security_group_from_dict,
    server_from_dict,
    server_group_from_dict,
    volume_from_dict,
)


def test_project_from_dict() -> None:
    p = project_from_dict({"id": "pid-1", "name": "proj-a", "domain_id": "default"})
    assert p.id == "pid-1"
    assert p.name == "proj-a"
    assert p.domain_id == "default"


def test_volume_from_dict() -> None:
    v = volume_from_dict(
        {
            "id": "v-1",
            "name": "vol",
            "size": 10,
            "volume_type": "ssd",
            "status": "in-use",
            "bootable": "true",
            "host": "node1@rbd-1#pool-a",
            "project_id": "pid-1",
            "attachments": [
                {
                    "server_id": "i-1",
                    "device": "/dev/vda",
                    "attachment_id": "a-1",
                    "volume_id": "v-1",
                    "id": "v-1",
                }
            ],
        }
    )
    assert v.bootable is True
    assert v.host == "node1@rbd-1#pool-a"
    assert v.attachments[0].server_id == "i-1"
    assert v.attachments[0].device == "/dev/vda"
    assert v.attachments[0].volume_id == "v-1"


def test_server_from_dict_uses_tenant_id_and_flavor() -> None:
    s = server_from_dict(
        {
            "id": "i-1",
            "name": "web-1",
            "status": "ACTIVE",
            "project_id": "pid-1",
            "flavor": {"id": "f-1"},
            "metadata": {"x": "y"},
            "tags": ["t1"],
        }
    )
    assert s.project_id == "pid-1"
    assert s.flavor_id == "f-1"
    assert s.tags == ("t1",)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("false", False),
        ("true", True),
    ],
)
def test_server_from_dict_config_drive_normalized(raw, expected) -> None:
    s = server_from_dict(
        {
            "id": "i-1",
            "name": "web-1",
            "status": "ACTIVE",
            "project_id": "pid-1",
            "flavor": {"id": "f-1"},
            "config_drive": raw,
        }
    )
    assert s.config_drive is expected


def test_port_from_dict() -> None:
    p = port_from_dict(
        {
            "id": "p-1",
            "network_id": "n-1",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "device_id": "i-1",
            "fixed_ips": [{"subnet_id": "s-1", "ip_address": "10.0.0.5"}],
            "security_group_ids": ["sg-1"],
        }
    )
    assert p.mac_address == "aa:bb:cc:dd:ee:ff"
    assert p.security_group_ids == ("sg-1",)


def test_flavor_from_dict() -> None:
    f = flavor_from_dict(
        {
            "id": "f-1",
            "name": "m1.small",
            "vcpus": 1,
            "ram": 1024,
            "disk": 20,
            "ephemeral": 0,
            "swap": 0,
        }
    )
    assert f.vcpus == 1
    assert f.ram == 1024


def test_security_group_from_dict() -> None:
    sg = security_group_from_dict(
        {
            "id": "sg-1",
            "name": "default",
            "security_group_rules": [
                {
                    "id": "r-1",
                    "direction": "ingress",
                    "protocol": "tcp",
                    "port_range_min": 22,
                    "port_range_max": 22,
                }
            ],
        }
    )
    assert sg.rules[0].protocol == "tcp"


def test_server_group_from_dict() -> None:
    g = server_group_from_dict(
        {"id": "g-1", "name": "grp", "policies": ["affinity"], "member_ids": ["i-1"]}
    )
    assert g.policies == ("affinity",)
    assert g.member_ids == ("i-1",)
