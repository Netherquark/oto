#!/usr/bin/env python3
"""telemetry.py: Minimal, non-root, systemd-distro sysfs amdgpu sensor reader.

Run-wide sampler: one instance is started per run directory and kept alive
across all phases, so a whole run's timeline survives (no per-phase CSV
truncation). Each row is tagged with the currently-active `phase_id` via
`set_phase()`, giving continuous coverage plus per-phase attribution in a
single CSV. `start()` is restart-safe: it never truncates an existing file
(headers are appended only when missing).
"""
import time
import threading
from pathlib import Path
from typing import Optional, Dict

# Header is the schema descriptor; CSV consumers use csv.DictReader (name-keyed).
HEADER = ("timestamp,sclk_hz,mclk_hz,power_uw,temp_mc,gpu_busy_percent,"
          "vram_used_bytes,vram_total_bytes,phase_id")

class TelemetrySampler:
    def __init__(self, log_path: Path, interval_s: float = 0.1):
        self.log_path = Path(log_path)
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_phase = ""
        self._warned_missing_busy = False
        self.device_dir, self.hwmon_dir = self._discover_amdgpu()

    def _discover_amdgpu(self):
        # Primary: /sys/class/drm/cardN/device. Only accept entries that carry
        # the amdgpu driver AND expose gpu_busy_percent, so connector dirs
        # (card1-DP-1/device -> symlink to the card node, no busy file) can
        # never be mis-selected.
        drm_base = Path("/sys/class/drm")
        if drm_base.exists():
            for card in sorted(drm_base.glob("card[0-9]*/device")):
                if not (card / "gpu_busy_percent").is_file():
                    continue
                uevent = card / "uevent"
                if uevent.exists() and "DRIVER=amdgpu" in uevent.read_text(errors="ignore"):
                    hwmon_dirs = list((card / "hwmon").glob("hwmon*"))
                    hwmon = hwmon_dirs[0] if hwmon_dirs else None
                    return card, hwmon
        # Fallback: /sys/class/hwmon entry named "amdgpu". Its resolved path is
        # .../<pci-dev>/hwmon/hwmonN, so the device dir is parent.parent
        # (NO "/device" suffix — that would double-append and never resolve).
        hwmon_base = Path("/sys/class/hwmon")
        if hwmon_base.exists():
            for hw in hwmon_base.glob("hwmon*"):
                name = hw / "name"
                if name.exists() and "amdgpu" in name.read_text(errors="ignore"):
                    res = hw.resolve()
                    dev_dir = res.parent.parent
                    if (dev_dir / "gpu_busy_percent").is_file():
                        return dev_dir, res
                    return dev_dir, res
        return None, None

    @staticmethod
    def _parse_dpm(path: Path) -> int:
        if not path or not path.is_file(): return 0
        try:
            for line in path.read_text().splitlines():
                if "*" in line:
                    for p in line.split():
                        if p.lower().endswith("mhz"):
                            return int(float(p[:-3])) * 1_000_000
        except Exception:
            pass
        return 0

    @staticmethod
    def _read_int(path: Optional[Path], default: int = 0) -> int:
        if not path or not path.is_file(): return default
        try:
            return int(path.read_text().strip())
        except Exception:
            return default

    def set_phase(self, phase_id: str) -> None:
        """Tag subsequent samples with the active phase ('' = between phases)."""
        self._current_phase = phase_id or ""

    def sample_row(self) -> Dict[str, object]:
        now = time.time()
        if not self.device_dir:
            return {"ts": now, "sclk": 0, "mclk": 0, "pwr": 0, "temp": 0, "busy": 0, "vram_u": 0, "vram_t": 0, "phase": ""}
        if (self.device_dir / "gpu_busy_percent").is_file():
            busy = self._read_int(self.device_dir / "gpu_busy_percent", 0)
        else:
            if not self._warned_missing_busy:
                print(f"[telemetry] WARNING: no gpu_busy_percent at "
                      f"{self.device_dir / 'gpu_busy_percent'} — busy reads 0.")
                self._warned_missing_busy = True
            busy = 0

        sclk = 0
        if self.hwmon_dir:
            sclk = self._read_int(self.hwmon_dir / "freq1_input", 0)
        if sclk == 0:
            sclk = self._parse_dpm(self.device_dir / "pp_dpm_sclk")

        mclk = self._parse_dpm(self.device_dir / "pp_dpm_mclk")

        pwr = 0
        if self.hwmon_dir:
            pwr = self._read_int(self.hwmon_dir / "power1_input", 0)
            if pwr == 0:
                pwr = self._read_int(self.hwmon_dir / "power1_average", 0)

        temp = self._read_int(self.hwmon_dir / "temp1_input", 0) if self.hwmon_dir else 0
        vram_u = self._read_int(self.device_dir / "mem_info_vram_used", 0)
        vram_t = self._read_int(self.device_dir / "mem_info_vram_total", 0)

        return {"ts": now, "sclk": sclk, "mclk": mclk, "pwr": pwr, "temp": temp,
                "busy": busy, "vram_u": vram_u, "vram_t": vram_t, "phase": self._current_phase}

    def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        lines = self.log_path.read_text().splitlines() if self.log_path.exists() else []
        header_missing = not lines or not lines[0].startswith("timestamp")
        if header_missing:
            # Append (never truncate): a restart mid-run must not destroy data.
            with open(self.log_path, "a") as f:
                f.write(HEADER + "\n")

        def _loop():
            while not self._stop_event.is_set():
                row = self.sample_row()
                with open(self.log_path, "a") as f:
                    f.write(f"{row['ts']},{row['sclk']},{row['mclk']},{row['pwr']},{row['temp']},{row['busy']},{row['vram_u']},{row['vram_t']},{row['phase']}\n")
                time.sleep(self.interval_s)

        self._stop_event.clear()
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)