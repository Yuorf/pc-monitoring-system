import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone

import psutil


def _round_gb(bytes_value: int | float | None) -> float | None:
    if bytes_value is None:
        return None
    return round(bytes_value / (1024**3), 2)


def _to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_string(value: object) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def _format_cim_datetime(value: object) -> str | None:
    text = _to_string(value)
    if text is None:
        return None

    milliseconds_match = re.search(r"/Date\((?P<milliseconds>-?\d+)", text)
    if milliseconds_match:
        try:
            milliseconds = int(milliseconds_match.group("milliseconds"))
            return (
                datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
                .date()
                .isoformat()
            )
        except (TypeError, ValueError, OSError):
            return text

    for date_format in (
        "%Y%m%d%H%M%S.%f%z",
        "%Y%m%d%H%M%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(text, date_format)
            return parsed.date().isoformat()
        except ValueError:
            continue

    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"

    return text


def _normalize_records(data: object) -> list[dict[str, object]]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _run_command(command: list[str], timeout: int = 5) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except Exception:
        return None

    output = result.stdout.strip()
    return output or None


def _run_powershell(command: str, timeout: int = 5) -> str | None:
    return _run_command(
        ["powershell", "-NoProfile", "-Command", command],
        timeout=timeout,
    )


def _run_powershell_json(command: str, timeout: int = 5) -> object | None:
    output = _run_powershell(command, timeout=timeout)
    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _collect_cpu_info() -> dict[str, object]:
    cpu_info = {
        "name": None,
        "manufacturer": None,
        "physical_cores": None,
        "logical_cores": None,
        "logical_processors": None,
        "threads": None,
        "current_frequency_mhz": None,
        "min_frequency_mhz": None,
        "max_frequency_mhz": None,
        "max_clock_mhz": None,
        "cpu_usage": None,
        "per_core_usage": None,
    }

    try:
        cpu_info["physical_cores"] = psutil.cpu_count(logical=False)
    except Exception:
        pass

    try:
        cpu_info["logical_cores"] = psutil.cpu_count(logical=True)
        cpu_info["logical_processors"] = cpu_info["logical_cores"]
        cpu_info["threads"] = cpu_info["logical_cores"]
    except Exception:
        pass

    try:
        cpu_freq = psutil.cpu_freq()
        if cpu_freq is not None:
            cpu_info["current_frequency_mhz"] = _to_float(round(cpu_freq.current, 2))
            cpu_info["min_frequency_mhz"] = _to_float(round(cpu_freq.min, 2))
            cpu_info["max_frequency_mhz"] = _to_float(round(cpu_freq.max, 2))
            cpu_info["max_clock_mhz"] = cpu_info["max_frequency_mhz"]
    except Exception:
        pass

    try:
        per_core_usage = psutil.cpu_percent(interval=1, percpu=True)
        cpu_info["per_core_usage"] = [round(value, 2) for value in per_core_usage]
        if per_core_usage:
            cpu_info["cpu_usage"] = round(sum(per_core_usage) / len(per_core_usage), 2)
        else:
            cpu_info["cpu_usage"] = 0.0
    except Exception:
        pass

    cpu_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed | "
            "ConvertTo-Json -Compress"
        )
    )
    if cpu_records:
        cpu_info["name"] = _to_string(cpu_records[0].get("Name"))
        cpu_info["manufacturer"] = _to_string(cpu_records[0].get("Manufacturer"))
        if cpu_info["physical_cores"] is None:
            cpu_info["physical_cores"] = _to_int(cpu_records[0].get("NumberOfCores"))
        logical_processors = _to_int(cpu_records[0].get("NumberOfLogicalProcessors"))
        if cpu_info["logical_cores"] is None:
            cpu_info["logical_cores"] = logical_processors
        if cpu_info["logical_processors"] is None:
            cpu_info["logical_processors"] = logical_processors
        if cpu_info["threads"] is None:
            cpu_info["threads"] = logical_processors

        max_clock_mhz = _to_float(cpu_records[0].get("MaxClockSpeed"))
        if max_clock_mhz is not None:
            cpu_info["max_clock_mhz"] = max_clock_mhz
            if (
                cpu_info["max_frequency_mhz"] is None
                or cpu_info["max_frequency_mhz"] <= 0
            ):
                cpu_info["max_frequency_mhz"] = max_clock_mhz

    return cpu_info


