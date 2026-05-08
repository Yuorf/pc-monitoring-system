import json
import subprocess


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


def _normalize_records(data: object) -> list[dict[str, object]]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _empty_sensor_payload() -> dict[str, object]:
    return {
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "powers": [],
        "clocks": [],
        "loads": [],
        "controls": [],
        "data": [],
        "sources": {
            "libre_hardware_monitor": False,
            "open_hardware_monitor": False,
            "wmi_thermal_zone": False,
            "nvidia_smi": False,
        },
    }


def _classify_component(*values: object) -> str:
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    if "cpu" in haystack:
        return "CPU"
    if "gpu" in haystack or "video" in haystack or "nvidia" in haystack:
        return "GPU"
    if "hdd" in haystack or "ssd" in haystack or "nvme" in haystack or "disk" in haystack:
        return "Disk"
    if "ram" in haystack or "memory" in haystack:
        return "RAM"
    if "motherboard" in haystack or "mainboard" in haystack or "board" in haystack:
        return "Motherboard"
    return "Unknown"


def _sensor_bucket(sensor_type: str | None) -> tuple[str, str, str] | None:
    mapping = {
        "temperature": ("temperatures", "°C", "temperature"),
        "fan": ("fans", "RPM", "fan"),
        "voltage": ("voltages", "V", "voltage"),
        "power": ("powers", "W", "power"),
        "clock": ("clocks", "MHz", "clock"),
        "load": ("loads", "%", "load"),
        "control": ("controls", "%", "control"),
        "data": ("data", "", "data"),
    }
    if sensor_type is None:
        return None
    return mapping.get(sensor_type.strip().lower())


def _append_sensor(
    container: dict[str, object],
    bucket: str,
    source: str,
    component: str,
    name: str | None,
    value: object,
    unit: str,
    sensor_type: str,
) -> None:
    numeric_value = _to_float(value)
    if numeric_value is None:
        return

    sensor = {
        "source": source,
        "component": component,
        "name": name or "Unknown Sensor",
        "value": numeric_value,
        "unit": unit,
        "sensor_type": sensor_type,
    }
    container[bucket].append(sensor)


def _collect_wmi_sensor_namespace(
    namespace: str,
    source_name: str,
) -> tuple[dict[str, list[dict[str, object]]], bool]:
    result = {
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "powers": [],
        "clocks": [],
        "loads": [],
        "controls": [],
        "data": [],
    }

    records = _normalize_records(
        _run_powershell_json(
            f"Get-WmiObject -Namespace {namespace} -Class Sensor | "
            "Select-Object Name, SensorType, Value, Identifier, Parent | "
            "ConvertTo-Json -Compress -Depth 3"
        )
    )
    if not records:
        return result, False

    has_data = False
    for record in records:
        mapping = _sensor_bucket(_to_string(record.get("SensorType")))
        if mapping is None:
            continue

        bucket, unit, sensor_type = mapping
        component = _classify_component(
            record.get("Identifier"),
            record.get("Parent"),
            record.get("Name"),
        )
        before_count = len(result[bucket])
        _append_sensor(
            result,
            bucket,
            source_name,
            component,
            _to_string(record.get("Name")),
            record.get("Value"),
            unit,
            sensor_type,
        )
        if len(result[bucket]) > before_count:
            has_data = True

    return result, has_data


def _collect_wmi_thermal_zone() -> tuple[list[dict[str, object]], bool]:
    sensors = []
    records = _normalize_records(
        _run_powershell_json(
            "Get-WmiObject -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature | "
            "Select-Object InstanceName, CurrentTemperature | "
            "ConvertTo-Json -Compress"
        )
    )

    for record in records:
        current_temperature = _to_float(record.get("CurrentTemperature"))
        if current_temperature is None:
            continue

        temperature_celsius = round((current_temperature / 10) - 273.15, 2)
        if temperature_celsius < -50 or temperature_celsius > 200:
            continue

        sensors.append(
            {
                "source": "WMI ThermalZone",
                "component": "System",
                "name": _to_string(record.get("InstanceName")) or "Thermal Zone",
                "value": temperature_celsius,
                "unit": "°C",
                "sensor_type": "temperature",
            }
        )

    return sensors, bool(sensors)


