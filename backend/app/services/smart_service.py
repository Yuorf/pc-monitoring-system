import json
import re
import subprocess
from urllib.error import URLError
from urllib.request import urlopen


SOURCE_NAMES = (
    "windows_physical_disk",
    "windows_reliability_counter",
    "libre_hardware_monitor",
    "smartctl",
)

DRIVE_FIELDS = (
    "name",
    "model",
    "serial",
    "interface",
    "media_type",
    "size_gb",
    "health_status",
    "temperature_celsius",
    "power_on_hours",
    "power_cycle_count",
    "life_percent",
    "percentage_used",
    "available_spare",
    "available_spare_threshold",
    "reallocated_sectors_count",
    "current_pending_sector_count",
    "offline_uncorrectable",
    "reported_uncorrectable_errors",
    "unsafe_shutdowns",
    "media_errors",
    "data_read_gb",
    "data_written_gb",
)


def _to_string(value: object) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


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


def _to_float(value: object) -> float | None:
    numeric_value = _extract_numeric_value(value)
    if numeric_value is None:
        return None
    return float(numeric_value)


def _to_int(value: object) -> int | None:
    numeric_value = _extract_numeric_value(value)
    if numeric_value is None:
        return None
    return int(round(numeric_value))


def _round_gb(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _run_command(command: list[str], timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None

    output = result.stdout.strip()
    if output:
        return output

    error_output = result.stderr.strip()
    if error_output.startswith("{") or error_output.startswith("["):
        return error_output
    return None


def _run_powershell(command: str, timeout: int = 10) -> str | None:
    return _run_command(
        ["powershell", "-NoProfile", "-Command", command],
        timeout=timeout,
    )


def _run_powershell_json(command: str, timeout: int = 10) -> object | None:
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


def _empty_drive() -> dict[str, object]:
    return {
        "name": None,
        "model": None,
        "serial": None,
        "interface": None,
        "media_type": None,
        "size_gb": None,
        "health_status": None,
        "temperature_celsius": None,
        "power_on_hours": None,
        "power_cycle_count": None,
        "life_percent": None,
        "percentage_used": None,
        "available_spare": None,
        "available_spare_threshold": None,
        "reallocated_sectors_count": None,
        "current_pending_sector_count": None,
        "offline_uncorrectable": None,
        "reported_uncorrectable_errors": None,
        "unsafe_shutdowns": None,
        "media_errors": None,
        "data_read_gb": None,
        "data_written_gb": None,
        "raw": {source_name: {} for source_name in SOURCE_NAMES},
    }


def _normalize_text(value: object) -> str | None:
    text = _to_string(value)
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip().lower()


def _combine_health_status(*values: object) -> str | None:
    normalized_values = []
    for value in values:
        text = _to_string(value)
        if text and text not in normalized_values:
            normalized_values.append(text)
    if not normalized_values:
        return None
    if len(normalized_values) == 1:
        return normalized_values[0]
    return " / ".join(normalized_values)


def _infer_media_type(*values: object) -> str | None:
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    if "nvme" in haystack:
        return "NVMe"
    if "ssd" in haystack or "solid state" in haystack:
        return "SSD"
    if "hdd" in haystack or "hard disk" in haystack:
        return "HDD"
    return None


def _infer_interface(*values: object) -> str | None:
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    if "nvme" in haystack:
        return "NVMe"
    if "usb" in haystack:
        return "USB"
    if "sas" in haystack:
        return "SAS"
    if "sata" in haystack or "ata" in haystack or "ahci" in haystack or "sat" in haystack:
        return "SATA"
    if "scsi" in haystack:
        return "SCSI"
    return None


def _looks_like_disk(*values: object) -> bool:
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    return any(
        token in haystack
        for token in (
            "/nvme",
            "/hdd",
            "/ssd",
            "/storage",
            "physicaldisk",
            " disk",
            " nvme",
            " ssd",
            " hdd",
            "solid state",
        )
    )


def _round_size_gb_from_bytes(value: object) -> float | None:
    size_bytes = _to_float(value)
    if size_bytes is None:
        return None
    return _round_gb(size_bytes / (1024 ** 3))


def _value_to_gb(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return _round_gb(float(value) / (1024 ** 3))

    value_str = _to_string(value)
    if value_str is None:
        return None

    numeric_value = _to_float(value_str)
    if numeric_value is None:
        return None

    normalized = value_str.lower()
    if "tb" in normalized:
        return _round_gb(numeric_value * 1024)
    if "gb" in normalized:
        return _round_gb(numeric_value)
    if "mb" in normalized:
        return _round_gb(numeric_value / 1024)
    if "kb" in normalized:
        return _round_gb(numeric_value / (1024 ** 2))
    if "bytes" in normalized or "byte" in normalized or normalized.endswith("b"):
        return _round_gb(numeric_value / (1024 ** 3))
    return _round_gb(numeric_value)


def _set_if_present(drive: dict[str, object], field: str, value: object) -> None:
    if value is not None:
        drive[field] = value


def _attribute_raw_int(attribute: dict[str, object]) -> int | None:
    raw = attribute.get("raw")
    if isinstance(raw, dict):
        value = _to_int(raw.get("value"))
        if value is not None:
            return value
        return _to_int(raw.get("string"))
    return _to_int(raw)


def _find_ata_attribute(
    table: list[dict[str, object]],
    *,
    names: tuple[str, ...] = (),
    ids: tuple[int, ...] = (),
) -> int | None:
    normalized_names = {name.lower() for name in names}
    for attribute in table:
        if not isinstance(attribute, dict):
            continue
        attribute_name = _normalize_text(attribute.get("name"))
        attribute_id = _to_int(attribute.get("id"))
        if attribute_name in normalized_names or (
            attribute_id is not None and attribute_id in ids
        ):
            return _attribute_raw_int(attribute)
    return None


def _make_drive_key(value: object) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    return normalized


def _find_merge_candidate(
    drives: list[dict[str, object]],
    incoming_drive: dict[str, object],
) -> dict[str, object] | None:
    incoming_serial = _make_drive_key(incoming_drive.get("serial"))
    if incoming_serial is not None:
        for existing_drive in drives:
            if incoming_serial == _make_drive_key(existing_drive.get("serial")):
                return existing_drive

    incoming_name = _make_drive_key(incoming_drive.get("name"))
    incoming_model = _make_drive_key(incoming_drive.get("model"))

    exact_candidates = []
    if incoming_name and incoming_model:
        for existing_drive in drives:
            if (
                incoming_name == _make_drive_key(existing_drive.get("name"))
                and incoming_model == _make_drive_key(existing_drive.get("model"))
            ):
                exact_candidates.append(existing_drive)
        if len(exact_candidates) == 1:
            return exact_candidates[0]

    name_candidates = []
    if incoming_name:
        for existing_drive in drives:
            existing_name = _make_drive_key(existing_drive.get("name"))
            existing_model = _make_drive_key(existing_drive.get("model"))
            if existing_name != incoming_name:
                continue
            if incoming_model and existing_model and incoming_model != existing_model:
                continue
            name_candidates.append(existing_drive)
        if len(name_candidates) == 1:
            return name_candidates[0]

    return None


def _merge_drive_data(
    target_drive: dict[str, object],
    source_drive: dict[str, object],
) -> None:
    for field in DRIVE_FIELDS:
        value = source_drive.get(field)
        if value is not None:
            target_drive[field] = value

    target_raw = target_drive.get("raw")
    source_raw = source_drive.get("raw")
    if isinstance(target_raw, dict) and isinstance(source_raw, dict):
        for source_name in SOURCE_NAMES:
            raw_value = source_raw.get(source_name)
            if raw_value:
                target_raw[source_name] = raw_value


def _collect_windows_physical_disk() -> tuple[list[dict[str, object]], bool]:
    records = _normalize_records(
        _run_powershell_json(
            "Get-PhysicalDisk | "
            "Select-Object FriendlyName, SerialNumber, MediaType, HealthStatus, OperationalStatus, Size, BusType | "
            "ConvertTo-Json -Compress -Depth 4",
        )
    )

    drives = []
    for record in records:
        drive = _empty_drive()
        friendly_name = _to_string(record.get("FriendlyName"))
        _set_if_present(drive, "name", friendly_name)
        _set_if_present(drive, "model", friendly_name)
        _set_if_present(drive, "serial", _to_string(record.get("SerialNumber")))
        _set_if_present(drive, "interface", _to_string(record.get("BusType")))
        _set_if_present(drive, "media_type", _to_string(record.get("MediaType")))
        _set_if_present(drive, "size_gb", _round_size_gb_from_bytes(record.get("Size")))
        _set_if_present(
            drive,
            "health_status",
            _combine_health_status(
                record.get("HealthStatus"),
                record.get("OperationalStatus"),
            ),
        )
        drive["raw"]["windows_physical_disk"] = record
        drives.append(drive)

    return drives, bool(drives)


def _collect_windows_reliability_counter() -> tuple[list[dict[str, object]], bool]:
    command = (
        "$disks = Get-PhysicalDisk; "
        "$items = foreach ($disk in $disks) { "
        "  $counter = $null; "
        "  try { $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop } catch {} "
        "  [pscustomobject]@{ "
        "    FriendlyName = $disk.FriendlyName; "
        "    SerialNumber = $disk.SerialNumber; "
        "    MediaType = $disk.MediaType; "
        "    HealthStatus = $disk.HealthStatus; "
        "    OperationalStatus = $disk.OperationalStatus; "
        "    Size = $disk.Size; "
        "    Temperature = if ($counter) { $counter.Temperature } else { $null }; "
        "    Wear = if ($counter) { $counter.Wear } else { $null }; "
        "    ReadErrorsTotal = if ($counter) { $counter.ReadErrorsTotal } else { $null }; "
        "    WriteErrorsTotal = if ($counter) { $counter.WriteErrorsTotal } else { $null }; "
        "    PowerOnHours = if ($counter) { $counter.PowerOnHours } else { $null }; "
        "    StartStopCycleCount = if ($counter) { $counter.StartStopCycleCount } else { $null }; "
        "    LoadUnloadCycleCount = if ($counter) { $counter.LoadUnloadCycleCount } else { $null } "
        "  } "
        "}; "
        "$items | ConvertTo-Json -Compress -Depth 4"
    )
    records = _normalize_records(_run_powershell_json(command))

    drives = []
    for record in records:
        if not any(record.get(key) is not None for key in ("Temperature", "Wear", "PowerOnHours")):
            if not any(
                record.get(key) is not None
                for key in ("StartStopCycleCount", "LoadUnloadCycleCount", "ReadErrorsTotal", "WriteErrorsTotal")
            ):
                continue

        drive = _empty_drive()
        friendly_name = _to_string(record.get("FriendlyName"))
        _set_if_present(drive, "name", friendly_name)
        _set_if_present(drive, "model", friendly_name)
        _set_if_present(drive, "serial", _to_string(record.get("SerialNumber")))
        _set_if_present(drive, "media_type", _to_string(record.get("MediaType")))
        _set_if_present(
            drive,
            "health_status",
            _combine_health_status(
                record.get("HealthStatus"),
                record.get("OperationalStatus"),
            ),
        )
        _set_if_present(drive, "size_gb", _round_size_gb_from_bytes(record.get("Size")))
        _set_if_present(drive, "temperature_celsius", _to_float(record.get("Temperature")))
        wear_value = _to_float(record.get("Wear"))
        if wear_value is not None:
            _set_if_present(drive, "life_percent", wear_value)
        _set_if_present(drive, "power_on_hours", _to_int(record.get("PowerOnHours")))
        _set_if_present(
            drive,
            "power_cycle_count",
            _to_int(record.get("StartStopCycleCount")) or _to_int(record.get("LoadUnloadCycleCount")),
        )
        drive["raw"]["windows_reliability_counter"] = record
        drives.append(drive)

    return drives, bool(drives)


def _collect_libre_hardware_monitor() -> tuple[list[dict[str, object]], bool]:
    try:
        with urlopen("http://localhost:8085/data.json", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return [], False
    except Exception:
        return [], False

    drives_by_key: dict[str, dict[str, object]] = {}
    drive_temperature_candidates: dict[str, list[tuple[str, float]]] = {}

    def ensure_drive(
        drive_key: str,
        *,
        name: str | None,
        hardware_id: str | None,
        path: list[str],
    ) -> dict[str, object]:
        drive = drives_by_key.get(drive_key)
        if drive is None:
            drive = _empty_drive()
            drives_by_key[drive_key] = drive

        inferred_name = name or hardware_id or drive_key
        _set_if_present(drive, "name", inferred_name)
        _set_if_present(drive, "model", inferred_name)
        _set_if_present(
            drive,
            "interface",
            _infer_interface(hardware_id, inferred_name, " / ".join(path)),
        )
        _set_if_present(
            drive,
            "media_type",
            _infer_media_type(hardware_id, inferred_name, " / ".join(path)),
        )

        raw_section = drive["raw"]["libre_hardware_monitor"]
        if not raw_section:
            raw_section = {
                "hardware_id": hardware_id,
                "path": " / ".join(path),
                "sensors": {},
            }
            drive["raw"]["libre_hardware_monitor"] = raw_section
        return drive

    def walk(
        node: object,
        path: list[str],
        hardware_id: str | None = None,
        drive_key: str | None = None,
        drive_name: str | None = None,
    ) -> None:
        if not isinstance(node, dict):
            return

        node_text = _to_string(node.get("Text"))
        current_path = path + ([node_text] if node_text else [])
        current_hardware_id = _to_string(node.get("HardwareId")) or hardware_id
        current_drive_key = drive_key
        current_drive_name = drive_name

        if _looks_like_disk(current_hardware_id, node_text, " / ".join(current_path)):
            current_drive_key = current_hardware_id or " / ".join(current_path)
            if node.get("HardwareId") is not None or current_drive_name is None:
                current_drive_name = node_text or current_drive_name
            ensure_drive(
                current_drive_key,
                name=current_drive_name,
                hardware_id=current_hardware_id,
                path=current_path,
            )

        if node.get("SensorId") is not None and current_drive_key is not None:
            drive = ensure_drive(
                current_drive_key,
                name=current_drive_name,
                hardware_id=current_hardware_id,
                path=current_path,
            )
            raw_section = drive["raw"]["libre_hardware_monitor"]
            if isinstance(raw_section.get("sensors"), dict):
                raw_section["sensors"][node_text or "Unknown"] = {
                    "value": node.get("Value"),
                    "type": node.get("Type"),
                    "sensor_id": node.get("SensorId"),
                }

            sensor_name = (node_text or "").lower()
            sensor_type = (_to_string(node.get("Type")) or "").lower()
            value = _to_float(node.get("Value"))

            if value is not None and sensor_type == "temperature":
                if not any(
                    keyword in sensor_name
                    for keyword in ("warning", "critical", "threshold", "limit")
                ):
                    drive_temperature_candidates.setdefault(current_drive_key, []).append(
                        (sensor_name, value)
                    )

            if "life" in sensor_name and "power" not in sensor_name:
                _set_if_present(drive, "life_percent", value)
            elif "available spare threshold" in sensor_name:
                _set_if_present(drive, "available_spare_threshold", value)
            elif "available spare" in sensor_name:
                _set_if_present(drive, "available_spare", value)
            elif "percentage used" in sensor_name:
                _set_if_present(drive, "percentage_used", value)
                if value is not None:
                    _set_if_present(drive, "life_percent", max(0.0, 100.0 - value))
            elif "power on hours" in sensor_name:
                _set_if_present(drive, "power_on_hours", _to_int(node.get("Value")))
            elif "power on count" in sensor_name:
                _set_if_present(drive, "power_cycle_count", _to_int(node.get("Value")))
            elif "data read" in sensor_name:
                _set_if_present(drive, "data_read_gb", _value_to_gb(node.get("Value")))
            elif "data written" in sensor_name:
                _set_if_present(drive, "data_written_gb", _value_to_gb(node.get("Value")))

        for child in node.get("Children", []):
            walk(
                child,
                current_path,
                current_hardware_id,
                current_drive_key,
                current_drive_name,
            )

    walk(payload, [])

    for drive_key, candidates in drive_temperature_candidates.items():
        drive = drives_by_key.get(drive_key)
        if drive is None or not candidates:
            continue

        preferred_candidates = [
            value
            for name, value in candidates
            if "composite temperature" in name or name == "temperature"
        ]
        if preferred_candidates:
            drive["temperature_celsius"] = max(preferred_candidates)
        else:
            drive["temperature_celsius"] = max(value for _, value in candidates)

    drives = list(drives_by_key.values())
    return drives, bool(drives)


def _parse_smartctl_scan_line(line: str) -> tuple[str, str | None] | None:
    match = re.match(r"^(?P<device>\S+)(?:\s+-d\s+(?P<device_type>\S+))?", line.strip())
    if not match:
        return None
    return match.group("device"), match.group("device_type")


def _smartctl_data_units_to_gb(value: object) -> float | None:
    units = _to_float(value)
    if units is None:
        return None
    return _round_gb((units * 512000) / (1024 ** 3))


def _collect_smartctl() -> tuple[list[dict[str, object]], bool]:
    scan_output = _run_command(["smartctl", "--scan-open"], timeout=10)
    if not scan_output:
        return [], False

    drives = []
    for line in scan_output.splitlines():
        parsed = _parse_smartctl_scan_line(line)
        if parsed is None:
            continue

        device_path, device_type = parsed
        command = ["smartctl", "-a", "-j"]
        if device_type:
            command.extend(["-d", device_type])
        command.append(device_path)

        output = _run_command(command, timeout=20)
        if not output:
            continue

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            continue

        drive = _empty_drive()
        model_name = (
            _to_string(payload.get("model_name"))
            or _to_string(payload.get("model_family"))
            or _to_string(payload.get("product"))
            or _to_string(payload.get("vendor"))
            or device_path
        )
        _set_if_present(drive, "name", device_path)
        _set_if_present(drive, "model", model_name)
        _set_if_present(drive, "serial", _to_string(payload.get("serial_number")))
        _set_if_present(
            drive,
            "interface",
            _infer_interface(
                device_type,
                payload.get("device", {}).get("type") if isinstance(payload.get("device"), dict) else None,
                payload.get("interface_speed", {}).get("max") if isinstance(payload.get("interface_speed"), dict) else None,
            ),
        )
        _set_if_present(
            drive,
            "media_type",
            _infer_media_type(
                device_type,
                payload.get("device", {}).get("type") if isinstance(payload.get("device"), dict) else None,
                model_name,
            ),
        )
        _set_if_present(
            drive,
            "size_gb",
            _round_size_gb_from_bytes(
                payload.get("user_capacity", {}).get("bytes")
                if isinstance(payload.get("user_capacity"), dict)
                else None
            ),
        )

        smart_status = payload.get("smart_status")
        if isinstance(smart_status, dict) and smart_status.get("passed") is not None:
            drive["health_status"] = "Passed" if smart_status.get("passed") else "Failed"

        nvme_log = payload.get("nvme_smart_health_information_log")
        if isinstance(nvme_log, dict):
            if drive.get("health_status") is None:
                critical_warning = _to_int(nvme_log.get("critical_warning"))
                if critical_warning is not None:
                    drive["health_status"] = "Passed" if critical_warning == 0 else "Critical Warning"

            percentage_used = _to_float(nvme_log.get("percentage_used"))
            _set_if_present(drive, "percentage_used", percentage_used)
            if percentage_used is not None:
                _set_if_present(drive, "life_percent", max(0.0, 100.0 - percentage_used))
            _set_if_present(drive, "available_spare", _to_float(nvme_log.get("available_spare")))
            _set_if_present(
                drive,
                "available_spare_threshold",
                _to_float(nvme_log.get("available_spare_threshold")),
            )
            _set_if_present(drive, "media_errors", _to_int(nvme_log.get("media_errors")))
            _set_if_present(drive, "unsafe_shutdowns", _to_int(nvme_log.get("unsafe_shutdowns")))
            _set_if_present(
                drive,
                "data_read_gb",
                _smartctl_data_units_to_gb(
                    nvme_log.get("data_units_read", {}).get("value")
                    if isinstance(nvme_log.get("data_units_read"), dict)
                    else nvme_log.get("data_units_read")
                ),
            )
            _set_if_present(
                drive,
                "data_written_gb",
                _smartctl_data_units_to_gb(
                    nvme_log.get("data_units_written", {}).get("value")
                    if isinstance(nvme_log.get("data_units_written"), dict)
                    else nvme_log.get("data_units_written")
                ),
            )

        temperature = None
        if isinstance(payload.get("temperature"), dict):
            temperature = _to_float(payload["temperature"].get("current"))
        if temperature is None and isinstance(nvme_log, dict):
            temperature = _to_float(nvme_log.get("temperature"))
        _set_if_present(drive, "temperature_celsius", temperature)

        power_on_time = payload.get("power_on_time")
        if isinstance(power_on_time, dict):
            _set_if_present(drive, "power_on_hours", _to_int(power_on_time.get("hours")))
        _set_if_present(drive, "power_cycle_count", _to_int(payload.get("power_cycle_count")))

        ata_table = []
        ata_attributes = payload.get("ata_smart_attributes")
        if isinstance(ata_attributes, dict):
            ata_table = [
                item
                for item in ata_attributes.get("table", [])
                if isinstance(item, dict)
            ]

        _set_if_present(
            drive,
            "reallocated_sectors_count",
            _find_ata_attribute(
                ata_table,
                names=("reallocated_sector_ct", "reallocated_sectors_count"),
                ids=(5,),
            ),
        )
        _set_if_present(
            drive,
            "current_pending_sector_count",
            _find_ata_attribute(
                ata_table,
                names=("current_pending_sector", "current_pending_sector_count"),
                ids=(197,),
            ),
        )
        _set_if_present(
            drive,
            "offline_uncorrectable",
            _find_ata_attribute(
                ata_table,
                names=("offline_uncorrectable",),
                ids=(198,),
            ),
        )
        _set_if_present(
            drive,
            "reported_uncorrectable_errors",
            _find_ata_attribute(
                ata_table,
                names=("reported_uncorrect", "reported_uncorrectable_errors"),
                ids=(187,),
            ),
        )

        drive["raw"]["smartctl"] = payload
        drives.append(drive)

    return drives, bool(drives)


def collect_smart_data() -> dict[str, object]:
    windows_physical_drives, windows_physical_available = _collect_windows_physical_disk()
    reliability_drives, reliability_available = _collect_windows_reliability_counter()
    libre_drives, libre_available = _collect_libre_hardware_monitor()
    smartctl_drives, smartctl_available = _collect_smartctl()

    merged_drives: list[dict[str, object]] = []
    for source_drives in (
        windows_physical_drives,
        reliability_drives,
        libre_drives,
        smartctl_drives,
    ):
        for source_drive in source_drives:
            merge_candidate = _find_merge_candidate(merged_drives, source_drive)
            if merge_candidate is None:
                merged_drives.append(source_drive)
                continue
            _merge_drive_data(merge_candidate, source_drive)

    return {
        "drives": merged_drives,
        "sources": {
            "windows_physical_disk": windows_physical_available,
            "windows_reliability_counter": reliability_available,
            "libre_hardware_monitor": libre_available,
            "smartctl": smartctl_available,
        },
    }
