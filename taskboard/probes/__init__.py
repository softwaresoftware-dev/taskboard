"""Built-in probe primitives.

These are live-only escape hatches — no fixtures, no pack generation. They
cover the long tail of "ping this URL" / "is this port open" / "run this
command" without forcing a source pack.

Each primitive exposes the Source protocol (KINDS, REF_SCHEMAS, SCRUB, probe).
Wired into serve() by default under built-in names:

    http   ->  http / https probe
    tcp    ->  raw TCP reachability
    cmd    ->  shell command exit code + stdout
    file   ->  file existence + age
"""
from . import http_probe, tcp_probe, cmd_probe, file_probe

BUILTIN_PACKS = {
    "http": http_probe,
    "tcp":  tcp_probe,
    "cmd":  cmd_probe,
    "file": file_probe,
}
