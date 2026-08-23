from __future__ import annotations

from pathlib import Path

import click
import openstack

from osbak.config import Settings
from osbak.db import create_engine_by_url, init_db, make_session_factory
from osbak.discovery.gateway import SDKGateway
from osbak.discovery.service import DiscoveryService
from osbak.models import RestoreOp
from osbak.providers.base import ProviderUnavailable
from osbak.restore.model import RestoreOptions, RestoreStrategy
from osbak.restore.restore_service import RestoreService
from osbak.snapshot.service import SnapshotOptions, SnapshotService


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default="config.yaml",
    envvar="OSBAK_CONFIG",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path) -> None:
    ctx.obj = Settings.from_yaml(config_path)


def _build_connection(settings: Settings):
    keystone = settings.keystone
    return openstack.connect(
        auth_url=keystone.auth_url,
        project_name=keystone.project_name,
        project_domain_name=keystone.project_domain_name,
        user_domain_name=keystone.user_domain_name,
        username=keystone.username,
        password=keystone.password.get_secret_value(),
        region_name=keystone.region_name or None,
    )


def _apply_project_filter(gateway, project_names: list[str]) -> list[str] | None:
    if not project_names:
        return None
    seen: dict[str, str] = {}
    for name in project_names:
        if name in seen:
            raise click.ClickException(f"duplicate project name in config: {name}")
        seen[name] = ""
    by_name: dict[str, str] = {p.name: p.id for p in gateway.list_projects()}
    missing = [name for name in project_names if name not in by_name]
    if missing:
        raise click.ClickException(
            f"configured project(s) not found: {', '.join(missing)}"
        )
    return [by_name[name] for name in project_names]


@main.command("inventory-refresh")
@click.pass_context
def inventory_refresh(ctx: click.Context) -> None:
    settings: Settings = ctx.obj
    gateway = SDKGateway(_build_connection(settings))
    engine = create_engine_by_url(settings.database.url)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        project_ids = _apply_project_filter(gateway, settings.projects)
        result = DiscoveryService(gateway).refresh(session, project_ids)
        click.echo(
            f"projects={result.projects} "
            f"instances={result.instances} volumes={result.volumes}"
        )
    finally:
        session.close()
        engine.dispose()


@main.command("manifest-show")
@click.argument("instance_uuid")
@click.pass_context
def manifest_show(ctx: click.Context, instance_uuid: str) -> None:
    import json

    from osbak.manifest.builder import ManifestBuilder

    settings: Settings = ctx.obj
    gateway = SDKGateway(_build_connection(settings))
    builder = ManifestBuilder(gateway)
    for project in gateway.list_projects():
        for server in gateway.list_servers(project.id):
            if server.id == instance_uuid:
                manifest = builder.build(project.id, server)
                click.echo(json.dumps(manifest, indent=2, sort_keys=True))
                return
    raise click.ClickException(f"instance not found: {instance_uuid}")


def _provider_factory(driver: str):
    if "rbd" in driver:
        from osbak.providers.ceph import CephProvider
        return CephProvider()
    raise ProviderUnavailable(f"bilinmeyen driver: {driver}")


@main.command("snapshot-take")
@click.argument("instance_uuid")
@click.option("--consistent", is_flag=True, default=False)
@click.pass_context
def snapshot_take(ctx: click.Context, instance_uuid: str, consistent: bool) -> None:
    settings: Settings = ctx.obj
    gateway = SDKGateway(_build_connection(settings))
    engine = create_engine_by_url(settings.database.url)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        result = SnapshotService(gateway, _provider_factory).snapshot_instance(
            session, instance_uuid, SnapshotOptions(require_consistent=consistent)
        )
        click.echo(
            f"restore_point={result.restore_point_id} "
            f"volumes={result.volumes_snapshotted} consistent={result.consistent}"
        )
    finally:
        session.close()
        engine.dispose()


def _restore_gateway_factory(conn):
    from osbak.restore.gateway_mutations import SDKRestoreGateway

    return SDKRestoreGateway(conn)


def _make_session(settings: Settings):
    engine = create_engine_by_url(settings.database.url)
    init_db(engine)
    return engine, make_session_factory(engine)()


@main.group()
def restore() -> None:
    """Restore komutlari (iki fazli: plan -> apply)."""


@restore.command("plan")
@click.argument("restore_point_id", type=int)
@click.option("--strategy", type=click.Choice(["rebuild"]), default="rebuild")
@click.option("--no-keep-ip", is_flag=True, default=False)
@click.option("--name", "instance_name", default=None, type=str)
@click.option("--az", "availability_zone", default=None, type=str)
@click.pass_context
def restore_plan(
    ctx: click.Context,
    restore_point_id: int,
    strategy: str,
    no_keep_ip: bool,
    instance_name: str | None,
    availability_zone: str | None,
) -> None:
    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    try:
        options = RestoreOptions(
            strategy=RestoreStrategy(strategy),
            instance_name=instance_name,
            availability_zone=availability_zone,
            keep_ip=not no_keep_ip,
        )
        service = RestoreService(session, None, lambda: None)
        op_id = service.plan(restore_point_id, options)
        plan = session.get(RestoreOp, op_id).plan
        click.echo(
            f"restore_op={op_id} state=PLANNED strategy={strategy} "
            f"steps={len(plan['steps'])} resource_delta={plan['resource_delta']}"
        )
    finally:
        session.close()
        engine.dispose()


@restore.command("apply")
@click.argument("restore_op_id", type=int)
@click.pass_context
def restore_apply(ctx: click.Context, restore_op_id: int) -> None:
    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    try:
        conn = _build_connection(settings)
        gateway = SDKGateway(conn)
        service = RestoreService(session, gateway, lambda: _restore_gateway_factory(conn))
        result = service.apply(restore_op_id)
        server = result.server_id or "-"
        click.echo(f"restore_op={result.restore_op_id} state={result.state} server={server}")
    finally:
        session.close()
        engine.dispose()


@restore.command("show")
@click.argument("restore_op_id", type=int)
@click.pass_context
def restore_show(ctx: click.Context, restore_op_id: int) -> None:
    import json

    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    try:
        service = RestoreService(session, None, lambda: None)
        op = service.show(restore_op_id)
        click.echo(json.dumps({
            "id": op.id, "state": op.state, "strategy": op.strategy,
            "error": op.error, "finished_at": op.finished_at.isoformat()
            if op.finished_at else None,
            "mapping": op.mapping,
        }, sort_keys=True))
    finally:
        session.close()
        engine.dispose()