def _collect_nvidia_smi_sensors() -> tuple[dict[str, list[dict[str, object]]], bool]:
    result = {
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "powers": [],
        "clocks": [],
        "loads": [],
        "controls": [],
        "data": [],
    }

    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return result, False

    has_data = False
    for line in output.splitlines():
        if not line.strip():
            continue

        parts = [part.strip() for part in line.split(",")]
        name = _to_string(parts[0] if len(parts) > 0 else None) or "GPU"

        sensor_definitions = [
            (
                "temperatures",
                "GPU",
                f"{name} Temperature",
                parts[4] if len(parts) > 4 else None,
                "°C",
                "temperature",
            ),
            (
                "loads",
                "GPU",
                f"{name} Utilization",
                parts[1] if len(parts) > 1 else None,
                "%",
                "load",
            ),
            (
                "data",
                "GPU",
                f"{name} Memory Used",
                parts[2] if len(parts) > 2 else None,
                "MB",
                "data",
            ),
            (
                "data",
                "GPU",
                f"{name} Memory Total",
                parts[3] if len(parts) > 3 else None,
                "MB",
                "data",
            ),
            (
                "powers",
                "GPU",
                f"{name} Power Draw",
                parts[5] if len(parts) > 5 else None,
                "W",
                "power",
            ),
            (
                "powers",
                "GPU",
                f"{name} Power Limit",
                parts[6] if len(parts) > 6 else None,
                "W",
                "power",
            ),
            (
                "fans",
                "GPU",
                f"{name} Fan Speed",
                parts[7] if len(parts) > 7 else None,
                "%",
                "fan",
            ),
            (
                "clocks",
                "GPU",
                f"{name} Graphics Clock",
                parts[8] if len(parts) > 8 else None,
                "MHz",
                "clock",
            ),
            (
                "clocks",
                "GPU",
                f"{name} Memory Clock",
                parts[9] if len(parts) > 9 else None,
                "MHz",
                "clock",
            ),
        ]

        for bucket, component, sensor_name, value, unit, sensor_type in sensor_definitions:
            before_count = len(result[bucket])
            _append_sensor(
                result,
                bucket,
                "nvidia-smi",
                component,
                sensor_name,
                value,
                unit,
                sensor_type,
            )
            if len(result[bucket]) > before_count:
                has_data = True

    return result, has_data


def _merge_sensor_lists(
    *sources: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    merged = {
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "powers": [],
        "clocks": [],
        "loads": [],
        "controls": [],
        "data": [],
    }

    for source in sources:
        for key in merged:
            merged[key].extend(source.get(key, []))

    return merged


def collect_hardware_sensors() -> dict[str, object]:
    payload = _empty_sensor_payload()

    libre_data, libre_available = _collect_wmi_sensor_namespace(
        "root\\LibreHardwareMonitor",
        "LibreHardwareMonitor",
    )
    open_data, open_available = _collect_wmi_sensor_namespace(
        "root\\OpenHardwareMonitor",
        "OpenHardwareMonitor",
    )
    thermal_sensors, thermal_available = _collect_wmi_thermal_zone()
    nvidia_data, nvidia_available = _collect_nvidia_smi_sensors()

    merged = _merge_sensor_lists(libre_data, open_data, nvidia_data)
    merged["temperatures"].extend(thermal_sensors)

    for key in (
        "temperatures",
        "fans",
        "voltages",
        "powers",
        "clocks",
        "loads",
        "controls",
        "data",
    ):
        payload[key] = merged[key]

    payload["sources"] = {
        "libre_hardware_monitor": libre_available,
        "open_hardware_monitor": open_available,
        "wmi_thermal_zone": thermal_available,
        "nvidia_smi": nvidia_available,
    }

    return payload
