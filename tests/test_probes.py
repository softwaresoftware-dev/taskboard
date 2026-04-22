"""Tests for built-in probe primitives. Network probes use monkeypatched clients
so the suite stays offline-safe."""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from mindframe.contract import Context
from mindframe.probes import cmd_probe, file_probe, http_probe, tcp_probe


# ---------- http ----------


def test_http_success():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-length": "42", "server": "nginx", "content-type": "text/html"}
    fake_resp.request.url = "https://example.com"

    with patch.object(http_probe.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.request.return_value = fake_resp
        status = http_probe.probe("http", "https://example.com", Context())

    assert status.error is None
    assert status.facts["status_code"] == 200
    assert status.facts["reachable"] is True
    assert status.facts["content_length"] == 42


def test_http_network_error():
    with patch.object(http_probe.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.request.side_effect = httpx.ConnectError("refused")
        status = http_probe.probe("http", "https://example.com", Context())

    assert status.facts["reachable"] is False
    assert status.error is not None
    assert "ConnectError" in status.error


def test_http_method_prefix():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {}
    fake_resp.request.url = "https://example.com"

    with patch.object(http_probe.httpx, "Client") as client_cls:
        instance = client_cls.return_value.__enter__.return_value
        instance.request.return_value = fake_resp
        http_probe.probe("http", "HEAD https://example.com", Context())
        method, url = instance.request.call_args.args
        assert method == "HEAD"
        assert url == "https://example.com"


def test_http_unknown_kind():
    import pytest
    with pytest.raises(ValueError):
        http_probe.probe("tcp", "x", Context())


# ---------- tcp ----------


def test_tcp_success():
    fake_sock = MagicMock()
    fake_sock.__enter__.return_value = fake_sock
    with patch.object(tcp_probe.socket, "create_connection", return_value=fake_sock):
        status = tcp_probe.probe("tcp", "1.1.1.1:53", Context())
    assert status.facts["reachable"] is True
    assert status.error is None


def test_tcp_failure():
    with patch.object(tcp_probe.socket, "create_connection", side_effect=OSError("refused")):
        status = tcp_probe.probe("tcp", "127.0.0.1:1", Context())
    assert status.facts["reachable"] is False
    assert "OSError" in status.error


def test_tcp_bad_ref():
    import pytest
    with pytest.raises(ValueError):
        tcp_probe.probe("tcp", "no-port-here", Context())


# ---------- cmd ----------


def test_cmd_success():
    status = cmd_probe.probe("cmd", "true", Context())
    assert status.facts["ok"] is True
    assert status.facts["exit_code"] == 0


def test_cmd_failure():
    status = cmd_probe.probe("cmd", "false", Context())
    assert status.facts["ok"] is False
    assert status.facts["exit_code"] == 1


def test_cmd_stdout_captured():
    status = cmd_probe.probe("cmd", "echo hello", Context())
    assert status.facts["ok"] is True
    assert "hello" in status.details["stdout"]


def test_cmd_timeout():
    status = cmd_probe.probe("cmd", "sleep 2", Context(config={"timeout": 0.1}))
    assert status.facts["ok"] is False
    assert status.error is not None
    assert "timeout" in status.error.lower()


# ---------- file ----------


def test_file_exists(tmp_path: Path):
    p = tmp_path / "sentinel"
    p.write_text("hi")
    status = file_probe.probe("file", str(p), Context())
    assert status.facts["exists"] is True
    assert status.facts["size_bytes"] == 2
    assert status.facts["age_seconds"] is not None


def test_file_missing(tmp_path: Path):
    status = file_probe.probe("file", str(tmp_path / "nope"), Context())
    assert status.facts["exists"] is False
    assert status.facts["size_bytes"] is None