def _collect_ram_info() -> dict[str, object]:
    ram_info = {
        "total_gb": None,
        "used_gb": None,
        "available_gb": None,
        "percent": None,
        "modules_count": 0,
        "modules": [],
        "memory_modules": [],
    }

    try:
        memory = psutil.virtual_memory()
        ram_info["total_gb"] = _round_gb(memory.total)
        ram_info["used_gb"] = _round_gb(memory.used)
        ram_info["available_gb"] = _round_gb(memory.available)
        ram_info["percent"] = _to_float(memory.percent)
    except Exception:
        pass

    module_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_PhysicalMemory | "
            "Select-Object Capacity, Manufacturer, Speed, ConfiguredClockSpeed, PartNumber, BankLabel | "
            "ConvertTo-Json -Compress"
        )
    )
    modules = [
        {
            "capacity_gb": _round_gb(_to_int(module.get("Capacity"))),
            "manufacturer": _to_string(module.get("Manufacturer")),
            "speed_mhz": _to_int(module.get("Speed")),
            "configured_clock_speed_mhz": _to_int(
                module.get("ConfiguredClockSpeed")
            ),
            "part_number": _to_string(module.get("PartNumber")),
            "bank_label": _to_string(module.get("BankLabel")),
        }
        for module in module_records
    ]
    ram_info["memory_modules"] = modules
    ram_info["modules"] = modules
    ram_info["modules_count"] = len(modules)

    return ram_info


def _collect_disk_partitions() -> list[dict[str, object]]:
    partitions_info = []

    try:
        partitions = psutil.disk_partitions()
    except Exception:
        return partitions_info

    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            partitions_info.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "filesystem": partition.fstype,
                    "total_gb": _round_gb(usage.total),
                    "used_gb": _round_gb(usage.used),
                    "free_gb": _round_gb(usage.free),
                    "percent": _to_float(usage.percent),
                }
            )
        except Exception:
            continue

    return partitions_info


def _collect_physical_drives() -> list[dict[str, object]]:
    drive_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_DiskDrive | "
            "Select-Object Model, InterfaceType, MediaType, Size, Partitions, Status | "
            "ConvertTo-Json -Compress"
        )
    )

    return [
        {
            "model": _to_string(drive.get("Model")),
            "interface_type": _to_string(drive.get("InterfaceType")),
            "media_type": _to_string(drive.get("MediaType")),
            "size_gb": _round_gb(_to_int(drive.get("Size"))),
            "partitions": _to_int(drive.get("Partitions")),
            "status": _to_string(drive.get("Status")),
        }
        for drive in drive_records
    ]


def _collect_disk_health() -> list[dict[str, object]]:
    health_records = _normalize_records(
        _run_powershell_json(
            "Get-PhysicalDisk | "
            "Select-Object FriendlyName, MediaType, HealthStatus, OperationalStatus, Size | "
            "ConvertTo-Json -Compress -Depth 3"
        )
    )

    health_info = []
    for disk in health_records:
        operational_status = disk.get("OperationalStatus")
        if isinstance(operational_status, list):
            operational_status = ", ".join(
                str(value) for value in operational_status if value is not None
            )

        health_info.append(
            {
                "friendly_name": _to_string(disk.get("FriendlyName")),
                "media_type": _to_string(disk.get("MediaType")),
                "health_status": _to_string(disk.get("HealthStatus")),
                "operational_status": _to_string(operational_status),
                "size_gb": _round_gb(_to_int(disk.get("Size"))),
            }
        )

    return health_info


def _collect_disks_info() -> dict[str, object]:
    return {
        "partitions": _collect_disk_partitions(),
        "physical_drives": _collect_physical_drives(),
        "health": _collect_disk_health(),
    }


def _collect_gpu_counter_usage() -> float | None:
    output = _run_powershell(
        (
            "$samples = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage')."
            "CounterSamples; "
            "$sum = ($samples | Measure-Object -Property CookedValue -Sum).Sum; "
            "if ($null -eq $sum) { '' } "
            "else { [math]::Min(100, [math]::Round($sum, 2)) }"
        )
    )
    return _to_float(output)


