import json
import os
import re
import subprocess
from urllib.error import URLError
from urllib.request import urlopen

from app.services.external_tools_service import find_smartctl_executable


SOURCE_PRIORITY = {
    "smartctl": 1,
    "windows_smart_wmi": 2,
    "libre_hardware_monitor": 3,
    "windows_reliability_counter": 4,
    "windows_physical_disk": 5,
}

SOURCE_NAMES = (
    "windows_physical_disk",
    "windows_reliability_counter",
    "windows_smart_wmi",
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
    "raw_read_error_rate",
    "seek_error_rate",
    "spin_retry_count",
    "start_stop_count",
    "reallocated_event_count",
    "command_timeout",
    "end_to_end_error",
    "runtime_bad_block",
    "udma_crc_error_count",
    "hardware_ecc_recovered",
    "num_err_log_entries",
    "critical_warning",
    "warning_temp_time",
    "critical_comp_time",
    "smartctl_exit_status",
)

ATA_ATTRIBUTE_FIELD_MAP: dict[tuple[int, str], tuple[str, ...]] = {
    (1, "raw_read_error_rate"): ("raw_read_error_rate",),
    (4, "start_stop_count"): ("start_stop_count",),
    (5, "reallocated_sector_ct"): ("reallocated_sectors_count",),
    (7, "seek_error_rate"): ("seek_error_rate",),
    (9, "power_on_hours"): ("power_on_hours",),
    (10, "spin_retry_count"): ("spin_retry_count",),
    (12, "power_cycle_count"): ("power_cycle_count",),
    (183, "runtime_bad_block"): ("runtime_bad_block",),
    (184, "end-to-end_error"): ("end_to_end_error",),
    (187, "reported_uncorrect"): ("reported_uncorrectable_errors",),
    (187, "reported_uncorrectable_errors"): ("reported_uncorrectable_errors",),
    (188, "command_timeout"): ("command_timeout",),
    (194, "temperature_celsius"): ("temperature_celsius",),
    (195, "hardware_ecc_recovered"): ("hardware_ecc_recovered",),
    (196, "reallocated_event_count"): ("reallocated_event_count",),
    (197, "current_pending_sector"): ("current_pending_sector_count",),
    (198, "offline_uncorrectable"): ("offline_uncorrectable",),
    (199, "udma_crc_error_count"): ("udma_crc_error_count",),
}

WMI_ATTRIBUTE_TO_FIELD = {
    5: "reallocated_sectors_count",
    9: "power_on_hours",
    12: "power_cycle_count",
    197: "current_pending_sector_count",
    198: "offline_uncorrectable",
    199: "udma_crc_error_count",
}


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
    drive = {field: None for field in DRIVE_FIELDS}
    drive["raw"] = {source_name: {} for source_name in SOURCE_NAMES}
    drive["_field_sources"] = {}
    return drive


def _finalize_drive(drive: dict[str, object]) -> dict[str, object]:
    drive.pop("_field_sources", None)
    return drive


def _normalize_text(value: object) -> str | None:
    text = _to_string(value)
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_serial(value: object) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    normalized = re.sub(r"[^a-z0-9]", "", text)
    return normalized or None


def _normalize_name_or_model(value: object) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


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


def _infer_media_type(*values: object, rotation_rate: object | None = None) -> str | None:
    rotation_value = _to_int(rotation_rate)
    if rotation_value is not None and rotation_value > 0:
        return "HDD"

    haystack = " ".join(str(value).lower() for value in values if value is not None)
    if "nvme" in haystack:
        return "SSD"
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


def _attribute_raw_string(attribute: dict[str, object]) -> str | None:
    raw = attribute.get("raw")
    if isinstance(raw, dict):
        return _to_string(raw.get("string"))
    return _to_string(raw)


def _attribute_raw_int(attribute: dict[str, object]) -> int | None:
    raw = attribute.get("raw")
    if isinstance(raw, dict):
        value = _to_int(raw.get("value"))
        if value is not None:
            return value
        return _to_int(raw.get("string"))
    return _to_int(raw)


