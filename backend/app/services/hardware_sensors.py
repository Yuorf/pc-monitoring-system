import json
import re
import subprocess
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen


NOISE_NAME_PARTS = (
    "resolution",
    "low limit",
    "high limit",
    "critical",
    "threshold",
    "trfc",
    "tckavg",
    "taa",
    "trcd",
    "trp",
    "tras",
    "trc",
    "twr",
    "fullscreen fps",
)


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
            "libre_hardware_monitor_web": False,
            "open_hardware_monitor": False,
            "wmi_thermal_zone": False,
            "nvidia_smi": False,
        },
    }


def _classify_component(*values: object) -> str:
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    if "/amdcpu" in haystack or " cpu" in f" {haystack}" or "cpu/" in haystack:
        return "CPU"
    if (
        "/gpu-nvidia" in haystack
        or "/gpu-amd" in haystack
        or "gpu" in haystack
        or "nvidia" in haystack
        or "radeon" in haystack
        or "video" in haystack
    ):
        return "GPU"
    if (
        "/memory" in haystack
        or "/ram" in haystack
        or "dimm" in haystack
        or " memory" in f" {haystack}"
    ):
        return "RAM"
    if (
        "/nvme" in haystack
        or "/hdd" in haystack
        or "disk" in haystack
        or "ssd" in haystack
        or "storage" in haystack
    ):
        return "Disk"
    if (
        "/lpc" in haystack
        or "motherboard" in haystack
        or "mainboard" in haystack
        or " board" in f" {haystack}"
        or "nct" in haystack
    ):
        return "Motherboard"
    if (
        "/nic" in haystack
        or "network" in haystack
        or "ethernet" in haystack
        or "wifi" in haystack
    ):
        return "Network"
    return "Unknown"


def _sensor_bucket(sensor_type: str | None) -> tuple[str, str | None, str] | None:
    mapping = {
        "temperature": ("temperatures", "°C", "temperature"),
        "fan": ("fans", "RPM", "fan"),
        "voltage": ("voltages", "V", "voltage"),
        "power": ("powers", "W", "power"),
        "clock": ("clocks", "MHz", "clock"),
        "load": ("loads", "%", "load"),
        "control": ("controls", "%", "control"),
        "data": ("data", None, "data"),
        "smalldata": ("data", None, "smalldata"),
        "level": ("data", None, "level"),
        "factor": ("data", None, "factor"),
        "throughput": ("data", None, "throughput"),
        "timing": ("data", None, "timing"),
    }
    if sensor_type is None:
        return None
    return mapping.get(sensor_type.strip().lower())


def _extract_numeric_value(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)

    value_str = _to_string(value)
    if value_str is None:
        return None

    normalized = value_str.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def _sanitize_unit(unit: str | None) -> str:
    unit_value = _to_string(unit) or ""
    if unit_value.startswith("."):
        return ""
    return unit_value


def _infer_unit_from_value(value: object, raw_value: object | None = None) -> str:
    candidates = [_to_string(value), _to_string(raw_value)]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?\s*([^\d\s].*)$", normalized)
        if match:
            return _sanitize_unit(match.group(1).strip())
    return ""


def _is_noise_sensor(name: str | None, sensor_type: str, value: object) -> bool:
    name_value = (name or "").lower()
    if any(part in name_value for part in NOISE_NAME_PARTS):
        return True

    numeric_value = _extract_numeric_value(value)
    if numeric_value is None:
        return False

    if sensor_type == "temperature" and numeric_value == 0:
        return True
    if sensor_type == "fan" and numeric_value == 0:
        return True
    if sensor_type == "factor" and numeric_value < 0:
        return True
    if sensor_type == "load" and (numeric_value < 0 or numeric_value > 1000):
        return True

    return False


