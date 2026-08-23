from __future__ import annotations

from pathlib import Path

import click
import openstack

from osbak.config import Settings
from osbak.db import create_engine_by_url, init_db, make_session_factory
from osbak.discovery.gateway import SDKGateway
from osbak.discovery.service import DiscoveryService
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
    raise NotImplementedError(f"bilinmeyen driver: {driver}")


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
