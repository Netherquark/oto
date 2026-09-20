#!/usr/bin/env python3
"""telemetry.py: Minimal, non-root, systemd-distro sysfs amdgpu sensor reader."""
import time
import threading
from pathlib import Path
from typing import Optional, Dict

class TelemetrySampler:
    def __init__(self, log_path: Path, interval_s: float = 0.1):
        self.log_path = Path(log_path)
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.device_dir, self.hwmon_dir = self._discover_amdgpu()

    def _discover_amdgpu(self):
        drm_base = Path("/sys/class/drm")
        if drm_base.exists():
            for card in sorted(drm_base.glob("card[0-9]*/device")):
                uevent = card / "uevent"
                if uevent.exists() and "DRIVER=amdgpu" in uevent.read_text(errors="ignore"):
                    hwmon_dirs = list((card / "hwmon").glob("hwmon*"))
                    hwmon = hwmon_dirs[0] if hwmon_dirs else None
                    return card, hwmon
        hwmon_base = Path("/sys/class/hwmon")
        if hwmon_base.exists():
            for hw in hwmon_base.glob("hwmon*"):
                name = hw / "name"
                if name.exists() and "amdgpu" in name.read_text(errors="ignore"):
                    return hw.resolve().parent.parent / "device", hw
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

    def sample_row(self) -> Dict[str, int]:
        now = time.time()
        if not self.device_dir:
            return {"ts": now, "sclk": 0, "mclk": 0, "pwr": 0, "temp": 0, "busy": 0, "vram_u": 0, "vram_t": 0}

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
        busy = self._read_int(self.device_dir / "gpu_busy_percent", 0)
        vram_u = self._read_int(self.device_dir / "mem_info_vram_used", 0)
        vram_t = self._read_int(self.device_dir / "mem_info_vram_total", 0)

        return {"ts": now, "sclk": sclk, "mclk": mclk, "pwr": pwr, "temp": temp, "busy": busy, "vram_u": vram_u, "vram_t": vram_t}

    def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w") as f:
            f.write("timestamp,sclk_hz,mclk_hz,power_uw,temp_mc,gpu_busy_percent,vram_used_bytes,vram_total_bytes\n")
        
        def _loop():
            while not self._stop_event.is_set():
                row = self.sample_row()
                with open(self.log_path, "a") as f:
                    f.write(f"{row['ts']},{row['sclk']},{row['mclk']},{row['pwr']},{row['temp']},{row['busy']},{row['vram_u']},{row['vram_t']}\n")
                time.sleep(self.interval_s)

        self._stop_event.clear()
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
