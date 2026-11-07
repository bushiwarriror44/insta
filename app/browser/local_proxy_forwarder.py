"""Loopback HTTP proxy that injects Proxy-Authorization to an upstream HTTP proxy."""
from __future__ import annotations

import asyncio
import base64
import threading

from app.logging_setup import get_logger

logger = get_logger(__name__)

_READ_LIMIT = 65536


class LocalProxyForwarder:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.Server | None = None
        self.local_port: int = 0
        self._upstream_host: str = ""
        self._upstream_port: int = 0
        self._auth_header: bytes = b""

    @property
    def local_proxy_server(self) -> str:
        if self.local_port <= 0:
            raise RuntimeError("forwarder не запущен")
        return f"http://127.0.0.1:{self.local_port}"

    def start(
        self,
        *,
        upstream_host: str,
        upstream_port: int,
        username: str,
        password: str,
    ) -> str:
        if self._thread is not None:
            raise RuntimeError("forwarder уже запущен")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8"))
        self._auth_header = b"Proxy-Authorization: Basic " + token + b"\r\n"
        self._upstream_host = upstream_host
        self._upstream_port = upstream_port

        ready = threading.Event()
        error: list[BaseException] = []

        def _run() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                loop.run_until_complete(self._async_start(ready))
                loop.run_forever()
            except BaseException as exc:  # noqa: BLE001
                error.append(exc)
                ready.set()
            finally:
                if self._loop is not None:
                    try:
                        self._loop.close()
                    except Exception:
                        pass
                self._loop = None

        self._thread = threading.Thread(target=_run, name="local-proxy-forwarder", daemon=True)
        self._thread.start()
        if not ready.wait(timeout=10.0):
            self.stop()
            raise RuntimeError("таймаут запуска local proxy forwarder")
        if error:
            self.stop()
            raise RuntimeError(f"forwarder: {error[0]}") from error[0]
        logger.info(
            "local_proxy_forwarder.started",
            local_port=self.local_port,
            upstream=f"{upstream_host}:{upstream_port}",
        )
        return self.local_proxy_server

    async def _async_start(self, ready: threading.Event) -> None:
        assert self._loop is not None
        self._server = await asyncio.start_server(
            self._handle_client,
            host="127.0.0.1",
            port=0,
            limit=_READ_LIMIT,
        )
        sockets = self._server.sockets or []
        if not sockets:
            raise RuntimeError("не удалось привязать local proxy")
        self.local_port = int(sockets[0].getsockname()[1])
        ready.set()

    def stop(self) -> None:
        loop = self._loop
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self.local_port = 0

        if loop is not None and server is not None:
            async def _close() -> None:
                server.close()
                await server.wait_closed()

            try:
                asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout=5.0)
            except Exception:
                pass
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._loop = None
        logger.info("local_proxy_forwarder.stopped")

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await client_reader.readline()
            if not request_line:
                return
            line = request_line.decode("latin-1", errors="replace").strip()
            parts = line.split()
            if len(parts) < 2:
                return
            method, target = parts[0].upper(), parts[1]

            headers = await self._read_headers(client_reader)
            body = b""
            if method in ("POST", "PUT", "PATCH"):
                cl = headers.get("content-length")
                if cl and cl.isdigit():
                    body = await client_reader.readexactly(int(cl))

            upstream_reader: asyncio.StreamReader | None = None
            upstream_writer: asyncio.StreamWriter | None = None
            try:
                upstream_reader, upstream_writer = await asyncio.open_connection(
                    self._upstream_host,
                    self._upstream_port,
                )
            except OSError as exc:
                await self._respond(client_writer, 502, f"upstream connect failed: {exc}")
                return

            assert upstream_writer is not None and upstream_reader is not None

            if method == "CONNECT":
                host_port = target
                req = (
                    f"CONNECT {host_port} HTTP/1.1\r\n"
                    f"Host: {host_port}\r\n"
                ).encode("latin-1") + self._auth_header + b"\r\n"
                upstream_writer.write(req)
                await upstream_writer.drain()
                upstream_status = await upstream_reader.readline()
                await self._drain_headers(upstream_reader)
                if b" 200" not in upstream_status:
                    client_writer.write(upstream_status)
                    await client_writer.drain()
                    await self._drain_headers(client_reader)
                    return
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                await self._tunnel(client_reader, client_writer, upstream_reader, upstream_writer)
                return

            # Plain HTTP via proxy (absolute-form URI).
            forwarded = (
                f"{method} {target} HTTP/1.1\r\n".encode("latin-1")
                + self._encode_forward_headers(headers)
                + self._auth_header
                + b"\r\n"
            )
            if body:
                forwarded += body
            upstream_writer.write(forwarded)
            await upstream_writer.drain()
            await self._relay_response(upstream_reader, client_writer)
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("local_proxy_forwarder.client_error", error=str(exc))
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            decoded = line.decode("latin-1", errors="replace").strip()
            if ":" in decoded:
                key, _, val = decoded.partition(":")
                headers[key.strip().lower()] = val.strip()
        return headers

    async def _drain_headers(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

    def _encode_forward_headers(self, headers: dict[str, str]) -> bytes:
        skip = frozenset(
            {"proxy-connection", "proxy-authorization", "connection", "keep-alive", "te", "trailers"}
        )
        lines: list[bytes] = []
        for key, val in headers.items():
            if key.lower() in skip:
                continue
            lines.append(f"{key}: {val}\r\n".encode("latin-1"))
        return b"".join(lines)

    async def _respond(self, writer: asyncio.StreamWriter, code: int, message: str) -> None:
        body = message.encode("utf-8")
        resp = (
            f"HTTP/1.1 {code} {message}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1") + body
        writer.write(resp)
        await writer.drain()

    async def _relay_response(
        self,
        upstream_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        while True:
            chunk = await upstream_reader.read(_READ_LIMIT)
            if not chunk:
                break
            client_writer.write(chunk)
            await client_writer.drain()

    async def _tunnel(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        async def _pipe(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                while True:
                    data = await reader.read(_READ_LIMIT)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
                pass

        t1 = asyncio.create_task(_pipe(client_reader, upstream_writer))
        t2 = asyncio.create_task(_pipe(upstream_reader, client_writer))
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
        try:
            upstream_writer.close()
            await upstream_writer.wait_closed()
        except Exception:
            pass
