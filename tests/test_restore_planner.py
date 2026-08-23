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


def make_manifest_with_group_ref() -> dict:
    manifest = make_manifest()
    manifest["security_groups"] = [
        {"id": "sg-old-1", "name": "web", "description": "web rules", "rules": [
            {"direction": "ingress", "protocol": "tcp", "ether_type": "IPv4",
             "port_range_min": 80, "port_range_max": 80,
             "remote_ip_prefix": "0.0.0.0/0", "remote_group_id": None},
        ]},
        {"id": "sg-old-2", "name": "db", "description": "db rules", "rules": [
            {"direction": "ingress", "protocol": "tcp", "ether_type": "IPv4",
             "port_range_min": 3306, "port_range_max": 3306,
             "remote_ip_prefix": None, "remote_group_id": "sg-old-1"},
        ]},
    ]
    return manifest


def test_build_translates_remote_group_id_to_name() -> None:
    plan = RestorePlanner(make_manifest_with_group_ref(),
                          RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    db_step = next(s for s in plan.steps
                   if s.action == "add_security_group_rules" and s.key == "sg_rules:db")
    rule = db_step.payload["rules"][0]
    assert rule["remote_group_name"] == "web"
    assert "remote_group_id" not in rule


def test_build_rejects_unknown_remote_group_id() -> None:
    manifest = make_manifest_with_group_ref()
    manifest["security_groups"][1]["rules"][0]["remote_group_id"] = "sg-unknown"
    try:
        RestorePlanner(manifest, RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
        assert False
    except RestorePlanError as exc:
        assert "bilinmeyen uzak grup" in str(exc)


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


def test_build_boot_device_first_with_real_boot_indices() -> None:
    manifest = make_manifest()
    manifest["block_device_mapping"] = [
        {"volume_id": "v-root", "size": 10, "volume_type": "ssd", "boot_index": 0},
        {"volume_id": "v-data", "size": 50, "volume_type": "ssd", "boot_index": -1},
    ]
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD)
    plan = RestorePlanner(manifest, opts, 1).build()
    server = plan.steps[-1].payload
    assert server["volume_keys"] == ["vol:v-root", "vol:v-data"]
    vol_steps = [s for s in plan.steps if s.action == "create_volume"]
    assert [s.key for s in vol_steps] == ["vol:v-root", "vol:v-data"]


def test_plan_rejects_unknown_port_security_group() -> None:
    manifest = make_manifest()
    manifest["network"]["ports"][0]["security_group_ids"] = ["sg-unknown"]
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD)
    try:
        RestorePlanner(manifest, opts, 1).build()
        assert False, "unknown port SG sessizce dusmemeli"
    except RestorePlanError as exc:
        assert "sg-unknown" in str(exc)


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
