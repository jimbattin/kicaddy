"""doctor's `server` check, run from the venv: version handshake, settings directory, library tables, and a
schematic round trip (place, wire, save, netlist) on the isolated config."""

import tempfile
import time
from pathlib import Path

from . import runtime, schematic


def run(launcher, bindings, config_home, settings_dir, expect_version):
    proto = schematic.bind(bindings)
    lt = proto.library_types
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kicaddy-smoke-") as tmp, \
            runtime.server(launcher, Path(config_home), project_dir=Path(tmp)) as api:
        version = api(proto.base.GetVersion()).version.full_version
        if version.split(",")[0].strip() != expect_version.split(",")[0].strip():
            raise RuntimeError(f"server reports {version}, kicad-cli reports {expect_version}")

        paths = {proto.enums.PathType.Name(e.type): e.path for e in api(proto.base.GetPaths()).paths}
        got = paths.get("PATH_USER_SETTINGS")
        if got is None or Path(got).resolve() != Path(settings_dir).resolve():
            raise RuntimeError(f"server uses settings dir {got}, doctor wrote library tables to {settings_dir}")

        runtime.wait_for_symbol_libraries(api, {"Device", "power"})
        n_sym = len(api(proto.library.GetLibraryStatuses(types=[lt.LT_SYMBOL], scope=lt.LTS_BOTH)).libraries)
        n_fp = len(api(proto.library.GetLibraryStatuses(types=[lt.LT_FOOTPRINT], scope=lt.LTS_BOTH)).libraries)
        if not n_sym:
            raise RuntimeError("no symbol libraries in the library tables")

        path = Path(tmp) / "smoke.kicad_sch"
        sch = schematic.Schematic(api, path)
        sch.symbol("R1", "Device:R", (20, 20))
        sch.symbol("R2", "Device:R", (20, 30))
        sch.wire("R1.2", "R2.1")
        sch.commit()
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"schematic round trip: {path.name} not saved")
        nets = sch.netlist()
        if not any(members == {"R1.2", "R2.1"} for _, members in nets):
            raise RuntimeError(f"schematic round trip: no net R1.2-R2.1 in {nets}")
    return {"full_version": version, "symbol_libraries": n_sym, "footprint_libraries": n_fp,
            "seconds": round(time.monotonic() - t0, 1)}
