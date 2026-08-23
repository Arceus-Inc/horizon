"""Test path setup plus the real Postgres fixture used by direction-store contracts."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


_PG_BIN = Path(
    os.environ.get(
        "HORIZON_PG_BIN", os.environ.get("CHORUS_PG_BIN", "/opt/homebrew/opt/postgresql@18/bin")
    )
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def postgres_dsn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real local Postgres cluster, following Chorus's integration-test convention."""
    if not _PG_BIN.exists():
        pytest.skip(f"PostgreSQL not found at {_PG_BIN} (set HORIZON_PG_BIN)")
    data = tmp_path_factory.mktemp("horizon_pgdata")
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run(
        [
            str(_PG_BIN / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    port = _free_port()
    subprocess.run(
        [
            str(_PG_BIN / "pg_ctl"),
            "-D",
            str(data),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''",
            "-l",
            str(data / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    dsn = f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    try:
        yield dsn
    finally:
        subprocess.run(
            [str(_PG_BIN / "pg_ctl"), "-D", str(data), "-w", "stop"],
            capture_output=True,
            env=env,
        )
        shutil.rmtree(data, ignore_errors=True)