def _append_sensor(
    container: dict[str, object],
    bucket: str,
    source: str,
    component: str,
    name: str | None,
    value: object,
    unit: str | None,
    sensor_type: str,
    raw_value: object | None = None,
    sensor_id: str | None = None,
    hardware_id: str | None = None,
) -> None:
    numeric_value = _extract_numeric_value(value)
    if numeric_value is None:
        numeric_value = _extract_numeric_value(raw_value)
    if numeric_value is None:
        return

    if _is_noise_sensor(name, sensor_type, numeric_value):
        return

    final_unit = _sanitize_unit(unit if unit is not None else _infer_unit_from_value(value, raw_value))
    sensor = {
        "source": source,
        "component": component,
        "name": name or "Unknown Sensor",
        "value": numeric_value,
        "unit": final_unit,
        "sensor_type": sensor_type,
    }
    if sensor_id is not None:
        sensor["sensor_id"] = sensor_id
    if hardware_id is not None:
        sensor["hardware_id"] = hardware_id
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


def _collect_libre_hardware_monitor_web() -> tuple[dict[str, list[dict[str, object]]], bool]:
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

    try:
        with urlopen("http://localhost:8085/data.json", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return result, False
    except Exception:
        return result, False

    has_data = False

    def walk(node: object, path: list[str], hardware_id: str | None = None) -> None:
        nonlocal has_data
        if not isinstance(node, dict):
            return

        node_text = _to_string(node.get("Text"))
        current_path = path + ([node_text] if node_text else [])
        current_hardware_id = _to_string(node.get("HardwareId")) or hardware_id

        if node.get("SensorId") is not None:
            mapping = _sensor_bucket(_to_string(node.get("Type")))
            if mapping is not None:
                bucket, unit, sensor_type = mapping
                component = _classify_component(
                    node.get("SensorId"),
                    current_hardware_id,
                    node.get("Text"),
                    " / ".join(current_path),
                )
                before_count = len(result[bucket])
                _append_sensor(
                    result,
                    bucket,
                    "LibreHardwareMonitor Web",
                    component,
                    node_text,
                    node.get("Value"),
                    unit,
                    sensor_type,
                    raw_value=node.get("RawValue"),
                    sensor_id=_to_string(node.get("SensorId")),
                    hardware_id=current_hardware_id,
                )
                if len(result[bucket]) > before_count:
                    has_data = True

        for child in node.get("Children", []):
            walk(child, current_path, current_hardware_id)

    walk(payload, [])
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


def _deduplicate_sensors(container: dict[str, object]) -> dict[str, object]:
    for bucket in (
        "temperatures",
        "fans",
        "voltages",
        "powers",
        "clocks",
        "loads",
        "controls",
        "data",
    ):
        seen = set()
        unique_sensors = []
        for sensor in container.get(bucket, []):
            sensor_id = _to_string(sensor.get("sensor_id"))
            hardware_id = _to_string(sensor.get("hardware_id"))
            if sensor_id is not None:
                key = (
                    sensor.get("source"),
                    sensor_id,
                )
            else:
                key = (
                    sensor.get("source"),
                    sensor.get("component"),
                    hardware_id,
                    sensor.get("name"),
                    sensor.get("sensor_type"),
                    sensor.get("unit", ""),
                )
            if key in seen:
                continue
            seen.add(key)
            unique_sensors.append(sensor)
        container[bucket] = unique_sensors

    return container


def _sensor_text(sensor: dict[str, object]) -> str:
    return " ".join(
        str(value).lower()
        for value in (sensor.get("component"), sensor.get("name"), sensor.get("source"))
        if value is not None
    )


def _sensor_name(sensor: dict[str, object]) -> str:
    return str(sensor.get("name", "")).lower()


def _match_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _collect_metric_sensors(
    sensor_payload: dict[str, object],
    bucket: str,
    *,
    component: str | None = None,
    include_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    sensors = sensor_payload.get(bucket, [])
    if not isinstance(sensors, list):
        return []

    matched = []
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue

        text = _sensor_text(sensor)
        if component and str(sensor.get("component")).lower() != component.lower():
            continue
        if include_keywords and not _match_keywords(text, include_keywords):
            continue
        if exclude_keywords and _match_keywords(text, exclude_keywords):
            continue
        if _to_float(sensor.get("value")) is None:
            continue
        matched.append(sensor)

    return matched


def _metric_values(sensors: list[dict[str, object]]) -> list[float]:
    values = []
    for sensor in sensors:
        value = _to_float(sensor.get("value"))
        if value is not None:
            values.append(value)
    return values


def _round_metric(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _average_value(sensors: list[dict[str, object]]) -> float | None:
    values = _metric_values(sensors)
    if not values:
        return None
    return sum(values) / len(values)


def _max_value(sensors: list[dict[str, object]]) -> float | None:
    values = _metric_values(sensors)
    if not values:
        return None
    return max(values)


def _min_value(sensors: list[dict[str, object]]) -> float | None:
    values = _metric_values(sensors)
    if not values:
        return None
    return min(values)


def _filter_sensors_by_name(
    sensors: list[dict[str, object]],
    *,
    include_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    matched = []
    for sensor in sensors:
        name = _sensor_name(sensor)
        if include_keywords and not _match_keywords(name, include_keywords):
            continue
        if exclude_keywords and _match_keywords(name, exclude_keywords):
            continue
        matched.append(sensor)
    return matched


def _pick_preferred_value_by_name(
    sensors: list[dict[str, object]],
    *,
    exact_names: tuple[str, ...] = (),
    contains_names: tuple[str, ...] = (),
    all_keyword_groups: tuple[tuple[str, ...], ...] = (),
    fallback: str = "max",
) -> float | None:
    for exact_name in exact_names:
        exact_matches = [
            sensor for sensor in sensors if _sensor_name(sensor) == exact_name
        ]
        if exact_matches:
            return _pick_preferred_value(exact_matches, fallback=fallback)

    for contains_name in contains_names:
        contains_matches = [
            sensor for sensor in sensors if contains_name in _sensor_name(sensor)
        ]
        if contains_matches:
            return _pick_preferred_value(contains_matches, fallback=fallback)

    for keyword_group in all_keyword_groups:
        grouped_matches = [
            sensor
            for sensor in sensors
            if all(keyword in _sensor_name(sensor) for keyword in keyword_group)
        ]
        if grouped_matches:
            return _pick_preferred_value(grouped_matches, fallback=fallback)

    return _pick_preferred_value(sensors, fallback=fallback)


def _pick_preferred_value(
    sensors: list[dict[str, object]],
    *,
    preferred_keywords: tuple[str, ...] = (),
    fallback: str = "max",
) -> float | None:
    candidates = sensors
    if preferred_keywords:
        preferred = [
            sensor
            for sensor in sensors
            if _match_keywords(_sensor_text(sensor), preferred_keywords)
        ]
        if preferred:
            candidates = preferred

    if fallback == "avg":
        return _average_value(candidates)
    if fallback == "min":
        return _min_value(candidates)
    return _max_value(candidates)


def _extract_disk_life(sensor_payload: dict[str, object]) -> float | None:
    disk_data = _collect_metric_sensors(sensor_payload, "data", component="Disk")
    life_values = []

    for sensor in disk_data:
        name = str(sensor.get("name", "")).lower()
        value = _to_float(sensor.get("value"))
        if value is None:
            continue

        if any(keyword in name for keyword in ("remaining life", "life left", "wear level", "health")):
            life_values.append(value)
            continue

        if "percentage used" in name:
            life_values.append(max(0.0, 100.0 - value))

    if not life_values:
        return None
    return min(life_values)


def _extract_disk_power_on_hours(sensor_payload: dict[str, object]) -> int | None:
    disk_data = _collect_metric_sensors(sensor_payload, "data", component="Disk")
    disk_data = _filter_sensors_by_name(
        disk_data,
        include_keywords=("power on hours", "power-on hours"),
    )
    values = _metric_values(disk_data)
    if not values:
        return None
    return int(round(max(values)))


def extract_key_metrics(sensor_payload: dict[str, object]) -> dict[str, object]:
    cpu_temperatures = _collect_metric_sensors(sensor_payload, "temperatures", component="CPU")
    gpu_temperatures = _collect_metric_sensors(sensor_payload, "temperatures", component="GPU")
    ram_temperatures = _collect_metric_sensors(sensor_payload, "temperatures", component="RAM")
    disk_temperatures = _collect_metric_sensors(sensor_payload, "temperatures", component="Disk")
    cpu_powers = _collect_metric_sensors(sensor_payload, "powers", component="CPU")
    gpu_powers = _collect_metric_sensors(sensor_payload, "powers", component="GPU")

    system_fans = _collect_metric_sensors(
        sensor_payload,
        "fans",
        include_keywords=("system", "sys", "chassis", "case"),
        exclude_keywords=("cpu", "gpu", "pump"),
    )
    if not system_fans:
        system_fans = _collect_metric_sensors(
            sensor_payload,
            "fans",
            component="Motherboard",
            exclude_keywords=("cpu", "gpu", "pump"),
        )
    disk_temperatures = _filter_sensors_by_name(
        disk_temperatures,
        exclude_keywords=("warning", "critical", "threshold", "limit"),
    )
    gpu_powers = _filter_sensors_by_name(
        gpu_powers,
        exclude_keywords=("power limit", "limit", "tdp"),
    )

    return {
        "timestamp": datetime.utcnow(),
        "cpu_temperature": _round_metric(
            _pick_preferred_value_by_name(
                cpu_temperatures,
                contains_names=("core (tctl/tdie)", "cpu socket", "ccd1"),
                exact_names=("cpu",),
                fallback="max",
            )
        ),
        "gpu_temperature": _round_metric(
            _pick_preferred_value_by_name(
                gpu_temperatures,
                contains_names=("gpu core",),
                all_keyword_groups=(("nvidia", "temperature"),),
                fallback="max",
            )
        ),
        "ram_temperature": _round_metric(_average_value(ram_temperatures)),
        "disk_temperature": _round_metric(_max_value(disk_temperatures)),
        "cpu_power": _round_metric(
            _pick_preferred_value(
                cpu_powers,
                preferred_keywords=("package", "total", "ppt"),
                fallback="max",
            )
        ),
        "gpu_power": _round_metric(
            _pick_preferred_value_by_name(
                gpu_powers,
                contains_names=("power draw", "gpu package", "gpu core"),
                fallback="max",
            )
        ),
        "system_fan_rpm": _round_metric(_average_value(system_fans)),
        "disk_life": _round_metric(_extract_disk_life(sensor_payload)),
        "disk_power_on_hours": _extract_disk_power_on_hours(sensor_payload),
    }


def collect_hardware_sensors() -> dict[str, object]:
    payload = _empty_sensor_payload()

    libre_data, libre_available = _collect_wmi_sensor_namespace(
        "root\\LibreHardwareMonitor",
        "LibreHardwareMonitor",
    )
    libre_web_data, libre_web_available = _collect_libre_hardware_monitor_web()
    open_data, open_available = _collect_wmi_sensor_namespace(
        "root\\OpenHardwareMonitor",
        "OpenHardwareMonitor",
    )
    thermal_sensors, thermal_available = _collect_wmi_thermal_zone()
    nvidia_data, nvidia_available = _collect_nvidia_smi_sensors()

    merged = _merge_sensor_lists(
        libre_data,
        libre_web_data,
        open_data,
        nvidia_data,
    )
    merged["temperatures"].extend(thermal_sensors)
    merged = _deduplicate_sensors(merged)

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
        "libre_hardware_monitor_web": libre_web_available,
        "open_hardware_monitor": open_available,
        "wmi_thermal_zone": thermal_available,
        "nvidia_smi": nvidia_available,
    }

    return payload