def _find_ata_attribute_entry(
    table: list[dict[str, object]],
    *,
    names: tuple[str, ...] = (),
    ids: tuple[int, ...] = (),
) -> dict[str, object] | None:
    normalized_names = {_normalize_text(name) for name in names}
    for attribute in table:
        if not isinstance(attribute, dict):
            continue
        attribute_name = _normalize_text(attribute.get("name"))
        attribute_id = _to_int(attribute.get("id"))
        if attribute_name in normalized_names or (
            attribute_id is not None and attribute_id in ids
        ):
            return attribute
    return None


def _find_ata_attribute_int(
    table: list[dict[str, object]],
    *,
    names: tuple[str, ...] = (),
    ids: tuple[int, ...] = (),
) -> int | None:
    attribute = _find_ata_attribute_entry(table, names=names, ids=ids)
    if attribute is None:
        return None
    return _attribute_raw_int(attribute)


def _extract_first_int(text: object) -> int | None:
    value = _to_string(text)
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _normalize_temperature_value(value: object) -> float | None:
    numeric_value = _to_float(value)
    if numeric_value is None:
        return None
    if numeric_value > 200:
        numeric_value = numeric_value - 273.15
    if numeric_value < 0 or numeric_value > 120:
        return None
    return round(numeric_value, 2)


def _extract_ata_temperature(table: list[dict[str, object]]) -> float | None:
    for names, ids in (
        (("temperature_celsius",), (194,)),
        (("airflow_temperature_cel", "airflow_temperature_celsius"), (190,)),
    ):
        attribute = _find_ata_attribute_entry(table, names=names, ids=ids)
        if attribute is None:
            continue

        raw_string = _attribute_raw_string(attribute)
        first_number = _extract_first_int(raw_string)
        normalized_first_number = _normalize_temperature_value(first_number)
        if normalized_first_number is not None:
            return normalized_first_number

        raw_value = _attribute_raw_int(attribute)
        normalized_raw_value = _normalize_temperature_value(raw_value)
        if normalized_raw_value is not None:
            return normalized_raw_value

    return None


def _smartctl_data_units_to_gb(value: object) -> float | None:
    units = _to_float(value)
    if units is None:
        return None
    return _round_gb((units * 512000) / (1024 ** 3))


def _as_number_or_none(value: object) -> int | float | None:
    int_value = _to_int(value)
    if int_value is not None:
        return int_value
    return _to_float(value)


def _are_sizes_close(first: object, second: object) -> bool:
    first_value = _to_float(first)
    second_value = _to_float(second)
    if first_value is None or second_value is None:
        return False
    difference = abs(first_value - second_value)
    if difference <= 2:
        return True
    largest = max(first_value, second_value)
    if largest == 0:
        return True
    return (difference / largest) <= 0.02


def _are_values_equivalent(field: str, first: object, second: object) -> bool:
    if first is None or second is None:
        return False

    if field in {"serial"}:
        return _normalize_serial(first) == _normalize_serial(second)

    if field in {"name", "model", "interface", "media_type", "health_status"}:
        return _normalize_text(first) == _normalize_text(second)

    if field == "size_gb":
        return _are_sizes_close(first, second)

    first_number = _to_float(first)
    second_number = _to_float(second)
    if first_number is None or second_number is None:
        return str(first) == str(second)

    tolerance = 0.01
    if field in {"temperature_celsius"}:
        tolerance = 2.0
    elif field in {"data_read_gb", "data_written_gb"}:
        tolerance = max(2.0, max(abs(first_number), abs(second_number)) * 0.02)
    elif field in {"life_percent", "percentage_used", "available_spare", "available_spare_threshold"}:
        tolerance = 1.0
    return abs(first_number - second_number) <= tolerance


def _raw_is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return not value
    if isinstance(value, list):
        return len(value) == 0
    return False


