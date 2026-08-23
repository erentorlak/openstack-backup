from osbak.restore.model import PlanStep, RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner


def make_manifest() -> dict:
    return {
        "schema_version": 1,
        "project_id": "p-1",
        "instance": {
            "name": "web-01", "project_id": "p-1", "key_name": "admin",
            "config_drive": True, "availability_zone": "nova:az1",
            "metadata": {"env": "prod"}, "tags": ["web"],
        },
        "flavor": {"name": "m1.small", "vcpus": 1, "ram": 2048, "disk": 10,
                    "ephemeral": 0, "swap": 0, "extra_specs": {}},
        "block_device_mapping": [
            {"volume_id": "v-root", "size": 10, "volume_type": "ssd", "boot_index": 0},
            {"volume_id": "v-data", "size": 50, "volume_type": "ssd", "boot_index": 1},
        ],
        "network": {"ports": [
            {"id": "port-1", "network_id": "net-1", "mac_address": "aa:bb:cc:dd:ee:ff",
             "fixed_ips": [{"subnet_id": "sub-1", "ip_address": "10.0.0.5"}],
             "security_group_ids": ["sg-old-1"], "allowed_address_pairs": []},
        ]},
        "security_groups": [
            {"id": "sg-old-1", "name": "web", "description": "web rules", "rules": [
                {"direction": "ingress", "protocol": "tcp", "ether_type": "IPv4",
                 "port_range_min": 80, "port_range_max": 80,
                 "remote_ip_prefix": "0.0.0.0/0", "remote_group_id": None},
            ]},
        ],
        "server_groups": [],
    }


def test_build_shells_come_before_rules() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    actions = [s.action for s in plan.steps]
    assert actions.index("ensure_security_group_shell") < actions.index("add_security_group_rules")


def test_build_server_is_last() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    assert plan.steps[-1].action == "create_server"
    assert plan.steps[-1].key == "server"


def test_build_volume_keys_ordered_by_boot() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    server = plan.steps[-1].payload
    assert server["volume_keys"] == ["vol:v-root", "vol:v-data"]


def test_build_port_fixed_ip_respects_keep_ip() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=True)
    plan = RestorePlanner(make_manifest(), opts, 1).build()
    port = next(s for s in plan.steps if s.action == "create_port")
    assert port.payload["fixed_ip"] == "10.0.0.5"
    assert port.payload["security_group_names"] == ["web"]

    opts_no = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=False)
    plan_no = RestorePlanner(make_manifest(), opts_no, 1).build()
    port_no = next(s for s in plan_no.steps if s.action == "create_port")
    assert port_no.payload["fixed_ip"] is None


def test_build_instance_name_override() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, instance_name="web-restore")
    plan = RestorePlanner(make_manifest(), opts, 1).build()
    assert plan.steps[-1].payload["name"] == "web-restore"


def test_build_rejects_unplanned_strategy() -> None:
    try:
        RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.LIVE), 1).build()
        assert False
    except RestorePlanError as exc:
        assert "desteklenmiyor" in str(exc)


def test_resource_delta() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    assert plan.resource_delta == {"volumes": 2, "ports": 1, "security_groups": 1,
                                   "flavors": 1, "servers": 1}
