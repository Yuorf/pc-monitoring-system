import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getDashboard,
  getDashboardCharts,
  getHealth,
  getSystemStatus,
} from "./api/client";

const SECTION_ITEMS = [
  { id: "overview", label: "Обзор" },
  { id: "components", label: "Компоненты" },
  { id: "drives", label: "Накопители" },
  { id: "prediction", label: "Прогноз" },
  { id: "charts", label: "Графики" },
  { id: "diagnostics", label: "Диагностика" },
];

const CHART_COLORS = [
  "#7dd3fc",
  "#34d399",
  "#fbbf24",
  "#fb7185",
  "#a78bfa",
  "#f97316",
];

const CHART_TITLES = {
  usage: "Нагрузка компонентов",
  temperatures: "Температуры компонентов",
  power: "Потребление мощности",
  cooling: "Охлаждение",
  disk_health: "Ресурс накопителя, %",
};

const STATUS_LABELS = {
  ok: "Норма",
  warning: "Требует внимания",
  critical: "Критично",
  unknown: "Неизвестно",
  error: "Ошибка",
  partial: "Частично",
  high_risk: "Высокий риск",
  normal: "Норма",
  available: "Доступно",
  started: "Запущено",
  already_running: "Уже запущено",
  disabled: "Отключено",
  not_found: "Не найдено",
};

const CARD_CONFIG = {
  cpu: {
    title: "Процессор",
    primaryLabel: "Нагрузка",
    secondaryLabel: "Температура",
    detailLabels: {
      usage_percent: "Нагрузка",
      temperature_celsius: "Температура",
      power_watts: "Потребление",
    },
    detailUnits: {
      usage_percent: "%",
      temperature_celsius: "°C",
      power_watts: "Вт",
    },
  },
  gpu: {
    title: "Видеокарта",
    primaryLabel: "Нагрузка",
    secondaryLabel: "Температура",
    detailLabels: {
      usage_percent: "Нагрузка",
      temperature_celsius: "Температура",
      power_watts: "Потребление",
      fan_percent: "Вентилятор",
      memory_used_mb: "Память занято",
      memory_total_mb: "Память всего",
    },
    detailUnits: {
      usage_percent: "%",
      temperature_celsius: "°C",
      power_watts: "Вт",
      fan_percent: "%",
      memory_used_mb: "МБ",
      memory_total_mb: "МБ",
    },
  },
  ram: {
    title: "Оперативная память",
    primaryLabel: "Занято",
    secondaryLabel: "Температура",
    detailLabels: {
      usage_percent: "Занято",
      temperature_celsius: "Температура",
    },
    detailUnits: {
      usage_percent: "%",
      temperature_celsius: "°C",
    },
  },
};

const HDD_DETAIL_FIELDS = [
  {
    label: "Переназначенные сектора",
    keys: ["reallocated_sectors_count", "reallocated_sectors", "reallocated_sector_count"],
  },
  { label: "Ожидающие сектора", keys: ["current_pending_sector_count"] },
  {
    label: "Некорректируемые ошибки",
    keys: ["offline_uncorrectable", "reported_uncorrectable_errors"],
  },
  { label: "CRC ошибки", keys: ["udma_crc_error_count"] },
];

const SSD_DETAIL_FIELDS = [
  { label: "Ресурс использован", keys: ["percentage_used"], unit: "%" },
  { label: "Доступный резерв", keys: ["available_spare"], unit: "%" },
  { label: "Ошибки носителя", keys: ["media_errors"] },
  { label: "Небезопасные выключения", keys: ["unsafe_shutdowns"] },
  { label: "Прочитано данных", keys: ["data_read_gb"], unit: "ГБ" },
  { label: "Записано данных", keys: ["data_written_gb"], unit: "ГБ" },
];

const ML_RISK_NOTE =
  "Это не гарантия отказа, а оценка модели по SMART-признакам накопителя.";

function formatStatusLabel(status) {
  if (!status) {
    return "Неизвестно";
  }
  return STATUS_LABELS[status] || status;
}

function formatMetric(value, unit = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "Нет данных";
  }

  const numericValue = Number(value);
  const formatted = Number.isInteger(numericValue)
    ? numericValue.toString()
    : numericValue.toFixed(digits);

  return unit ? `${formatted} ${unit}` : formatted;
}