def _collect_gpu_info() -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    wmi_gpu_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name, AdapterRAM, DriverVersion, VideoProcessor | "
            "ConvertTo-Json -Compress"
        )
    )

    nvidia_output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
            "--format=csv,noheader,nounits",
        ]
    )
    if nvidia_output:
        gpu_devices = []
        for line in nvidia_output.splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split(",")]
            adapter_ram_gb = None
            memory_total_mb = _to_int(parts[4] if len(parts) > 4 else None)
            if memory_total_mb is not None:
                adapter_ram_gb = round(memory_total_mb / 1024, 2)
            gpu_devices.append(
                {
                    "name": _to_string(parts[0] if len(parts) > 0 else None),
                    "driver_version": _to_string(parts[1] if len(parts) > 1 else None),
                    "usage_percent": _to_float(parts[2] if len(parts) > 2 else None),
                    "memory_used_mb": _to_int(parts[3] if len(parts) > 3 else None),
                    "memory_total_mb": memory_total_mb,
                    "temperature_celsius": _to_float(
                        parts[5] if len(parts) > 5 else None
                    ),
                    "power_draw_watts": _to_float(parts[6] if len(parts) > 6 else None),
                    "power_limit_watts": _to_float(
                        parts[7] if len(parts) > 7 else None
                    ),
                    "fan_speed_percent": _to_float(parts[8] if len(parts) > 8 else None),
                    "graphics_clock_mhz": _to_float(
                        parts[9] if len(parts) > 9 else None
                    ),
                    "memory_clock_mhz": _to_float(
                        parts[10] if len(parts) > 10 else None
                    ),
                    "adapter_ram_gb": adapter_ram_gb,
                    "video_processor": None,
                }
            )

        if gpu_devices:
            if wmi_gpu_records:
                wmi_first = wmi_gpu_records[0]
                if gpu_devices[0].get("adapter_ram_gb") is None:
                    adapter_ram_bytes = _to_int(wmi_first.get("AdapterRAM"))
                    if adapter_ram_bytes is not None:
                        gpu_devices[0]["adapter_ram_gb"] = round(
                            adapter_ram_bytes / (1024**3), 2
                        )
                if gpu_devices[0].get("driver_version") is None:
                    gpu_devices[0]["driver_version"] = _to_string(
                        wmi_first.get("DriverVersion")
                    )
            return gpu_devices[0], gpu_devices

    if not wmi_gpu_records:
        return None, []

    gpu_counter_usage = _collect_gpu_counter_usage()
    gpu_devices = []
    for index, gpu in enumerate(wmi_gpu_records):
        adapter_ram_bytes = _to_int(gpu.get("AdapterRAM"))
        gpu_devices.append(
            {
                "name": _to_string(gpu.get("Name")),
                "driver_version": _to_string(gpu.get("DriverVersion")),
                "usage_percent": gpu_counter_usage if index == 0 else None,
                "memory_used_mb": None,
                "memory_total_mb": _to_int(
                    round(adapter_ram_bytes / (1024**2), 2)
                    if adapter_ram_bytes is not None
                    else None
                ),
                "temperature_celsius": None,
                "power_draw_watts": None,
                "power_limit_watts": None,
                "fan_speed_percent": None,
                "graphics_clock_mhz": None,
                "memory_clock_mhz": None,
                "adapter_ram_gb": (
                    round(adapter_ram_bytes / (1024**3), 2)
                    if adapter_ram_bytes is not None
                    else None
                ),
                "video_processor": _to_string(gpu.get("VideoProcessor")),
            }
        )

    return gpu_devices[0], gpu_devices


def _collect_motherboard_info() -> dict[str, str | None]:
    motherboard_info = {
        "manufacturer": None,
        "model": None,
        "product": None,
        "version": None,
        "bios_manufacturer": None,
        "bios_version": None,
        "release_date": None,
    }

    board_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_BaseBoard | "
            "Select-Object -First 1 Manufacturer, Product, Version | "
            "ConvertTo-Json -Compress"
        )
    )
    if board_records:
        motherboard_info["manufacturer"] = _to_string(
            board_records[0].get("Manufacturer")
        )
        motherboard_info["product"] = _to_string(board_records[0].get("Product"))
        motherboard_info["model"] = motherboard_info["product"]
        motherboard_info["version"] = _to_string(board_records[0].get("Version"))

    bios_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_BIOS | "
            "Select-Object -First 1 Manufacturer, SMBIOSBIOSVersion, ReleaseDate | "
            "ConvertTo-Json -Compress"
        )
    )
    if bios_records:
        motherboard_info["bios_manufacturer"] = _to_string(
            bios_records[0].get("Manufacturer")
        )
        motherboard_info["bios_version"] = _to_string(
            bios_records[0].get("SMBIOSBIOSVersion")
        )
        motherboard_info["release_date"] = _format_cim_datetime(
            bios_records[0].get("ReleaseDate")
        )

    return motherboard_info


