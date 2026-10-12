"""Agent reference sources: allowlist, SSRF guards, file confinement."""

from __future__ import annotations

import pytest

from app.agent.sources import SourceError, check_url, read_file, resolve_reference
from app.config import Settings


def test_check_url_rejects_non_http_scheme(tmp_path):
    settings = Settings(
        reference_dir=str(tmp_path),
        reference_allowed_hosts="example.com",
    )
    with pytest.raises(SourceError, match="только источники http"):
        check_url("file:///etc/passwd", settings)


def test_check_url_empty_allowlist_refuses(tmp_path):
    settings = Settings(
        reference_dir=str(tmp_path),
        reference_allowed_hosts="",
    )
    with pytest.raises(SourceError, match="хосты не разрешены"):
        check_url("https://example.com/page", settings)


def test_check_url_host_not_on_allowlist(tmp_path):
    settings = Settings(
        reference_dir=str(tmp_path),
        reference_allowed_hosts="example.com",
    )
    with pytest.raises(SourceError, match="нет в REFERENCE_ALLOWED_HOSTS"):
        check_url("https://other.test/page", settings)


def test_check_url_private_address_refused(tmp_path, monkeypatch):
    settings = Settings(
        reference_dir=str(tmp_path),
        reference_allowed_hosts="localhost",
    )

    def _fake_addrinfo(host, _port):
        return [(None, None, None, None, ("127.0.0.1", 0))]

    monkeypatch.setattr("app.agent.sources.socket.getaddrinfo", _fake_addrinfo)
    with pytest.raises(SourceError, match="частный адрес"):
        check_url("https://localhost/page", settings)


def test_resolve_reference_rejects_path_traversal(tmp_path):
    root = tmp_path / "refs"
    root.mkdir()
    settings = Settings(reference_dir=str(root), reference_allowed_hosts="")
    with pytest.raises(SourceError, match="выходит за каталог"):
        resolve_reference("../outside.txt", settings)


def test_read_file_rejects_unknown_suffix(tmp_path):
    root = tmp_path / "refs"
    root.mkdir()
    (root / "notes.pdf").write_bytes(b"%PDF")
    settings = Settings(reference_dir=str(root), reference_allowed_hosts="")
    with pytest.raises(SourceError, match="читаются только файлы"):
        read_file("notes.pdf", settings)
