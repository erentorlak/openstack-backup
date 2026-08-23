from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osbak.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keystone_project_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    instances: Mapped[list["Instance"]] = relationship(back_populates="project")


class Instance(Base):
    __tablename__ = "instances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    project: Mapped["Project"] = relationship(back_populates="instances")
    volumes: Mapped[list["VolumeRef"]] = relationship(back_populates="instance")


class VolumeRef(Base):
    __tablename__ = "volume_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("instances.id"))
    volume_uuid: Mapped[str] = mapped_column(String(64))
    boot_index: Mapped[int] = mapped_column(Integer)
    size_gb: Mapped[int] = mapped_column(Integer)
    volume_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backend: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pool: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    instance: Mapped["Instance"] = relationship(back_populates="volumes")


class RestorePoint(Base):
    __tablename__ = "restore_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    instance_id: Mapped[int] = mapped_column(ForeignKey("instances.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    policy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("policies.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)


class VolumeBackup(Base):
    __tablename__ = "volume_backups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restore_point_id: Mapped[int] = mapped_column(ForeignKey("restore_points.id"))
    volume_ref_id: Mapped[int] = mapped_column(ForeignKey("volume_refs.id"))
    snapshot_ref: Mapped[str] = mapped_column(String(256))
    tier: Mapped[str] = mapped_column(String(8))
    object_manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    incremental_from_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("volume_backups.id"), nullable=True
    )


class Chunk(Base):
    __tablename__ = "chunks"
    chunk_hash: Mapped[str] = mapped_column("hash", String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    refcount: Mapped[int] = mapped_column(Integer, default=0)


class VolumeChunkMap(Base):
    __tablename__ = "volume_chunk_map"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    volume_backup_id: Mapped[int] = mapped_column(ForeignKey("volume_backups.id"))
    chunk_hash: Mapped[str] = mapped_column(ForeignKey("chunks.hash"))
    offset_bytes: Mapped[int] = mapped_column(Integer)
    length: Mapped[int] = mapped_column(Integer)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON)
    retention: Mapped[dict[str, Any]] = mapped_column(JSON)
    quiesce_policy: Mapped[str] = mapped_column(String(16), default="allow_crash")
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    policy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("policies.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    dry_run: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)


class RestoreOp(Base):
    __tablename__ = "restore_ops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restore_point_id: Mapped[int] = mapped_column(ForeignKey("restore_points.id"))
    strategy: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32))
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