def _raw_signature(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _merge_raw_value(existing: object, incoming: object) -> object:
    if _raw_is_empty(existing):
        return incoming
    if _raw_is_empty(incoming):
        return existing

    if _raw_signature(existing) == _raw_signature(incoming):
        return existing

    if isinstance(existing, list):
        existing_list = existing[:]
    else:
        existing_list = [existing]

    incoming_items = incoming if isinstance(incoming, list) else [incoming]
    seen = {_raw_signature(item) for item in existing_list}
    for item in incoming_items:
        signature = _raw_signature(item)
        if signature in seen:
            continue
        existing_list.append(item)
        seen.add(signature)
    return existing_list


def _is_nvme_like(drive: dict[str, object]) -> bool:
    return _infer_interface(
        drive.get("interface"),
        drive.get("media_type"),
        drive.get("name"),
        drive.get("model"),
    ) == "NVMe"


def _drive_aliases(drive: dict[str, object]) -> set[str]:
    aliases = set()
    for field in ("name", "model"):
        normalized = _normalize_name_or_model(drive.get(field))
        if normalized:
            aliases.add(normalized)
    return aliases


def _find_merge_candidate(
    drives: list[dict[str, object]],
    incoming_drive: dict[str, object],
) -> dict[str, object] | None:
    incoming_serial = _normalize_serial(incoming_drive.get("serial"))
    if incoming_serial is not None:
        for existing_drive in drives:
            if incoming_serial == _normalize_serial(existing_drive.get("serial")):
                return existing_drive

    incoming_aliases = _drive_aliases(incoming_drive)
    incoming_model = _normalize_name_or_model(incoming_drive.get("model"))
    incoming_name = _normalize_name_or_model(incoming_drive.get("name"))
    incoming_size = incoming_drive.get("size_gb")
    incoming_nvme = _is_nvme_like(incoming_drive)

    scored_candidates: list[tuple[int, dict[str, object]]] = []
    for existing_drive in drives:
        existing_aliases = _drive_aliases(existing_drive)
        existing_model = _normalize_name_or_model(existing_drive.get("model"))
        existing_name = _normalize_name_or_model(existing_drive.get("name"))
        size_close = _are_sizes_close(existing_drive.get("size_gb"), incoming_size)
        alias_overlap = bool(incoming_aliases & existing_aliases)
        same_model = incoming_model is not None and incoming_model == existing_model
        same_name = incoming_name is not None and incoming_name == existing_name
        nvme_like = incoming_nvme or _is_nvme_like(existing_drive)

        if same_model and size_close:
            scored_candidates.append((100 if nvme_like else 95, existing_drive))
            continue
        if alias_overlap and size_close:
            scored_candidates.append((90 if nvme_like else 80, existing_drive))
            continue
        if same_name and same_model:
            scored_candidates.append((75, existing_drive))
            continue
        if nvme_like and same_model:
            scored_candidates.append((70, existing_drive))

    if not scored_candidates:
        return None

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    best_score = scored_candidates[0][0]
    best_candidates = [candidate for score, candidate in scored_candidates if score == best_score]
    if len(best_candidates) == 1:
        return best_candidates[0]
    return None


def _merge_drive_data(
    target_drive: dict[str, object],
    source_drive: dict[str, object],
    *,
    source_name: str,
) -> None:
    field_sources = target_drive.setdefault("_field_sources", {})
    source_priority = SOURCE_PRIORITY[source_name]

    for field in DRIVE_FIELDS:
        incoming_value = source_drive.get(field)
        if incoming_value is None:
            continue

        current_value = target_drive.get(field)
        current_source = field_sources.get(field)
        current_priority = SOURCE_PRIORITY.get(current_source, 999)

        if current_value is None:
            target_drive[field] = incoming_value
            field_sources[field] = source_name
            continue

        if _are_values_equivalent(field, current_value, incoming_value):
            if current_priority > source_priority:
                field_sources[field] = source_name
            continue

        if source_priority < current_priority:
            target_drive[field] = incoming_value
            field_sources[field] = source_name

    target_raw = target_drive.get("raw")
    source_raw = source_drive.get("raw")
    if isinstance(target_raw, dict) and isinstance(source_raw, dict):
        for raw_source_name in SOURCE_NAMES:
            target_raw[raw_source_name] = _merge_raw_value(
                target_raw.get(raw_source_name),
                source_raw.get(raw_source_name),
            )


def _collect_windows_physical_disk() -> tuple[list[dict[str, object]], bool]:
    command = (
        "Get-PhysicalDisk | "
        "Select-Object FriendlyName, Model, SerialNumber, MediaType, HealthStatus, OperationalStatus, Size, BusType, DeviceId, UniqueId, Manufacturer | "
        "ConvertTo-Json -Compress -Depth 4"
    )
    records = _normalize_records(_run_powershell_json(command))

    drives = []
    for record in records:
        drive = _empty_drive()
        friendly_name = _to_string(record.get("FriendlyName"))
        model_name = _to_string(record.get("Model")) or friendly_name
        _set_if_present(drive, "name", friendly_name or model_name)
        _set_if_present(drive, "model", model_name)
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

    return drives, bool(records)


def _collect_windows_reliability_counter_records(command: str) -> list[dict[str, object]]:
    return _normalize_records(_run_powershell_json(command, timeout=20))


def _collect_windows_reliability_counter() -> tuple[list[dict[str, object]], bool]:
    commands = (
        (
            "$items = Get-PhysicalDisk | ForEach-Object { "
            "  $disk = $_; "
            "  $counter = $null; "
            "  try { $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop } catch {} "
            "  [pscustomobject]@{ "
            "    Source = 'Get-PhysicalDisk'; "
            "    FriendlyName = $disk.FriendlyName; "
            "    Model = $disk.Model; "
            "    SerialNumber = $disk.SerialNumber; "
            "    MediaType = $disk.MediaType; "
            "    HealthStatus = $disk.HealthStatus; "
            "    OperationalStatus = $disk.OperationalStatus; "
            "    Size = $disk.Size; "
            "    BusType = $disk.BusType; "
            "    DeviceId = $disk.DeviceId; "
            "    Number = $null; "
            "    Reliability = $counter "
            "  } "
            "}; "
            "$items | ConvertTo-Json -Compress -Depth 6"
        ),
        (
            "$items = Get-Disk | ForEach-Object { "
            "  $disk = $_; "
            "  $counter = $null; "
            "  try { $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop } catch {} "
            "  [pscustomobject]@{ "
            "    Source = 'Get-Disk'; "
            "    FriendlyName = $disk.FriendlyName; "
            "    Model = $disk.Model; "
            "    SerialNumber = $disk.SerialNumber; "
            "    MediaType = $null; "
            "    HealthStatus = $disk.HealthStatus; "
            "    OperationalStatus = $disk.OperationalStatus; "
            "    Size = $disk.Size; "
            "    BusType = $disk.BusType; "
            "    DeviceId = $disk.DeviceId; "
            "    Number = $disk.Number; "
            "    Reliability = $counter "
            "  } "
            "}; "
            "$items | ConvertTo-Json -Compress -Depth 6"
        ),
    )

    records: list[dict[str, object]] = []
    for command in commands:
        records.extend(_collect_windows_reliability_counter_records(command))

    drives = []
    for record in records:
        drive = _empty_drive()
        reliability = record.get("Reliability")
        reliability_dict = reliability if isinstance(reliability, dict) else {}
        friendly_name = _to_string(record.get("FriendlyName"))
        model_name = _to_string(record.get("Model")) or friendly_name

        _set_if_present(drive, "name", friendly_name or model_name)
        _set_if_present(drive, "model", model_name)
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
        _set_if_present(
            drive,
            "temperature_celsius",
            _normalize_temperature_value(reliability_dict.get("Temperature")),
        )

        wear_value = _to_float(reliability_dict.get("Wear"))
        if wear_value is not None:
            _set_if_present(drive, "life_percent", wear_value)

        _set_if_present(drive, "power_on_hours", _to_int(reliability_dict.get("PowerOnHours")))
        _set_if_present(
            drive,
            "power_cycle_count",
            _to_int(reliability_dict.get("PowerCycleCount"))
            or _to_int(reliability_dict.get("StartStopCycleCount"))
            or _to_int(reliability_dict.get("LoadUnloadCycleCount")),
        )
        _set_if_present(
            drive,
            "start_stop_count",
            _to_int(reliability_dict.get("StartStopCycleCount"))
            or _to_int(reliability_dict.get("LoadUnloadCycleCount")),
        )
        _set_if_present(
            drive,
            "reallocated_sectors_count",
            _to_int(reliability_dict.get("ReallocatedSectors")),
        )
        _set_if_present(
            drive,
            "current_pending_sector_count",
            _to_int(reliability_dict.get("PendingSectors")),
        )
        _set_if_present(
            drive,
            "offline_uncorrectable",
            _to_int(reliability_dict.get("UncorrectableSectors")),
        )

        if any(
            drive.get(field) is not None
            for field in ("name", "model", "serial", "size_gb")
        ):
            drive["raw"]["windows_reliability_counter"] = record
            drives.append(drive)

    return drives, bool(records)


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
                    "raw_value": node.get("RawValue"),
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


def _find_smartctl_path() -> str | None:
    smartctl_path = find_smartctl_executable()
    return str(smartctl_path) if smartctl_path is not None else None


def _parse_smartctl_scan_line(line: str) -> tuple[str, str | None] | None:
    match = re.match(
        r"^(?P<device>\S+)(?:\s+-d\s+(?P<device_type>\S+))?(?:\s+#.*)?$",
        line.strip(),
    )
    if not match:
        return None
    return match.group("device"), match.group("device_type")


def _extract_smartctl_temperature(
    payload: dict[str, object],
    ata_table: list[dict[str, object]],
    nvme_log: dict[str, object] | None,
) -> float | None:
    if isinstance(payload.get("temperature"), dict):
        current = _normalize_temperature_value(payload["temperature"].get("current"))
        if current is not None:
            return current

    ata_temperature = _extract_ata_temperature(ata_table)
    if ata_temperature is not None:
        return ata_temperature

    if isinstance(nvme_log, dict):
        nvme_temperature = _normalize_temperature_value(nvme_log.get("temperature"))
        if nvme_temperature is not None:
            return nvme_temperature

    return None


def _parse_smartctl_ata_attributes(
    drive: dict[str, object],
    table: list[dict[str, object]],
) -> None:
    for attribute in table:
        if not isinstance(attribute, dict):
            continue

        attribute_id = _to_int(attribute.get("id"))
        attribute_name = _normalize_text(attribute.get("name"))
        if attribute_id is None or attribute_name is None:
            continue

        mapped_fields = ATA_ATTRIBUTE_FIELD_MAP.get((attribute_id, attribute_name))
        if not mapped_fields:
            continue

        raw_value = _attribute_raw_int(attribute)
        if raw_value is None:
            continue

        for field_name in mapped_fields:
            if field_name == "temperature_celsius":
                normalized_temperature = _normalize_temperature_value(raw_value)
                if normalized_temperature is not None:
                    drive[field_name] = normalized_temperature
            else:
                drive[field_name] = raw_value


def _parse_smartctl_nvme_fields(
    drive: dict[str, object],
    nvme_log: dict[str, object],
) -> None:
    _set_if_present(drive, "critical_warning", _to_int(nvme_log.get("critical_warning")))
    _set_if_present(drive, "available_spare", _as_number_or_none(nvme_log.get("available_spare")))
    _set_if_present(
        drive,
        "available_spare_threshold",
        _as_number_or_none(nvme_log.get("available_spare_threshold")),
    )
    percentage_used = _as_number_or_none(nvme_log.get("percentage_used"))
    _set_if_present(drive, "percentage_used", percentage_used)
    if percentage_used is not None:
        _set_if_present(drive, "life_percent", max(0.0, 100.0 - float(percentage_used)))

    _set_if_present(drive, "media_errors", _to_int(nvme_log.get("media_errors")))
    _set_if_present(drive, "unsafe_shutdowns", _to_int(nvme_log.get("unsafe_shutdowns")))
    _set_if_present(
        drive,
        "num_err_log_entries",
        _to_int(nvme_log.get("num_err_log_entries")),
    )
    _set_if_present(
        drive,
        "warning_temp_time",
        _to_int(nvme_log.get("warning_temp_time")),
    )
    _set_if_present(
        drive,
        "critical_comp_time",
        _to_int(nvme_log.get("critical_comp_time")),
    )

    _set_if_present(
        drive,
        "power_cycle_count",
        _to_int(nvme_log.get("power_cycles")),
    )
    _set_if_present(
        drive,
        "power_on_hours",
        _to_int(nvme_log.get("power_on_hours")),
    )

    data_units_read = nvme_log.get("data_units_read")
    data_units_written = nvme_log.get("data_units_written")
    if isinstance(data_units_read, dict):
        data_units_read = data_units_read.get("value")
    if isinstance(data_units_written, dict):
        data_units_written = data_units_written.get("value")

    _set_if_present(drive, "data_read_gb", _smartctl_data_units_to_gb(data_units_read))
    _set_if_present(
        drive,
        "data_written_gb",
        _smartctl_data_units_to_gb(data_units_written),
    )


def _collect_smartctl() -> tuple[list[dict[str, object]], bool]:
    smartctl_path = _find_smartctl_path()
    if smartctl_path is None:
        return [], False

    scan_output = _run_command([smartctl_path, "--scan-open"], timeout=10)
    if not scan_output:
        scan_output = _run_command([smartctl_path, "--scan"], timeout=10)
    if not scan_output:
        return [], False

    drives = []
    for line in scan_output.splitlines():
        parsed = _parse_smartctl_scan_line(line)
        if parsed is None:
            continue

        device_path, device_type = parsed
        commands_to_try = []
        if device_type:
            commands_to_try.append([smartctl_path, "-a", "-j", "-d", device_type, device_path])
        commands_to_try.append([smartctl_path, "-a", "-j", device_path])

        payload = None
        for command in commands_to_try:
            output = _run_command(command, timeout=20)
            if not output:
                continue
            try:
                payload = json.loads(output)
                break
            except json.JSONDecodeError:
                continue

        if not isinstance(payload, dict):
            continue

        drive = _empty_drive()
        device_info = payload.get("device") if isinstance(payload.get("device"), dict) else {}
        user_capacity = payload.get("user_capacity") if isinstance(payload.get("user_capacity"), dict) else {}
        smartctl_info = payload.get("smartctl") if isinstance(payload.get("smartctl"), dict) else {}
        nvme_log = payload.get("nvme_smart_health_information_log")
        if not isinstance(nvme_log, dict):
            nvme_log = None

        model_name = (
            _to_string(payload.get("model_name"))
            or _to_string(payload.get("model_family"))
            or _to_string(payload.get("product"))
            or _to_string(payload.get("vendor"))
            or device_path
        )

        _set_if_present(drive, "name", model_name)
        _set_if_present(drive, "model", model_name)
        _set_if_present(drive, "serial", _to_string(payload.get("serial_number")))
        _set_if_present(
            drive,
            "interface",
            _infer_interface(
                device_type,
                device_info.get("type"),
                device_info.get("protocol"),
                payload.get("interface_speed"),
            ),
        )
        _set_if_present(
            drive,
            "media_type",
            _infer_media_type(
                device_type,
                device_info.get("type"),
                device_info.get("protocol"),
                model_name,
                rotation_rate=payload.get("rotation_rate"),
            ),
        )

        size_bytes = user_capacity.get("bytes")
        if size_bytes is None:
            size_bytes = payload.get("nvme_total_capacity")
        _set_if_present(drive, "size_gb", _round_size_gb_from_bytes(size_bytes))

        smart_status = payload.get("smart_status")
        if isinstance(smart_status, dict) and smart_status.get("passed") is not None:
            drive["health_status"] = "PASSED" if smart_status.get("passed") else "FAILED"

        if drive.get("health_status") is None and nvme_log is not None:
            critical_warning = _to_int(nvme_log.get("critical_warning"))
            if critical_warning is not None:
                drive["health_status"] = "PASSED" if critical_warning == 0 else "FAILED"

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

        _parse_smartctl_ata_attributes(drive, ata_table)

        if nvme_log is not None:
            _parse_smartctl_nvme_fields(drive, nvme_log)

        _set_if_present(
            drive,
            "temperature_celsius",
            _extract_smartctl_temperature(payload, ata_table, nvme_log),
        )
        _set_if_present(
            drive,
            "smartctl_exit_status",
            _to_int(smartctl_info.get("exit_status")),
        )

        drive["raw"]["smartctl"] = {
            "scan": {
                "device_path": device_path,
                "device_type": device_type,
            },
            "payload": payload,
        }
        drives.append(drive)

    return drives, bool(drives)


def _extract_model_from_wmi_instance(instance_name: object) -> str | None:
    instance = _to_string(instance_name)
    if instance is None:
        return None

    vendor_match = re.search(r"ven_([^&\\]+)", instance, flags=re.IGNORECASE)
    product_match = re.search(r"prod_([^\\]+)", instance, flags=re.IGNORECASE)

    vendor = None
    if vendor_match:
        vendor = vendor_match.group(1).replace("_", " ").strip()
    product = None
    if product_match:
        product = re.sub(r"_+", " ", product_match.group(1)).strip(" _")

    if vendor and product:
        if product.lower().startswith(vendor.lower()):
            return product
        return f"{vendor} {product}".strip()
    return product or vendor


def _extract_wmi_vendor_bytes(value: object) -> list[int]:
    if isinstance(value, list):
        result = []
        for item in value:
            item_value = _to_int(item)
            if item_value is None:
                continue
            if 0 <= item_value <= 255:
                result.append(item_value)
        return result

    value_text = _to_string(value)
    if value_text is None:
        return []

    if value_text.startswith("[") and value_text.endswith("]"):
        try:
            decoded = json.loads(value_text)
            return _extract_wmi_vendor_bytes(decoded)
        except json.JSONDecodeError:
            return []

    matches = re.findall(r"\d+", value_text)
    bytes_list = []
    for match in matches:
        number = _to_int(match)
        if number is not None and 0 <= number <= 255:
            bytes_list.append(number)
    return bytes_list


def _parse_wmi_failure_predict_data(raw_bytes: list[int]) -> dict[int, int]:
    if len(raw_bytes) < 14:
        return {}

    attributes = {}
    offset = 2
    while offset + 11 < len(raw_bytes):
        attribute_id = raw_bytes[offset]
        if attribute_id == 0:
            offset += 12
            continue

        raw_value = 0
        for byte_index in range(6):
            raw_value |= raw_bytes[offset + 5 + byte_index] << (8 * byte_index)
        attributes[attribute_id] = raw_value
        offset += 12

    return attributes


def _parse_wmi_failure_predict_thresholds(raw_bytes: list[int]) -> dict[int, int]:
    if len(raw_bytes) < 14:
        return {}

    thresholds = {}
    offset = 2
    while offset + 11 < len(raw_bytes):
        attribute_id = raw_bytes[offset]
        if attribute_id != 0:
            thresholds[attribute_id] = raw_bytes[offset + 1]
        offset += 12
    return thresholds


def _collect_windows_smart_wmi_records(command: str) -> list[dict[str, object]]:
    return _normalize_records(_run_powershell_json(command, timeout=20))


def _collect_windows_smart_wmi() -> tuple[list[dict[str, object]], bool]:
    commands = (
        (
            "Get-CimInstance -Namespace root/wmi -ClassName MSStorageDriver_FailurePredictStatus | "
            "Select-Object InstanceName, Active, PredictFailure, Reason | "
            "ConvertTo-Json -Compress -Depth 4"
        ),
        (
            "Get-CimInstance -Namespace root/wmi -ClassName MSStorageDriver_FailurePredictData | "
            "Select-Object InstanceName, VendorSpecific | "
            "ConvertTo-Json -Compress -Depth 6"
        ),
        (
            "Get-CimInstance -Namespace root/wmi -ClassName MSStorageDriver_FailurePredictThresholds | "
            "Select-Object InstanceName, VendorSpecific | "
            "ConvertTo-Json -Compress -Depth 6"
        ),
    )

    status_records = _collect_windows_smart_wmi_records(commands[0])
    data_records = _collect_windows_smart_wmi_records(commands[1])
    threshold_records = _collect_windows_smart_wmi_records(commands[2])

    if not status_records and not data_records and not threshold_records:
        return [], False

    grouped: dict[str, dict[str, object]] = {}

    for record in status_records:
        instance_name = _to_string(record.get("InstanceName"))
        if instance_name is None:
            continue
        grouped.setdefault(instance_name, {})["status"] = record

    for record in data_records:
        instance_name = _to_string(record.get("InstanceName"))
        if instance_name is None:
            continue
        grouped.setdefault(instance_name, {})["data"] = record

    for record in threshold_records:
        instance_name = _to_string(record.get("InstanceName"))
        if instance_name is None:
            continue
        grouped.setdefault(instance_name, {})["thresholds"] = record

    drives = []
    for instance_name, source_payload in grouped.items():
        drive = _empty_drive()
        model_name = _extract_model_from_wmi_instance(instance_name)
        _set_if_present(drive, "name", model_name)
        _set_if_present(drive, "model", model_name)
        _set_if_present(drive, "interface", _infer_interface(instance_name, model_name))
        _set_if_present(drive, "media_type", _infer_media_type(instance_name, model_name))

        status_record = source_payload.get("status")
        if isinstance(status_record, dict):
            predict_failure = status_record.get("PredictFailure")
            if predict_failure is not None:
                drive["health_status"] = "FAILED" if bool(predict_failure) else "PASSED"

        data_record = source_payload.get("data")
        threshold_record = source_payload.get("thresholds")

        parsed_attributes = {}
        parsed_thresholds = {}
        if isinstance(data_record, dict):
            parsed_attributes = _parse_wmi_failure_predict_data(
                _extract_wmi_vendor_bytes(data_record.get("VendorSpecific"))
            )
        if isinstance(threshold_record, dict):
            parsed_thresholds = _parse_wmi_failure_predict_thresholds(
                _extract_wmi_vendor_bytes(threshold_record.get("VendorSpecific"))
            )

        for attribute_id, field_name in WMI_ATTRIBUTE_TO_FIELD.items():
            attribute_value = parsed_attributes.get(attribute_id)
            if attribute_value is not None:
                drive[field_name] = attribute_value

        drive["raw"]["windows_smart_wmi"] = {
            "instance_name": instance_name,
            "status": status_record or {},
            "data": data_record or {},
            "thresholds": threshold_record or {},
            "parsed_attributes": parsed_attributes,
            "parsed_thresholds": parsed_thresholds,
        }
        drives.append(drive)

    return drives, True


def collect_smart_data() -> dict[str, object]:
    collectors = (
        ("smartctl", _collect_smartctl),
        ("windows_smart_wmi", _collect_windows_smart_wmi),
        ("libre_hardware_monitor", _collect_libre_hardware_monitor),
        ("windows_reliability_counter", _collect_windows_reliability_counter),
        ("windows_physical_disk", _collect_windows_physical_disk),
    )

    collected_sources: dict[str, tuple[list[dict[str, object]], bool]] = {}
    for source_name, collector in collectors:
        try:
            collected_sources[source_name] = collector()
        except Exception:
            collected_sources[source_name] = ([], False)

    merged_drives: list[dict[str, object]] = []
    for source_name, _ in collectors:
        source_drives, _available = collected_sources[source_name]
        for source_drive in source_drives:
            merge_candidate = _find_merge_candidate(merged_drives, source_drive)
            if merge_candidate is None:
                merge_candidate = _empty_drive()
                merged_drives.append(merge_candidate)
            _merge_drive_data(merge_candidate, source_drive, source_name=source_name)

    finalized_drives = [_finalize_drive(drive) for drive in merged_drives]
    return {
        "drives": finalized_drives,
        "sources": {
            "windows_physical_disk": collected_sources["windows_physical_disk"][1],
            "windows_reliability_counter": collected_sources["windows_reliability_counter"][1],
            "windows_smart_wmi": collected_sources["windows_smart_wmi"][1],
            "libre_hardware_monitor": collected_sources["libre_hardware_monitor"][1],
            "smartctl": collected_sources["smartctl"][1],
        },
    }
