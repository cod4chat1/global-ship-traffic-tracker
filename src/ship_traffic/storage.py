from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .models import DailyObservation


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_observations (
    observation_date TEXT NOT NULL,
    area_id TEXT NOT NULL,
    area_name TEXT NOT NULL,
    area_type TEXT NOT NULL,
    total REAL,
    bulk_og REAL,
    bulk_non_og REAL,
    container REAL,
    other_cargo REAL,
    others REAL,
    unknown REAL,
    imports_tons REAL,
    exports_tons REAL,
    availability TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (observation_date, area_id, source)
);
CREATE TABLE IF NOT EXISTS run_log (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    target_date TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    message TEXT
);
"""


class Repository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def upsert(self, observations: Iterable[DailyObservation]) -> int:
        rows = [
            (
                item.observation_date.isoformat(),
                item.area_id,
                item.area_name,
                item.area_type,
                item.total,
                item.bulk_og,
                item.bulk_non_og,
                item.container,
                item.other_cargo,
                item.others,
                item.unknown,
                item.imports_tons,
                item.exports_tons,
                item.availability,
                item.source,
                item.source_url,
            )
            for item in observations
        ]
        self.connection.executemany(
            """
            INSERT INTO daily_observations VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(observation_date, area_id, source) DO UPDATE SET
                area_name=excluded.area_name,
                area_type=excluded.area_type,
                total=excluded.total,
                bulk_og=excluded.bulk_og,
                bulk_non_og=excluded.bulk_non_og,
                container=excluded.container,
                other_cargo=excluded.other_cargo,
                others=excluded.others,
                unknown=excluded.unknown,
                imports_tons=excluded.imports_tons,
                exports_tons=excluded.exports_tons,
                availability=excluded.availability,
                source_url=excluded.source_url
            """,
            rows,
        )
        self.connection.commit()
        return len(rows)

    def observations(
        self, start_date: str, end_date: str, source: str | None = None
    ) -> list[dict]:
        sql = """
            SELECT * FROM daily_observations
            WHERE observation_date BETWEEN ? AND ?
        """
        parameters: list[str] = [start_date, end_date]
        if source is not None:
            sql += " AND source = ?"
            parameters.append(source)
        sql += " ORDER BY observation_date, area_type, area_name"
        rows = self.connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def observation_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM daily_observations"
            ).fetchone()[0]
        )

    def start_run(
        self, run_id: str, started_at: str, provider: str, target_date: str
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO run_log (
                run_id, started_at, status, provider, target_date
            ) VALUES (?, ?, 'running', ?, ?)
            """,
            (run_id, started_at, provider, target_date),
        )
        self.connection.commit()

    def finish_run(
        self,
        run_id: str,
        completed_at: str,
        status: str,
        row_count: int,
        warning_count: int,
        message: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE run_log
            SET completed_at=?, status=?, row_count=?, warning_count=?, message=?
            WHERE run_id=?
            """,
            (completed_at, status, row_count, warning_count, message, run_id),
        )
        self.connection.commit()

    def runs(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
        return [dict(row) for row in rows]