function formatDateTime(value) {
  if (!value) {
    return "Нет данных";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatUpdatedTime(value) {
  if (!value) {
    return "Нет данных";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatShortTime(value) {
  if (!value) {
    return "--:--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatStorageValue(value) {
  if (value === null || value === undefined) {
    return "Нет данных";
  }

  const numericValue = Number(value);
  if (Number.isNaN(numericValue)) {
    return String(value);
  }

  if (numericValue > 1024 ** 3) {
    return `${(numericValue / 1024 ** 3).toFixed(2)} ГБ`;
  }
  if (numericValue > 1024 ** 2) {
    return `${(numericValue / 1024 ** 2).toFixed(2)} МБ`;
  }
  return `${numericValue} Б`;
}

function getObjectField(source, ...keys) {
  if (!source || typeof source !== "object") {
    return null;
  }

  for (const key of keys) {
    const value = source[key];
    if (value !== null && value !== undefined && value !== "") {
      return value;
    }
  }

  return null;
}

function formatBoolean(value) {
  if (value === null || value === undefined) {
    return "Нет данных";
  }
  return value ? "Да" : "Нет";
}

function formatChartType(type) {
  if (!type || type === "line") {
    return "Линия";
  }
  return type;
}

function getToolHealthState(toolPayload) {
  const status = toolPayload?.status;
  if (
    status === "ok"
    || status === "available"
    || status === "started"
    || status === "already_running"
  ) {
    return "ok";
  }
  if (status === "error") {
    return "error";
  }
  if (status === "not_found") {
    return "warning";
  }
  return "unknown";
}

function getSmartHealthState(status) {
  const normalizedStatus = String(status || "").toUpperCase();
  if (!normalizedStatus) {
    return "unknown";
  }
  if (
    normalizedStatus.includes("PASSED")
    || normalizedStatus.includes("OK")
    || normalizedStatus.includes("HEALTHY")
  ) {
    return "ok";
  }
  if (normalizedStatus.includes("WARN")) {
    return "warning";
  }
  if (normalizedStatus.includes("FAIL") || normalizedStatus.includes("CRIT")) {
    return "critical";
  }
  return "unknown";
}

function getStatusClass(status) {
  return `status-badge status-${status || "unknown"}`;
}

function normalizeDriveType(drive) {
  const mediaType = String(getObjectField(drive, "media_type", "type", "disk_type") || "")
    .trim()
    .toUpperCase();
  const interfaceType = String(getObjectField(drive, "interface", "interface_type", "bus_type") || "")
    .trim()
    .toUpperCase();

  if (mediaType === "HDD") {
    return "HDD";
  }
  if (mediaType === "SSD" && interfaceType === "NVME") {
    return "SSD / NVMe";
  }
  if (mediaType === "SSD") {
    return "SSD";
  }
  if (
    mediaType === "USB"
    || interfaceType.includes("USB")
    || interfaceType === "SCSI"
    || interfaceType === "UAS"
  ) {
    return "USB";
  }
  return "Unknown";
}

function formatDriveCapacity(drive) {
  const sizeGb = getObjectField(drive, "size_gb", "capacity_gb");
  if (sizeGb !== null && sizeGb !== undefined && !Number.isNaN(Number(sizeGb))) {
    return `${Number(sizeGb).toFixed(2)} ГБ`;
  }

  const capacityBytes = getObjectField(drive, "capacity_bytes");
  if (capacityBytes !== null && capacityBytes !== undefined) {
    return formatStorageValue(capacityBytes);
  }

  return "Нет данных";
}

function buildVisibleCharts(chartsPayload) {
  if (!chartsPayload || typeof chartsPayload !== "object") {
    return {};
  }

  const nextCharts = { ...chartsPayload };
  const diskHealthChart = chartsPayload.disk_health;

  if (
    diskHealthChart
    && Array.isArray(diskHealthChart.series)
  ) {
    const lifeSeries = diskHealthChart.series.filter((item) => item?.key === "disk_life");
    nextCharts.disk_health = {
      ...diskHealthChart,
      title: "Ресурс накопителя, %",
      unit: "%",
      series: lifeSeries,
    };
  }

  delete nextCharts.disk_runtime;
  return nextCharts;
}

function buildFocusedChart(chartsPayload, chartKey, seriesKeys, title, unit) {
  const chart = chartsPayload?.[chartKey];
  if (!chart || !Array.isArray(chart.series)) {
    return null;
  }

  const series = chart.series.filter((item) => seriesKeys.includes(item?.key));
  if (series.length === 0) {
    return null;
  }

  return {
    ...chart,
    title,
    unit: unit || chart.unit,
    series,
  };
}

function getDriveKey(drive, index = 0) {
  return getObjectField(drive, "serial", "name", "model") || `drive-${index}`;
}

function isSameDrive(firstDrive, secondDrive) {
  const firstSerial = getObjectField(firstDrive, "serial");
  const secondSerial = getObjectField(secondDrive, "serial");
  if (firstSerial && secondSerial) {
    return firstSerial === secondSerial;
  }

  const firstModel = getObjectField(firstDrive, "model", "name");
  const secondModel = getObjectField(secondDrive, "model", "name");
  return Boolean(firstModel && secondModel && firstModel === secondModel);
}

function getDriveRiskPercent(drive, mlPrediction) {
  const riskPercent = Number(mlPrediction?.risk_percent);
  if (
    mlPrediction?.status === "high_risk"
    && isSameDrive(drive, mlPrediction?.source_drive)
    && !Number.isNaN(riskPercent)
  ) {
    return riskPercent;
  }

  const reallocatedSectors = Number(
    getObjectField(
      drive,
      "reallocated_sectors_count",
      "reallocated_sectors",
      "reallocated_sector_count",
    ),
  );
  if (!Number.isNaN(reallocatedSectors) && reallocatedSectors > 0) {
    return 60;
  }

  return 0;
}

function isProblemDrive(drive, mlPrediction) {
  const riskPercent = getDriveRiskPercent(drive, mlPrediction);
  const pendingSectors = Number(getObjectField(drive, "current_pending_sector_count"));
  const offlineUncorrectable = Number(
    getObjectField(drive, "offline_uncorrectable", "reported_uncorrectable_errors"),
  );

  return (
    riskPercent >= 50
    || (!Number.isNaN(pendingSectors) && pendingSectors > 0)
    || (!Number.isNaN(offlineUncorrectable) && offlineUncorrectable > 0)
  );
}

function getDriveProblemReason(drive, mlPrediction) {
  if (mlPrediction?.status === "high_risk" && isSameDrive(drive, mlPrediction?.source_drive)) {
    return `Повышенный риск по ${getObjectField(drive, "model", "name") || "накопителю"}`;
  }

  const reallocatedSectors = Number(
    getObjectField(
      drive,
      "reallocated_sectors_count",
      "reallocated_sectors",
      "reallocated_sector_count",
    ),
  );
  if (!Number.isNaN(reallocatedSectors) && reallocatedSectors > 0) {
    return `Обнаружены переназначенные сектора: ${reallocatedSectors}`;
  }

  const pendingSectors = Number(getObjectField(drive, "current_pending_sector_count"));
  if (!Number.isNaN(pendingSectors) && pendingSectors > 0) {
    return `Есть ожидающие сектора: ${pendingSectors}`;
  }

  return "Требуется наблюдение за SMART-показателями";
}

function getDriveDetailRows(drive) {
  const driveType = normalizeDriveType(drive);
  const commonRows = [
    { label: "Тип", value: driveType },
    {
      label: "Интерфейс",
      value: getObjectField(drive, "interface", "interface_type", "bus_type") || "Нет данных",
    },
    { label: "Объём", value: formatDriveCapacity(drive) },
    {
      label: "Температура",
      value: formatMetric(getObjectField(drive, "temperature_celsius"), "°C"),
    },
    {
      label: "Состояние SMART",
      value: getObjectField(drive, "health_status") || "Нет данных",
    },
    {
      label: "Часы работы",
      value: formatMetric(getObjectField(drive, "power_on_hours")),
    },
  ];

  const extraFieldConfig = driveType.startsWith("HDD")
    ? HDD_DETAIL_FIELDS
    : driveType.startsWith("SSD")
      ? SSD_DETAIL_FIELDS
      : [];

  const extraRows = extraFieldConfig
    .map((field) => {
      const rawValue = getObjectField(drive, ...field.keys);
      if (rawValue === null || rawValue === undefined || rawValue === "") {
        return null;
      }

      return {
        label: field.label,
        value: field.unit
          ? formatMetric(rawValue, field.unit)
          : formatMetric(rawValue),
      };
    })
    .filter(Boolean);

  return {
    commonRows,
    extraRows,
  };
}

function getOverviewStatus(componentCards, drives, mlPrediction, health, healthChecks) {
  const criticalComponentCount = componentCards.filter(
    (card) => card?.status === "critical" || card?.status === "error",
  ).length;
  const problematicDrives = drives.filter((drive) => isProblemDrive(drive, mlPrediction));
  const backendCritical = [
    health?.status,
    healthChecks?.backend?.status,
    healthChecks?.database?.status,
    healthChecks?.ml_model?.status,
    healthChecks?.sensors?.status,
  ].some((status) => status === "error" || status === "critical");

  if (backendCritical || criticalComponentCount >= 2) {
    return {
      status: "critical",
      label: "Критично",
      reason: "Есть критические проблемы в работе сервера приложения или нескольких подсистем.",
    };
  }

  if (problematicDrives.length === 1 && criticalComponentCount === 0) {
    return {
      status: "warning",
      label: "Требует внимания",
      reason: getDriveProblemReason(problematicDrives[0], mlPrediction),
    };
  }

  if (problematicDrives.length > 1 || (problematicDrives.length >= 1 && criticalComponentCount >= 1)) {
    return {
      status: "critical",
      label: "Критично",
      reason: "Есть несколько проблемных компонентов или накопителей.",
    };
  }

  return {
    status: "ok",
    label: "Норма",
    reason: "Критичных предупреждений не обнаружено.",
  };
}

function getUiHealthScore(status) {
  if (status === "critical") {
    return 55;
  }
  if (status === "warning") {
    return 78;
  }
  return 96;
}

function getMlIndicatorLabel(mlPrediction) {
  if (mlPrediction?.status === "high_risk") {
    return "высокий";
  }
  if (mlPrediction?.status === "normal") {
    return "норма";
  }
  return "нет данных";
}

function getDriveSummary(drives, mlPrediction) {
  const problematicDrives = drives.filter((drive) => isProblemDrive(drive, mlPrediction));
  const topDrive = problematicDrives[0] || null;

  return {
    total: drives.length,
    problemCount: problematicDrives.length,
    mlIndicator: getMlIndicatorLabel(mlPrediction),
    topReason: topDrive
      ? getDriveProblemReason(topDrive, mlPrediction)
      : "Все накопители без признаков риска.",
  };
}

function normalizeWarningItem(item) {
  if (!item || item.metric !== "ml_smart_failure_prediction") {
    return item;
  }

  return {
    ...item,
    level: "warning",
    message: "ML-модель выявила повышенный риск по SMART-признакам накопителя.",
  };
}

function normalizeRecommendationItem(item) {
  if (!item || item.metric !== "ml_smart_failure_prediction") {
    return item;
  }

  return {
    ...item,
    priority: "medium",
    message:
      "Создайте или обновите резервную копию важных данных, выполните расширенную SMART-диагностику и наблюдайте за динамикой состояния накопителя.",
    reason: "Модель выявила повышенный риск по SMART-признакам накопителя.",
  };
}

function getPredictionRecommendation(mlPrediction) {
  if (mlPrediction?.status !== "high_risk") {
    return mlPrediction?.recommendation || "Нет данных";
  }

  return "Рекомендуется создать или обновить резервную копию важных данных, провести расширенную SMART-диагностику и наблюдать за динамикой показателей.";
}

function formatSourceValue(value) {
  if (value === null || value === undefined || value === "") {
    return "Нет данных";
  }
  if (typeof value === "boolean") {
    return value ? "Да" : "Нет";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function buildMotherboardLabel(configuration) {
  const manufacturer = getObjectField(configuration?.motherboard, "manufacturer");
  const model = getObjectField(configuration?.motherboard, "model", "product");
  return [manufacturer, model].filter(Boolean).join(" ").trim() || null;
}

function buildBiosLabel(configuration) {
  const version = getObjectField(configuration?.bios, "version");
  const releaseDate = getObjectField(configuration?.bios, "release_date");
  return [version, releaseDate].filter(Boolean).join(" · ").trim() || null;
}

function buildOsLabel(configuration) {
  const name = getObjectField(configuration?.os, "name");
  const version = getObjectField(configuration?.os, "version");
  const architecture = getObjectField(configuration?.os, "architecture");
  return [name, version, architecture].filter(Boolean).join(" · ").trim() || null;
}

function buildConfigurationItems(configuration, drivesCount, device) {
  const items = [
    {
      label: "CPU",
      value: getObjectField(configuration?.cpu, "name") || device?.cpu || null,
    },
    {
      label: "GPU",
      value: getObjectField(configuration?.gpu, "name") || device?.gpu || null,
    },
    {
      label: "RAM",
      value: (() => {
        const total = getObjectField(configuration?.ram, "total_gb");
        return total !== null && total !== undefined ? formatMetric(total, "ГБ", 1) : null;
      })(),
    },
    {
      label: "Модулей RAM",
      value: (() => {
        const count = getObjectField(configuration?.ram, "modules_count");
        return count !== null && count !== undefined ? String(count) : null;
      })(),
    },
    {
      label: "Накопителей",
      value: drivesCount > 0 ? String(drivesCount) : null,
    },
    {
      label: "ОС",
      value: buildOsLabel(configuration),
    },
    {
      label: "Материнская плата",
      value: buildMotherboardLabel(configuration),
    },
    {
      label: "BIOS",
      value: buildBiosLabel(configuration),
    },
  ];

  return items.filter((item) => item.value);
}

function StatusBadge({ status, text }) {
  return (
    <span className={getStatusClass(status)}>
      {text || formatStatusLabel(status)}
    </span>
  );
}

function ValuePair({ label, value }) {
  return (
    <div className="key-value">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ComponentCard({ card }) {
  const isCritical = card?.status === "critical";
  const details = card?.details || {};
  const config = CARD_CONFIG[card?.id] || {
    title: card?.title || "Компонент",
    primaryLabel: "Показатель",
    secondaryLabel: "Дополнительно",
    detailLabels: {},
    detailUnits: {},
  };

  return (
    <article className={`metric-card ${isCritical ? "metric-card-critical" : ""}`}>
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">Компоненты</p>
          <h3>{config.title}</h3>
        </div>
        <StatusBadge status={card?.status} />
      </div>

      <div className="metric-card-values">
        <div>
          <span className="metric-label">{config.primaryLabel}</span>
          <strong className="metric-value">
            {formatMetric(card?.primary_value, card?.primary_unit)}
          </strong>
        </div>
        <div>
          <span className="metric-label">{config.secondaryLabel}</span>
          <strong className="metric-value">
            {formatMetric(card?.secondary_value, card?.secondary_unit)}
          </strong>
        </div>
      </div>

      <div className="metric-details">
        {Object.entries(details).map(([key, value]) => {
          const label = config.detailLabels[key] || key.replaceAll("_", " ");
          const unit = config.detailUnits[key] || "";
          const formattedValue = typeof value === "boolean"
            ? formatBoolean(value)
            : formatMetric(value, unit);

          return (
            <ValuePair
              key={key}
              label={label}
              value={formattedValue}
            />
          );
        })}
      </div>
    </article>
  );
}

function OverviewDriveCard({ summary }) {
  return (
    <article className={`metric-card ${summary.problemCount > 0 ? "metric-card-warning" : ""}`}>
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">Накопители</p>
          <h3>Краткая сводка</h3>
        </div>
        <StatusBadge
          status={summary.problemCount > 0 ? "warning" : "ok"}
          text={summary.problemCount > 0 ? "Требует внимания" : "Норма"}
        />
      </div>

      <div className="metric-details overview-drive-details">
        <ValuePair label="Накопителей" value={String(summary.total || 0)} />
        <ValuePair label="Требуют внимания" value={String(summary.problemCount || 0)} />
        <ValuePair label="ML-индикатор" value={summary.mlIndicator} />
        <ValuePair label="Причина" value={summary.topReason} />
      </div>
    </article>
  );
}

function ScoreDetailsPanel({ items }) {
  if (!Array.isArray(items) || items.length === 0) {
    return null;
  }

  return (
    <div className="score-details-panel">
      <p className="eyebrow">Почему такая оценка</p>
      <div className="score-details-list">
        {items.slice(0, 3).map((item, index) => (
          <article
            key={`${item?.component || "score"}-${item?.label || index}`}
            className="score-detail-item"
          >
            <div className="score-detail-top">
              <strong>{item?.label || "Причина"}</strong>
              <span>-{item?.penalty || 0}</span>
            </div>
            <p>{item?.reason || "Нет данных"}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function MessageList({ title, items, emptyText }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <span className="panel-count">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="empty-state">{emptyText}</p>
      ) : (
        <div className="message-list">
          {items.map((item, index) => (
            <article
              key={`${title}-${index}`}
              className={`message-card message-${item?.level || item?.priority || "neutral"}`}
            >
              <div className="message-card-top">
                <strong>{item?.component || "Система"}</strong>
                <span>{item?.metric || item?.priority || "инфо"}</span>
              </div>
              <p>{item?.message || item?.reason || "Нет данных"}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ChartSection({ chartKey, chart }) {
  const series = chart?.series || [];
  const hasAnyPoints = series.some((item) =>
    (item?.points || []).some((point) => point?.value !== null && point?.value !== undefined)
  );
  const chartData = [];

  if (hasAnyPoints) {
    const maxPointsLength = Math.max(...series.map((item) => item.points?.length || 0));
    for (let index = 0; index < maxPointsLength; index += 1) {
      const row = { time: null };
      for (const item of series) {
        const point = item?.points?.[index];
        if (point?.time && !row.time) {
          row.time = point.time;
        }
        row[item.key] = point?.value ?? null;
      }
      chartData.push(row);
    }
  }

  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Графики</p>
          <h3>{CHART_TITLES[chartKey] || chart?.title || chartKey}</h3>
        </div>
        <span className="chart-meta">
          {formatChartType(chart?.type)} {chart?.unit ? `· ${chart.unit}` : ""}
        </span>
      </div>

      {!hasAnyPoints ? (
        <p className="empty-state">Нет данных для графика.</p>
      ) : (
        <div className="chart-canvas">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 12, right: 24, bottom: 8, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.14)" />
              <XAxis
                dataKey="time"
                allowDuplicatedCategory={false}
                tickFormatter={formatShortTime}
                stroke="#94a3b8"
                minTickGap={24}
              />
              <YAxis stroke="#94a3b8" width={56} />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid rgba(148, 163, 184, 0.2)",
                  borderRadius: "14px",
                }}
                formatter={(value) => formatMetric(value, chart?.unit, 2)}
                labelFormatter={(value) => formatDateTime(value)}
              />
              <Legend />
              {series.map((item, index) => (
                <Line
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.name}
                  stroke={CHART_COLORS[index % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function ConfigurationPanel({ items }) {
  return (
    <section className="panel configuration-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Конфигурация ПК</p>
          <h3>Паспортная информация</h3>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="empty-state">Данные о конфигурации пока недоступны.</p>
      ) : (
        <div className="configuration-grid">
          {items.map((item) => (
            <ValuePair key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
      )}
    </section>
  );
}

function ComponentCategoryCard({ item, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`component-category-card ${selected ? "component-category-card-active" : ""}`}
      onClick={onSelect}
    >
      <div className="component-category-header">
        <div>
          <p className="eyebrow">Категория</p>
          <h3>{item.title}</h3>
        </div>
        <StatusBadge status={item.status} />
      </div>
      <p className="component-category-summary">{item.summary}</p>
    </button>
  );
}

function DriveCard({ drive, index, mlPrediction }) {
  const driveName = getObjectField(drive, "model", "name") || "Нет данных";
  const smartHealth = getObjectField(drive, "health_status") || "Нет данных";
  const driveProblem = isProblemDrive(drive, mlPrediction);
  const detailRows = getDriveDetailRows(drive);
  const smartState = driveProblem ? "critical" : getSmartHealthState(smartHealth);
  const driveReason = driveProblem ? getDriveProblemReason(drive, mlPrediction) : null;

  return (
    <article className={`drive-card ${driveProblem ? "drive-card-problem" : ""}`}>
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">Накопители</p>
          <h3>{driveName}</h3>
        </div>
        <StatusBadge status={smartState} text={smartHealth} />
      </div>

      {driveReason ? (
        <div className="drive-note">
          <strong>Требует внимания</strong>
          <p>{driveReason}</p>
        </div>
      ) : null}

      <div className="drive-details-grid">
        {detailRows.commonRows.map((row) => (
          <ValuePair key={`${getDriveKey(drive, index)}-${row.label}`} label={row.label} value={row.value} />
        ))}
        {detailRows.extraRows.map((row) => (
          <ValuePair key={`${getDriveKey(drive, index)}-${row.label}`} label={row.label} value={row.value} />
        ))}
      </div>

      {detailRows.extraRows.length === 0 ? (
        <p className="drive-empty-note">Дополнительные SMART-данные недоступны.</p>
      ) : null}
    </article>
  );
}

function DiagnosticStatusCard({ title, status, detail }) {
  return (
    <article className="diagnostic-card">
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">Диагностика</p>
          <h3>{title}</h3>
        </div>
        <StatusBadge status={status} />
      </div>
      <p className="diagnostic-detail">{detail}</p>
    </article>
  );
}

function DiagnosticsSourceCard({ title, payload }) {
  const entries = payload && typeof payload === "object" ? Object.entries(payload) : [];

  return (
    <section className="panel diagnostics-source-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Подробности источников</p>
          <h3>{title}</h3>
        </div>
      </div>

      {entries.length === 0 ? (
        <p className="empty-state">Нет данных по источникам.</p>
      ) : (
        <div className="diagnostics-grid">
          {entries.map(([key, value]) => (
            <ValuePair key={`${title}-${key}`} label={key} value={formatSourceValue(value)} />
          ))}
        </div>
      )}
    </section>
  );
}

function App() {
  const [activeSection, setActiveSection] = useState("overview");
  const [selectedComponent, setSelectedComponent] = useState("cpu");
  const [showDiagnosticsDetails, setShowDiagnosticsDetails] = useState(false);
  const [dashboard, setDashboard] = useState(null);
  const [charts, setCharts] = useState(null);
  const [health, setHealth] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const [backendNotice, setBackendNotice] = useState("");
  const requestInFlightRef = useRef(false);
  const abortControllerRef = useRef(null);
  const activeRequestModeRef = useRef(null);
  const pendingManualRefreshRef = useRef(false);
  const loadDataRef = useRef(null);

  async function loadData({ mode = "initial" } = {}) {
    if (requestInFlightRef.current) {
      if (mode === "manual") {
        pendingManualRefreshRef.current = true;
      }
      return;
    }

    requestInFlightRef.current = true;
    activeRequestModeRef.current = mode;

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    if (mode === "initial") {
      setLoading(true);
    }
    if (mode === "manual") {
      setManualRefreshing(true);
    }

    let shouldScheduleManualRefresh = false;

    try {
      const requestOptions = { signal: abortController.signal };
      const results = await Promise.allSettled([
        getDashboard(requestOptions),
        getDashboardCharts(120, requestOptions),
        getHealth(requestOptions),
        getSystemStatus(requestOptions),
      ]);

      const [dashboardResult, chartsResult, healthResult, systemStatusResult] = results;
      const failedEndpoints = [];

      if (dashboardResult.status === "fulfilled") {
        setDashboard(dashboardResult.value);
      } else {
        failedEndpoints.push("/dashboard");
      }

      if (chartsResult.status === "fulfilled") {
        setCharts(chartsResult.value);
      } else {
        failedEndpoints.push("/dashboard/charts");
      }

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      } else {
        failedEndpoints.push("/health");
      }

      if (systemStatusResult.status === "fulfilled") {
        setSystemStatus(systemStatusResult.value);
      } else {
        failedEndpoints.push("/system/status");
      }

      if (failedEndpoints.length === 0) {
        setBackendNotice("");
      } else {
        setBackendNotice(
          `Backend отвечает не полностью. Не удалось обновить: ${failedEndpoints.join(", ")}.`,
        );
      }
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }

      const details = requestError instanceof Error
        ? requestError.message
        : "Не удалось загрузить данные панели.";
      setBackendNotice(details);
    } finally {
      const finishedMode = activeRequestModeRef.current;
      shouldScheduleManualRefresh =
        pendingManualRefreshRef.current && finishedMode !== "manual";

      requestInFlightRef.current = false;
      activeRequestModeRef.current = null;
      abortControllerRef.current = null;
      pendingManualRefreshRef.current = false;
      setLoading(false);

      if (finishedMode === "manual") {
        setManualRefreshing(false);
      } else if (!shouldScheduleManualRefresh) {
        setManualRefreshing(false);
      }
    }

    if (shouldScheduleManualRefresh) {
      void loadData({ mode: "manual" });
    }
  }

  useEffect(() => {
    loadDataRef.current = loadData;
  });

  useEffect(() => {
    const initialLoadId = window.setTimeout(() => {
      void loadDataRef.current?.({ mode: "initial" });
    }, 0);

    const intervalId = window.setInterval(() => {
      void loadDataRef.current?.({ mode: "background" });
    }, 10000);

    return () => {
      window.clearTimeout(initialLoadId);
      window.clearInterval(intervalId);
      abortControllerRef.current?.abort();
    };
  }, []);

  const cards = dashboard?.cards || [];
  const cardsById = Object.fromEntries(
    cards
      .filter((card) => card && card.id)
      .map((card) => [card.id, card]),
  );
  const componentCards = cards.filter((card) => ["cpu", "gpu", "ram"].includes(card?.id));
  const warnings = dashboard?.warnings?.items || [];
  const recommendations = dashboard?.recommendations?.items || [];
  const normalizedWarnings = warnings.map(normalizeWarningItem);
  const normalizedRecommendations = recommendations.map(normalizeRecommendationItem);
  const visibleCharts = buildVisibleCharts(charts?.charts);
  const healthChecks = health?.checks || {};
  const externalTools = healthChecks?.external_tools || dashboard?.external_tools || {};
  const mlPrediction = dashboard?.ml_prediction || {};
  const sourceDrive = mlPrediction?.source_drive || {};
  const drives = dashboard?.smart?.drives || [];
  const device = dashboard?.device || {};
  const configuration = dashboard?.configuration || {
    cpu: { name: device?.cpu || null },
    gpu: { name: device?.gpu || null },
    ram: {
      total_gb: device?.ram_total_gb || null,
      modules_count: device?.ram_modules_count || null,
    },
    motherboard: device?.motherboard || {},
    bios: device?.bios || {},
    os: device?.os || {},
    drives_count: drives.length,
  };
  const updatedAt = dashboard?.overall?.updated_at || charts?.updated_at;
  const lhmHealthState = getToolHealthState(externalTools?.libre_hardware_monitor);
  const smartctlHealthState = getToolHealthState(externalTools?.smartctl);
  const motherboardLabel = buildMotherboardLabel(configuration);
  const biosLabel = buildBiosLabel(configuration);
  const configurationItems = buildConfigurationItems(configuration, drives.length, device);
  const driveSummary = getDriveSummary(drives, mlPrediction);
  const fallbackOverviewStatus = getOverviewStatus(
    componentCards,
    drives,
    mlPrediction,
    health,
    healthChecks,
  );
  const overviewStatus = {
    status: dashboard?.overall?.status || fallbackOverviewStatus.status,
    label: formatStatusLabel(dashboard?.overall?.status || fallbackOverviewStatus.status),
    reason: dashboard?.overall?.reason || fallbackOverviewStatus.reason,
  };
  const interfaceHealthScore = Number.isFinite(Number(dashboard?.overall?.health_score))
    ? Number(dashboard?.overall?.health_score)
    : getUiHealthScore(overviewStatus.status);
  const scoreDetails = Array.isArray(dashboard?.overall?.score_details)
    ? dashboard.overall.score_details
    : [];
  const visibleDrive = sourceDrive && Object.keys(sourceDrive).length > 0 ? sourceDrive : null;
  const coolingRpm = getObjectField(systemStatus?.sensors?.summary, "system_fan_rpm");

  const componentItems = [
    {
      id: "cpu",
      title: "Процессор",
      status: cardsById.cpu?.status || "unknown",
      summary: getObjectField(configuration?.cpu, "name") || "Нет данных",
    },
    {
      id: "gpu",
      title: "Видеокарта",
      status: cardsById.gpu?.status || "unknown",
      summary: getObjectField(configuration?.gpu, "name") || "Нет данных",
    },
    {
      id: "ram",
      title: "Оперативная память",
      status: cardsById.ram?.status || "unknown",
      summary: (() => {
        const total = getObjectField(configuration?.ram, "total_gb");
        return total !== null && total !== undefined
          ? `${formatMetric(total, "ГБ", 1)}`
          : "Нет данных";
      })(),
    },
    {
      id: "drives",
      title: "Накопители",
      status: driveSummary.problemCount > 0 ? "warning" : "ok",
      summary: `${driveSummary.total} шт.`,
    },
    {
      id: "cooling",
      title: "Охлаждение",
      status: healthChecks?.sensors?.status === "error"
        ? "error"
        : coolingRpm
          ? "ok"
          : "unknown",
      summary: coolingRpm ? formatMetric(coolingRpm, "RPM") : "Нет данных",
    },
    {
      id: "motherboard",
      title: "Материнская плата",
      status: motherboardLabel ? "ok" : "unknown",
      summary: motherboardLabel || "Данные пока недоступны",
    },
  ];

  const cpuCharts = [
    buildFocusedChart(visibleCharts, "usage", ["cpu_usage"], "Нагрузка CPU", "%"),
    buildFocusedChart(visibleCharts, "temperatures", ["cpu_temperature"], "Температура CPU", "°C"),
    buildFocusedChart(visibleCharts, "power", ["cpu_power"], "Потребление CPU", "W"),
  ].filter(Boolean);

  const gpuCharts = [
    buildFocusedChart(visibleCharts, "usage", ["gpu_usage"], "Нагрузка GPU", "%"),
    buildFocusedChart(visibleCharts, "temperatures", ["gpu_temperature"], "Температура GPU", "°C"),
    buildFocusedChart(visibleCharts, "power", ["gpu_power"], "Потребление GPU", "W"),
  ].filter(Boolean);

  const ramCharts = [
    buildFocusedChart(visibleCharts, "usage", ["ram_usage"], "Занятость RAM", "%"),
    buildFocusedChart(visibleCharts, "temperatures", ["ram_temperature"], "Температура RAM", "°C"),
  ].filter(Boolean);

  const coolingCharts = [
    buildFocusedChart(visibleCharts, "cooling", ["system_fan_rpm"], "Скорость системного вентилятора", "RPM"),
  ].filter(Boolean);

  function renderOverviewSection() {
    return (
      <>
        <section className="overview-grid">
          {componentCards.map((card) => (
            <ComponentCard key={card.id} card={card} />
          ))}
          <OverviewDriveCard summary={driveSummary} />
        </section>

        <section className="panel summary-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Обзор</p>
              <h3>Общее состояние компьютера</h3>
            </div>
            <StatusBadge status={overviewStatus.status} text={overviewStatus.label} />
          </div>

          <div className="summary-grid">
            <ValuePair label="Условная оценка состояния" value={formatMetric(interfaceHealthScore)} />
            <ValuePair label="Причина" value={overviewStatus.reason} />
            <ValuePair label="Обновлено" value={formatUpdatedTime(updatedAt)} />
            <ValuePair label="Сервер приложения" value={formatStatusLabel(health?.status)} />
          </div>
          <ScoreDetailsPanel items={scoreDetails} />
        </section>

        <ConfigurationPanel items={configurationItems} />

        <section className="lists-grid">
          <MessageList
            title="Предупреждения"
            items={normalizedWarnings}
            emptyText="Предупреждений сейчас нет."
          />
          <MessageList
            title="Рекомендации"
            items={normalizedRecommendations}
            emptyText="Рекомендаций сейчас нет."
          />
        </section>
      </>
    );
  }

  function renderComponentDetails() {
    if (selectedComponent === "cpu") {
      return (
        <section className="panel component-detail-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Компоненты</p>
              <h3>Процессор</h3>
            </div>
          </div>
          <div className="component-info-grid">
            <ValuePair label="Модель" value={getObjectField(configuration?.cpu, "name") || "Нет данных"} />
            <ValuePair label="Нагрузка" value={formatMetric(cardsById.cpu?.details?.usage_percent, "%")} />
            <ValuePair label="Температура" value={formatMetric(cardsById.cpu?.details?.temperature_celsius, "°C")} />
            <ValuePair label="Потребление" value={formatMetric(cardsById.cpu?.details?.power_watts, "Вт")} />
            <ValuePair label="Ядра / потоки" value={(() => {
              const cores = getObjectField(configuration?.cpu, "physical_cores");
              const threads = getObjectField(configuration?.cpu, "threads", "logical_processors");
              if (cores === null && threads === null) {
                return "Нет данных";
              }
              return `${cores ?? "?"} / ${threads ?? "?"}`;
            })()} />
            <ValuePair label="Макс. частота" value={formatMetric(getObjectField(configuration?.cpu, "max_clock_mhz"), "МГц")} />
          </div>
          <div className="component-charts-grid">
            {cpuCharts.map((chart) => (
              <ChartSection key={chart.title} chartKey={chart.title} chart={chart} />
            ))}
          </div>
        </section>
      );
    }

    if (selectedComponent === "gpu") {
      return (
        <section className="panel component-detail-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Компоненты</p>
              <h3>Видеокарта</h3>
            </div>
          </div>
          <div className="component-info-grid">
            <ValuePair label="Модель" value={getObjectField(configuration?.gpu, "name") || "Нет данных"} />
            <ValuePair label="Нагрузка" value={formatMetric(cardsById.gpu?.details?.usage_percent, "%")} />
            <ValuePair label="Температура" value={formatMetric(cardsById.gpu?.details?.temperature_celsius, "°C")} />
            <ValuePair label="Потребление" value={formatMetric(cardsById.gpu?.details?.power_watts, "Вт")} />
            <ValuePair label="Вентилятор" value={formatMetric(cardsById.gpu?.details?.fan_percent, "%")} />
            <ValuePair
              label="Память"
              value={(() => {
                const used = cardsById.gpu?.details?.memory_used_mb;
                const total = cardsById.gpu?.details?.memory_total_mb;
                if (used === null || used === undefined || total === null || total === undefined) {
                  return "Нет данных";
                }
                return `${formatMetric(used, "МБ")} / ${formatMetric(total, "МБ")}`;
              })()}
            />
            <ValuePair label="Драйвер" value={getObjectField(configuration?.gpu, "driver_version") || "Нет данных"} />
            <ValuePair label="Видеопамять" value={formatMetric(getObjectField(configuration?.gpu, "adapter_ram_gb"), "ГБ")} />
          </div>
          <div className="component-charts-grid">
            {gpuCharts.map((chart) => (
              <ChartSection key={chart.title} chartKey={chart.title} chart={chart} />
            ))}
          </div>
        </section>
      );
    }

    if (selectedComponent === "ram") {
      return (
        <section className="panel component-detail-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Компоненты</p>
              <h3>Оперативная память</h3>
            </div>
          </div>
          <div className="component-info-grid">
            <ValuePair label="Занято" value={formatMetric(cardsById.ram?.details?.usage_percent, "%")} />
            <ValuePair label="Общий объём" value={formatMetric(getObjectField(configuration?.ram, "total_gb"), "ГБ")} />
            <ValuePair label="Модулей" value={(() => {
              const count = getObjectField(configuration?.ram, "modules_count");
              return count !== null && count !== undefined ? String(count) : "Нет данных";
            })()} />
            <ValuePair label="Температура" value={formatMetric(cardsById.ram?.details?.temperature_celsius, "°C")} />
          </div>
          <div className="component-charts-grid">
            {ramCharts.map((chart) => (
              <ChartSection key={chart.title} chartKey={chart.title} chart={chart} />
            ))}
          </div>
        </section>
      );
    }

    if (selectedComponent === "drives") {
      return (
        <section className="panel component-detail-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Компоненты</p>
              <h3>Накопители</h3>
            </div>
          </div>
          <div className="component-info-grid">
            <ValuePair label="Накопителей" value={String(driveSummary.total || 0)} />
            <ValuePair label="Требуют внимания" value={String(driveSummary.problemCount || 0)} />
            <ValuePair label="ML-индикатор" value={driveSummary.mlIndicator} />
            <ValuePair label="Причина" value={driveSummary.topReason} />
          </div>
          {renderDrivesSection()}
        </section>
      );
    }

    if (selectedComponent === "cooling") {
      return (
        <section className="panel component-detail-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Компоненты</p>
              <h3>Охлаждение</h3>
            </div>
          </div>
          <div className="component-info-grid">
            <ValuePair label="Системный вентилятор" value={formatMetric(coolingRpm, "RPM")} />
          </div>
          <div className="component-charts-grid">
            {coolingCharts.map((chart) => (
              <ChartSection key={chart.title} chartKey={chart.title} chart={chart} />
            ))}
          </div>
        </section>
      );
    }

    return (
      <section className="panel component-detail-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Компоненты</p>
            <h3>Материнская плата</h3>
          </div>
        </div>
        {motherboardLabel ? (
          <div className="component-info-grid">
            <ValuePair label="Материнская плата" value={motherboardLabel} />
            <ValuePair label="BIOS" value={biosLabel || "Нет данных"} />
          </div>
        ) : (
          <p className="empty-state">Данные по материнской плате пока недоступны.</p>
        )}
      </section>
    );
  }

  function renderComponentsSection() {
    return (
      <div className="components-stack">
        <section className="component-category-grid">
          {componentItems.map((item) => (
            <ComponentCategoryCard
              key={item.id}
              item={item}
              selected={selectedComponent === item.id}
              onSelect={() => setSelectedComponent(item.id)}
            />
          ))}
        </section>
        {renderComponentDetails()}
      </div>
    );
  }

  function renderDrivesSection() {
    return (
      <section className="panel drives-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Накопители</p>
            <h3>Состояние накопителей</h3>
          </div>
          <span className="panel-count">{drives.length}</span>
        </div>

        {drives.length === 0 ? (
          <p className="empty-state">Нет данных по накопителям.</p>
        ) : (
          <div className="drives-grid">
            {drives.map((drive, index) => (
              <DriveCard
                key={`${getDriveKey(drive, index)}-${index}`}
                drive={drive}
                index={index}
                mlPrediction={mlPrediction}
              />
            ))}
          </div>
        )}
      </section>
    );
  }

  function renderPredictionSection() {
    const predictionStatus = mlPrediction?.status === "high_risk" ? "warning" : mlPrediction?.status;
    const predictionStatusText = mlPrediction?.status === "high_risk"
      ? "Повышенный риск"
      : formatStatusLabel(mlPrediction?.status);

    return (
      <section className="panel spotlight-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Прогноз</p>
            <h3>Прогноз отказа накопителя</h3>
          </div>
          <StatusBadge status={predictionStatus} text={predictionStatusText} />
        </div>

        {!visibleDrive ? (
          <p className="empty-state">Нет данных по анализируемому накопителю.</p>
        ) : (
          <>
            <div className="spotlight-grid">
              <div className="spotlight-risk">
                <span className="metric-label">Оценка модели</span>
                <strong className="risk-value">
                  {formatMetric(mlPrediction?.risk_percent, "%", 2)}
                </strong>
              </div>
              <ValuePair
                label="Накопитель"
                value={getObjectField(sourceDrive, "name", "model") || "Нет данных"}
              />
              <ValuePair
                label="Тип"
                value={normalizeDriveType(sourceDrive) || "Нет данных"}
              />
              <ValuePair
                label="Интерфейс"
                value={getObjectField(sourceDrive, "interface", "interface_type", "bus_type") || "Нет данных"}
              />
              <ValuePair
                label="Модель"
                value={getObjectField(sourceDrive, "model", "name") || "Нет данных"}
              />
              <ValuePair label="Объём" value={formatDriveCapacity(sourceDrive)} />
              <ValuePair
                label="Температура"
                value={formatMetric(getObjectField(sourceDrive, "temperature_celsius", "temperature"), "°C")}
              />
              <ValuePair
                label="Часы работы"
                value={formatMetric(getObjectField(sourceDrive, "power_on_hours", "hours"))}
              />
              <ValuePair
                label="Переназначенные сектора"
                value={formatMetric(getObjectField(sourceDrive, "reallocated_sectors_count", "reallocated_sectors", "reallocated_sector_count"))}
              />
              <ValuePair
                label="Рекомендация"
                value={getPredictionRecommendation(mlPrediction)}
              />
            </div>

            <div className="ml-note">
              <strong>Повышенный риск отказа</strong>
              <p>{ML_RISK_NOTE}</p>
            </div>
          </>
        )}
      </section>
    );
  }

  function renderChartsSection() {
    return (
      <div className="charts-stack">
        <section className="panel charts-intro-panel">
          <p className="charts-intro-text">
            Это общий исторический обзор системных метрик. Он помогает увидеть динамику нагрузки,
            температур, энергопотребления и состояния накопителя во времени.
          </p>
        </section>
        <section className="charts-grid">
          {Object.entries(visibleCharts).map(([chartKey, chart]) => (
            <ChartSection key={chartKey} chartKey={chartKey} chart={chart} />
          ))}
        </section>
      </div>
    );
  }

  function renderDiagnosticsSection() {
    const diagnosticsItems = [
      {
        title: "Сервер приложения",
        status: healthChecks?.backend?.status || "unknown",
        detail: "Отвечает за API и обновление данных dashboard.",
      },
      {
        title: "Локальная база данных",
        status: healthChecks?.database?.status || "unknown",
        detail: healthChecks?.database?.type === "sqlite"
          ? "Используется локальная SQLite-база."
          : "Используется настроенная внешняя база данных.",
      },
      {
        title: "Модель прогнозирования",
        status: healthChecks?.ml_model?.status || "unknown",
        detail: "Отвечает за ML-оценку риска отказа накопителя.",
      },
      {
        title: "Датчики оборудования",
        status: lhmHealthState,
        detail: `Технический статус: ${formatStatusLabel(externalTools?.libre_hardware_monitor?.status)}.`,
      },
      {
        title: "SMART-диагностика",
        status: smartctlHealthState,
        detail: `Технический статус: ${formatStatusLabel(externalTools?.smartctl?.status)}.`,
      },
      {
        title: "Сбор датчиков",
        status: healthChecks?.sensors?.status || "unknown",
        detail: "Показывает доступность текущих сенсоров нагрузки, температуры и питания.",
      },
      {
        title: "SMART-данные",
        status: healthChecks?.smart?.status || "unknown",
        detail: "Показывает доступность паспортных и диагностических данных накопителей.",
      },
    ];

    return (
      <div className="diagnostics-stack">
        <section className="diagnostic-card-grid">
          {diagnosticsItems.map((item) => (
            <DiagnosticStatusCard
              key={item.title}
              title={item.title}
              status={item.status}
              detail={item.detail}
            />
          ))}
        </section>

        <section className="panel diagnostics-toggle-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Диагностика</p>
              <h3>Подробности источников</h3>
            </div>
            <button
              type="button"
              className="secondary-action-button"
              onClick={() => setShowDiagnosticsDetails((value) => !value)}
            >
              {showDiagnosticsDetails ? "Скрыть подробности" : "Показать подробности"}
            </button>
          </div>

          {showDiagnosticsDetails ? (
            <div className="diagnostics-panels-grid">
              <DiagnosticsSourceCard
                title="Источники сенсоров"
                payload={systemStatus?.sensors?.sources}
              />
              <DiagnosticsSourceCard
                title="Источники SMART"
                payload={systemStatus?.smart?.sources}
              />
            </div>
          ) : (
            <p className="empty-state">
              Детали источников скрыты, чтобы не перегружать экран технической информацией.
            </p>
          )}
        </section>
      </div>
    );
  }

  function renderActiveSection() {
    switch (activeSection) {
      case "components":
        return renderComponentsSection();
      case "prediction":
        return renderPredictionSection();
      case "charts":
        return renderChartsSection();
      case "diagnostics":
        return renderDiagnosticsSection();
      case "overview":
      default:
        return renderOverviewSection();
    }
  }

  return (
    <div className="app-shell">
      <div className="background-glow background-glow-left" />
      <div className="background-glow background-glow-right" />

      <header className="hero panel">
        <div className="hero-copy">
          <p className="eyebrow">Система мониторинга ПК</p>
          <h1>Панель состояния компьютера</h1>
          <div className="hero-meta-grid">
            <ValuePair label="Устройство" value={device?.name || "Локальный ПК"} />
            <ValuePair label="Обновлено" value={formatUpdatedTime(updatedAt)} />
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-status-card">
            <span className="metric-label">Общее состояние</span>
            <StatusBadge status={overviewStatus.status} text={overviewStatus.label} />
            <strong className="health-score">
              {formatMetric(interfaceHealthScore)}
            </strong>
            <span className="metric-label">Условная оценка состояния</span>
            <p className="hero-status-reason">{overviewStatus.reason}</p>
          </div>
          <button
            className="refresh-button"
            type="button"
            onClick={() => void loadData({ mode: "manual" })}
            disabled={loading || manualRefreshing}
          >
            {manualRefreshing ? "Обновление..." : "Обновить"}
          </button>
        </div>
      </header>

      <nav className="section-nav panel" aria-label="Разделы dashboard">
        <div className="section-nav-list">
          {SECTION_ITEMS.filter((section) => section.id !== "drives").map((section) => (
            <button
              key={section.id}
              type="button"
              className={`section-tab ${activeSection === section.id ? "section-tab-active" : ""}`}
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </button>
          ))}
        </div>
      </nav>

      {backendNotice ? (
        <div className="alert-panel">
          <strong>Backend недоступен</strong>
          <br />
          <span className="alert-hint">{backendNotice}</span>
        </div>
      ) : null}

      {loading ? (
        <div className="panel loading-panel">Загрузка панели...</div>
      ) : (
        <main className="section-content">
          {renderActiveSection()}
        </main>
      )}
    </div>
  );
}

export default App;
