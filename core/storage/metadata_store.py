from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from models.result_models import TransactionRecord
from models.station_models import DeviceConnectionConfig, MetadataBundle, ProjectProfile, SiteProfile


class MetadataStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "studio.db"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists projects (
                    code text primary key,
                    name text not null,
                    principal text,
                    archive_root text,
                    notes text
                )
                """
            )
            conn.execute(
                """
                create table if not exists sites (
                    station_code text primary key,
                    station_name text not null,
                    location text,
                    canopy_height_m real,
                    altitude_m real,
                    timezone text
                )
                """
            )
            conn.execute(
                """
                create table if not exists devices (
                    uid text primary key,
                    label text not null,
                    port text not null,
                    baudrate integer not null,
                    device_id text not null,
                    software_profile text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists transactions (
                    transaction_id text primary key,
                    created_at text not null,
                    finished_at text,
                    label text not null,
                    command_text text not null,
                    device_uid text not null,
                    device_id text not null,
                    dangerous integer not null,
                    status text not null,
                    response_text text,
                    response_quality text,
                    response_summary text,
                    metadata_json text
                )
                """
            )
            conn.execute(
                """
                create table if not exists metadata_documents (
                    doc_key text primary key,
                    payload_json text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists alternative_metadata (
                    profile_name text primary key,
                    payload_json text not null,
                    updated_at text not null
                )
                """
            )

    def upsert_project(self, profile: ProjectProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into projects(code, name, principal, archive_root, notes)
                values (?, ?, ?, ?, ?)
                on conflict(code) do update set
                    name=excluded.name,
                    principal=excluded.principal,
                    archive_root=excluded.archive_root,
                    notes=excluded.notes
                """,
                (profile.code, profile.name, profile.principal, profile.archive_root, profile.notes),
            )

    def upsert_site(self, profile: SiteProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into sites(station_code, station_name, location, canopy_height_m, altitude_m, timezone)
                values (?, ?, ?, ?, ?, ?)
                on conflict(station_code) do update set
                    station_name=excluded.station_name,
                    location=excluded.location,
                    canopy_height_m=excluded.canopy_height_m,
                    altitude_m=excluded.altitude_m,
                    timezone=excluded.timezone
                """,
                (
                    profile.station_code,
                    profile.station_name,
                    profile.location,
                    profile.canopy_height_m,
                    profile.altitude_m,
                    profile.timezone,
                ),
            )

    def upsert_device(self, config: DeviceConnectionConfig) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into devices(uid, label, port, baudrate, device_id, software_profile)
                values (?, ?, ?, ?, ?, ?)
                on conflict(uid) do update set
                    label=excluded.label,
                    port=excluded.port,
                    baudrate=excluded.baudrate,
                    device_id=excluded.device_id,
                    software_profile=excluded.software_profile
                """,
                (
                    config.uid,
                    config.label,
                    config.port,
                    config.baudrate,
                    config.device_id,
                    config.software_profile,
                ),
            )

    def append_transaction(self, record: TransactionRecord) -> None:
        row = record.to_row()
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into transactions(
                    transaction_id, created_at, finished_at, label, command_text,
                    device_uid, device_id, dangerous, status, response_text,
                    response_quality, response_summary, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["transaction_id"],
                    row["created_at"],
                    row["finished_at"],
                    row["label"],
                    row["command_text"],
                    row["device_uid"],
                    row["device_id"],
                    row["dangerous"],
                    row["status"],
                    row["response_text"],
                    row["response_quality"],
                    row["response_summary"],
                    json.dumps(row["metadata_json"], ensure_ascii=False),
                ),
            )

    def recent_transactions(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select transaction_id, created_at, label, device_id, status, response_quality, response_summary
                from transactions
                order by created_at desc
                limit ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "transaction_id": row[0],
                "created_at": row[1],
                "label": row[2],
                "device_id": row[3],
                "status": row[4],
                "response_quality": row[5],
                "response_summary": row[6],
            }
            for row in rows
        ]

    def save_metadata_document(self, doc_key: str, payload: dict) -> None:
        updated_at = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                insert into metadata_documents(doc_key, payload_json, updated_at)
                values (?, ?, ?)
                on conflict(doc_key) do update set
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (doc_key, json.dumps(payload, ensure_ascii=False, indent=2), updated_at),
            )

    def load_metadata_document(self, doc_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from metadata_documents where doc_key = ?",
                (doc_key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row[0]))

    def save_alternative_metadata(self, profile_name: str, bundle: MetadataBundle | dict) -> None:
        payload = bundle.to_dict() if isinstance(bundle, MetadataBundle) else dict(bundle)
        updated_at = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                insert into alternative_metadata(profile_name, payload_json, updated_at)
                values (?, ?, ?)
                on conflict(profile_name) do update set
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (profile_name, json.dumps(payload, ensure_ascii=False, indent=2), updated_at),
            )

    def load_alternative_metadata(self, profile_name: str) -> MetadataBundle | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from alternative_metadata where profile_name = ?",
                (profile_name,),
            ).fetchone()
        if row is None:
            return None
        return MetadataBundle.from_dict(json.loads(str(row[0])))

    def list_alternative_metadata(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "select profile_name from alternative_metadata order by profile_name asc"
            ).fetchall()
        return [str(row[0]) for row in rows]
