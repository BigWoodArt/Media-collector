"""A tiny WebSocket client (RFC 6455, text frames only) so the app can talk to a browser on localhost without
extra packages. Just enough for the Chrome DevTools protocol; not a general-purpose library."""
import base64
import json
import os
import socket
import struct
import urllib.parse


class WSError(OSError):
    pass


class WebSocket:
    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        if u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise WSError("only ws:// connections to this computer are allowed")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("browser closed the connection during the handshake")
            head += chunk
        head, _, self._buf = head.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise WSError("browser refused the WebSocket: " + head.split(b"\r\n")[0].decode("latin1"))
        self._next_id = 0

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_text(self, text):
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv_text(self):
        """Next complete text message (handles fragments, answers pings)."""
        message = b""
        while True:
            b0, b1 = self._read(2)
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)             # servers never mask
            if opcode == 0x9:                   # ping -> pong
                mask = os.urandom(4)
                self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask +
                                  bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
                continue
            if opcode == 0x8:
                raise WSError("browser closed the connection")
            message += payload
            if b0 & 0x80:                       # FIN
                return message.decode("utf-8", "replace")

    def call(self, method, params=None):
        """DevTools command -> result dict (raises WSError on an error reply)."""
        self._next_id += 1
        self.send_text(json.dumps({"id": self._next_id, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(self.recv_text())
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise WSError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
