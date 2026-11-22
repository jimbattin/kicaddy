#!/usr/bin/env python3
"""Minimal KiCad IPC API client: start a headless server, query it, shut it down.

Verified against KiCad 10.99.0-6860-gbdd2930d2b (nightly AppImage).

Requires `pynng`, `protobuf`, and Python bindings generated from the KiCad
`api/proto` tree of the matching commit (see docs/02-ipc-protocol.md, "Client bindings").

    python minimal_client.py --bindings <gen-dir> [PROJECT_OR_FILE]
"""

import argparse
import collections
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DOC_TYPES = {".kicad_sch": "DOCTYPE_SCHEMATIC", ".kicad_pcb": "DOCTYPE_PCB"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kicad", default=str(Path.home() / ".local/bin/kicad-nightly"),
                        help="KiCad AppImage, or a kicad-cli binary")
    parser.add_argument("--bindings", required=True, help="directory holding the generated *_pb2.py tree")
    parser.add_argument("file", nargs="?", help=".kicad_sch or .kicad_pcb to pre-load")
    args = parser.parse_args()

    sys.path.insert(0, args.bindings)
    import pynng
    from common import envelope_pb2
    from common.commands import base_commands_pb2, editor_commands_pb2
    from common.types import base_types_pb2

    # The AppImage's AppRun dispatches to a bundled tool named by the first argument.
    launcher = [args.kicad] if Path(args.kicad).name.startswith("kicad-cli") else [args.kicad, "kicad-cli"]

    with tempfile.TemporaryDirectory(prefix="kicad-ipc-") as tmp:
        socket_path = Path(tmp) / "api.sock"
        command = [*launcher, "api-server", "--socket", str(socket_path)]
        if args.file:
            command.append(args.file)

        # No display is needed. stdout is block-buffered when piped, so the
        # "listening at" banner is NOT a usable readiness signal; poll the socket instead.
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        server = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        try:
            deadline = time.monotonic() + 60
            while not socket_path.exists():
                if server.poll() is not None:
                    raise RuntimeError(f"api-server exited with code {server.returncode}")
                if time.monotonic() > deadline:
                    raise TimeoutError("api-server did not create its socket")
                time.sleep(0.05)

            with pynng.Req0(dial=f"ipc://{socket_path}", send_timeout=10000, recv_timeout=10000) as sock:

                def call(request, response_type):
                    envelope = envelope_pb2.ApiRequest()
                    envelope.header.client_name = f"minimal-client-{os.getpid()}"
                    envelope.message.Pack(request)

                    # The socket accepts requests before a pre-loaded file has finished loading;
                    # until then every request is answered with AS_NOT_READY.
                    while True:
                        sock.send(envelope.SerializeToString())
                        reply = envelope_pb2.ApiResponse()
                        reply.ParseFromString(sock.recv())
                        if reply.status.status != envelope_pb2.AS_NOT_READY:
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError("api-server never became ready")
                        time.sleep(0.05)

                    if reply.status.status != envelope_pb2.AS_OK:
                        code = envelope_pb2.ApiStatusCode.Name(reply.status.status)
                        raise RuntimeError(f"{type(request).__name__}: {code}: {reply.status.error_message}")

                    response = response_type()
                    if not reply.message.Unpack(response):
                        raise RuntimeError(f"unexpected response type {reply.message.type_url}")
                    return response

                version = call(base_commands_pb2.GetVersion(), base_commands_pb2.GetVersionResponse).version
                print(f"KiCad {version.full_version}")

                doc_type = DOC_TYPES.get(Path(args.file).suffix) if args.file else None
                if doc_type:
                    request = editor_commands_pb2.GetOpenDocuments(type=base_types_pb2.DocumentType.Value(doc_type))
                    document = call(request, editor_commands_pb2.GetOpenDocumentsResponse).documents[0]

                    header = base_types_pb2.ItemHeader(document=document)
                    items = call(editor_commands_pb2.GetItems(header=header), editor_commands_pb2.GetItemsResponse)
                    counts = collections.Counter(item.type_url.rsplit(".", 1)[-1] for item in items.items)
                    for name, count in sorted(counts.items()):
                        print(f"{count:6d}  {name}")
        finally:
            # SIGINT/SIGTERM shut down cleanly: documents closed, socket and project lock removed.
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