def _collect_bios_info() -> dict[str, str | None]:
    bios_info = {
        "manufacturer": None,
        "version": None,
        "release_date": None,
    }

    bios_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_BIOS | "
            "Select-Object -First 1 Manufacturer, SMBIOSBIOSVersion, ReleaseDate | "
            "ConvertTo-Json -Compress"
        )
    )
    if bios_records:
        bios_info["manufacturer"] = _to_string(bios_records[0].get("Manufacturer"))
        bios_info["version"] = _to_string(bios_records[0].get("SMBIOSBIOSVersion"))
        bios_info["release_date"] = _format_cim_datetime(
            bios_records[0].get("ReleaseDate")
        )

    return bios_info


def _collect_os_info() -> dict[str, str | None]:
    os_info = {
        "name": None,
        "caption": None,
        "version": None,
        "architecture": None,
    }

    os_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object -First 1 Caption, Version, OSArchitecture | "
            "ConvertTo-Json -Compress"
        )
    )
    if os_records:
        caption = _to_string(os_records[0].get("Caption"))
        os_info["caption"] = caption
        os_info["name"] = caption
        os_info["version"] = _to_string(os_records[0].get("Version"))
        os_info["architecture"] = _to_string(os_records[0].get("OSArchitecture"))

    return os_info


def _collect_cooling_info() -> dict[str, list[dict[str, object]]]:
    fan_records = _normalize_records(
        _run_powershell_json(
            "Get-CimInstance Win32_Fan | "
            "Select-Object Name, Status, DesiredSpeed, VariableSpeed | "
            "ConvertTo-Json -Compress"
        )
    )

    return {
        "fans": [
            {
                "name": _to_string(fan.get("Name")),
                "status": _to_string(fan.get("Status")),
                "desired_speed": _to_int(fan.get("DesiredSpeed")),
                "variable_speed": fan.get("VariableSpeed"),
            }
            for fan in fan_records
        ]
    }


def _collect_temperatures_info() -> dict[str, list[dict[str, object]]]:
    sensor_records = _normalize_records(
        _run_powershell_json(
            "Get-WmiObject -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature | "
            "Select-Object InstanceName, CurrentTemperature | "
            "ConvertTo-Json -Compress"
        )
    )

    sensors = []
    for sensor in sensor_records:
        current_temperature = _to_float(sensor.get("CurrentTemperature"))
        if current_temperature is None:
            continue

        temperature_celsius = round((current_temperature / 10) - 273.15, 2)
        if temperature_celsius < -50 or temperature_celsius > 200:
            continue

        sensors.append(
            {
                "name": _to_string(sensor.get("InstanceName")),
                "temperature_celsius": temperature_celsius,
            }
        )

    return {"sensors": sensors}


def _collect_battery_info() -> dict[str, object] | None:
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return None

    if battery is None:
        return None

    seconds_left = battery.secsleft
    if isinstance(seconds_left, (int, float)) and seconds_left < 0:
        seconds_left = None

    return {
        "percent": _to_float(battery.percent),
        "plugged": battery.power_plugged,
        "seconds_left": seconds_left,
    }


def _collect_platform_info() -> dict[str, str | None]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "python_version": platform.python_version() if sys.version_info else None,
        "hostname": platform.node() or None,
    }


def collect_system_info() -> dict[str, object]:
    gpu, gpu_devices = _collect_gpu_info()
    motherboard_info = _collect_motherboard_info()
    bios_info = _collect_bios_info()
    os_info = _collect_os_info()
    ram_info = _collect_ram_info()

    return {
        "cpu": _collect_cpu_info(),
        "ram": ram_info,
        "disks": _collect_disks_info(),
        "gpu": gpu,
        "gpu_devices": gpu_devices,
        "motherboard": motherboard_info,
        "bios": bios_info,
        "os": os_info,
        "cooling": _collect_cooling_info(),
        "temperatures": _collect_temperatures_info(),
        "battery": _collect_battery_info(),
        "platform": _collect_platform_info(),
    }
