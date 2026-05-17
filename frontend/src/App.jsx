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
  BACKEND_BASE_URL,
  getDashboard,
  getDashboardCharts,
  getHealth,
} from "./api/client";

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
  cooling: "Скорость охлаждения",
  disk_health: "Состояние накопителя",
  disk_runtime: "Время работы накопителя",
};

const STATUS_LABELS = {
  ok: "Норма",
  warning: "Предупреждение",
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
  disk: {
    title: "Накопитель",
    primaryLabel: "Занято",
    secondaryLabel: "Температура",
    detailLabels: {
      usage_percent: "Занято",
      temperature_celsius: "Температура",
      drives_count: "Накопителей",
      high_risk: "Риск отказа",
    },
    detailUnits: {
      usage_percent: "%",
      temperature_celsius: "°C",
    },
  },
};

const ML_RISK_NOTE =
  "Прогноз указывает на повышенный риск по SMART-признакам. Это не означает гарантированный отказ, но требует проверки резервных копий и наблюдения за состоянием накопителя.";

function formatStatusLabel(status) {
  if (!status) {
    return "Неизвестно";
  }
  return STATUS_LABELS[status] || status;
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

function formatBoolean(value) {
  if (value === null || value === undefined) {
    return "Нет данных";
  }
  return value ? "Да" : "Нет";
}

function formatFailureRisk(value) {
  if (value === null || value === undefined) {
    return "Нет данных";
  }
  return value ? "Высокий риск" : "Норма";
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

  if (!diskHealthChart || !Array.isArray(diskHealthChart.series)) {
    return nextCharts;
  }

  const lifeSeries = diskHealthChart.series.filter((item) => item?.key === "disk_life");
  const runtimeSeries = diskHealthChart.series.filter(
    (item) => item?.key === "disk_power_on_hours",
  );

  if (lifeSeries.length > 0) {
    nextCharts.disk_health = {
      ...diskHealthChart,
      unit: "%",
      series: lifeSeries,
    };
  }

  if (runtimeSeries.length > 0) {
    nextCharts.disk_runtime = {
      title: "Время работы накопителя",
      unit: "ч",
      type: "line",
      series: runtimeSeries.map((item) => ({
        ...item,
        name: "Часы работы",
      })),
    };
  }

  return nextCharts;
}

function getStatusClass(status) {
  return `status-badge status-${status || "unknown"}`;
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
          let formattedValue = formatMetric(value, unit);

          if (typeof value === "boolean") {
            formattedValue = key === "high_risk" ? formatFailureRisk(value) : formatBoolean(value);
          } else if (key === "drives_count") {
            formattedValue = value === null || value === undefined ? "Нет данных" : String(value);
          }

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
  const hasAnyPoints = series.some((item) => (item?.points || []).length > 0);
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

function HealthChip({ label, payload }) {
  return (
    <div className="health-chip">
      <span>{label}</span>
      <strong>{formatStatusLabel(payload?.status)}</strong>
    </div>
  );
}

function DriveCard({ drive }) {
  const driveName = getObjectField(drive, "model", "name") || "Нет данных";
  const driveType = normalizeDriveType(drive);
  const healthStatus = getObjectField(drive, "health_status") || "Нет данных";
  const smartStatus = getSmartHealthState(healthStatus);

  return (
    <article className="drive-card">
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">Накопители</p>
          <h3>{driveName}</h3>
        </div>
        <StatusBadge status={smartStatus} text={healthStatus} />
      </div>

      <div className="drive-details-grid">
        <ValuePair label="Тип" value={driveType} />
        <ValuePair
          label="Интерфейс"
          value={getObjectField(drive, "interface", "interface_type", "bus_type") || "Нет данных"}
        />
        <ValuePair label="Объем" value={formatDriveCapacity(drive)} />
        <ValuePair label="Температура" value={formatMetric(getObjectField(drive, "temperature_celsius"), "°C")} />
        <ValuePair label="Состояние SMART" value={healthStatus} />
        <ValuePair label="Часы работы" value={formatMetric(getObjectField(drive, "power_on_hours"))} />
        <ValuePair
          label="Переназначенные сектора"
          value={formatMetric(getObjectField(drive, "reallocated_sectors_count", "reallocated_sectors", "reallocated_sector_count"))}
        />
        <ValuePair
          label="Ожидающие сектора"
          value={formatMetric(getObjectField(drive, "current_pending_sector_count"))}
        />
        <ValuePair
          label="Ошибки CRC"
          value={formatMetric(getObjectField(drive, "udma_crc_error_count"))}
        />
      </div>
    </article>
  );
}

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [charts, setCharts] = useState(null);
  const [health, setHealth] = useState(null);
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
        setManualRefreshing(true);
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
      const [dashboardPayload, chartsPayload, healthPayload] = await Promise.all([
        getDashboard(requestOptions),
        getDashboardCharts(120, requestOptions),
        getHealth(requestOptions),
      ]);

      setDashboard(dashboardPayload);
      setCharts(chartsPayload);
      setHealth(healthPayload);
      setBackendNotice("");
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
      setLoading(false);

      if (finishedMode === "manual") {
        setManualRefreshing(false);
      }

      if (shouldScheduleManualRefresh) {
        pendingManualRefreshRef.current = false;
      } else {
        pendingManualRefreshRef.current = false;
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
  const warnings = dashboard?.warnings?.items || [];
  const recommendations = dashboard?.recommendations?.items || [];
  const visibleCharts = buildVisibleCharts(charts?.charts);
  const healthChecks = health?.checks || {};
  const externalTools = healthChecks?.external_tools || dashboard?.external_tools || {};
  const mlPrediction = dashboard?.ml_prediction || {};
  const sourceDrive = mlPrediction?.source_drive || {};
  const drives = dashboard?.smart?.drives || [];
  const device = dashboard?.device || {};
  const updatedAt = dashboard?.overall?.updated_at || charts?.updated_at;
  const lhmHealthState = getToolHealthState(externalTools?.libre_hardware_monitor);
  const smartctlHealthState = getToolHealthState(externalTools?.smartctl);

  const driveType = normalizeDriveType(sourceDrive);
  const driveInterface = getObjectField(sourceDrive, "interface", "interface_type", "bus_type");
  const driveModel = getObjectField(sourceDrive, "model", "name");
  const driveTemperature = getObjectField(sourceDrive, "temperature_celsius", "temperature");
  const drivePowerOnHours = getObjectField(sourceDrive, "power_on_hours", "hours");
  const driveReallocatedSectors = getObjectField(
    sourceDrive,
    "reallocated_sectors_count",
    "reallocated_sectors",
    "reallocated_sector_count",
  );
  const optionalDeviceFields = [
    { label: "ОЗУ", value: getObjectField(device, "ram", "ram_total", "memory") },
    { label: "Материнская плата", value: getObjectField(device, "motherboard", "mainboard") },
    { label: "ОС", value: getObjectField(device, "os", "operating_system") },
  ].filter((item) => item.value !== null && item.value !== undefined && item.value !== "");

  return (
    <div className="app-shell">
      <div className="background-glow background-glow-left" />
      <div className="background-glow background-glow-right" />

      <header className="hero panel">
        <div className="hero-copy">
          <p className="eyebrow">Система мониторинга ПК</p>
          <h1>Панель состояния компьютера</h1>
          <p className="hero-text">
            Подключение к backend: <code>{BACKEND_BASE_URL}</code>
          </p>
          <div className="device-grid">
            <ValuePair label="Устройство" value={device?.name || "Нет данных"} />
            <ValuePair label="CPU" value={device?.cpu || "Нет данных"} />
            <ValuePair label="GPU" value={device?.gpu || "Нет данных"} />
            <ValuePair label="Обновлено" value={formatUpdatedTime(updatedAt)} />
            {optionalDeviceFields.map((item) => (
              <ValuePair key={item.label} label={item.label} value={String(item.value)} />
            ))}
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-status-card">
            <span className="metric-label">Общее состояние</span>
            <StatusBadge status={dashboard?.overall?.status} />
            <strong className="health-score">
              {dashboard?.overall?.health_score ?? "Нет данных"}
            </strong>
            <span className="metric-label">Оценка состояния</span>
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
        <>
          <section className="cards-grid">
            {cards.map((card) => (
              <ComponentCard key={card.id} card={card} />
            ))}
          </section>

          <section className="panel spotlight-panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Прогноз</p>
                <h3>Прогноз отказа накопителя</h3>
              </div>
              <StatusBadge status={mlPrediction?.status} />
            </div>

            <div className="spotlight-grid">
              <div className="spotlight-risk">
                <span className="metric-label">Риск отказа</span>
                <strong className="risk-value">
                  {formatMetric(mlPrediction?.risk_percent, "%", 2)}
                </strong>
              </div>
              <ValuePair
                label="Накопитель"
                value={getObjectField(sourceDrive, "name", "model") || "Нет данных"}
              />
              <ValuePair label="Тип" value={driveType || "Нет данных"} />
              <ValuePair label="Интерфейс" value={driveInterface || "Нет данных"} />
              <ValuePair label="Модель" value={driveModel || "Нет данных"} />
              <ValuePair label="Объем" value={formatDriveCapacity(sourceDrive)} />
              <ValuePair
                label="Температура"
                value={formatMetric(driveTemperature, "°C")}
              />
              <ValuePair
                label="Часы работы"
                value={formatMetric(drivePowerOnHours)}
              />
              <ValuePair
                label="Переназначенные сектора"
                value={formatMetric(driveReallocatedSectors)}
              />
              <ValuePair
                label="Рекомендация"
                value={mlPrediction?.recommendation || "Нет данных"}
              />
            </div>

            <div className="ml-note">
              <strong>Повышенный риск отказа</strong>
              <p>{ML_RISK_NOTE}</p>
            </div>
          </section>

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
                    key={`${getObjectField(drive, "serial", "name", "model") || "drive"}-${index}`}
                    drive={drive}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="panel tools-panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Диагностика</p>
                <h3>Проверка подсистем</h3>
              </div>
              <StatusBadge status={health?.status} />
            </div>

            <div className="tool-status-grid">
              <ValuePair
                label="Libre Hardware Monitor"
                value={formatStatusLabel(externalTools?.libre_hardware_monitor?.status)}
              />
              <ValuePair
                label="smartctl"
                value={formatStatusLabel(externalTools?.smartctl?.status)}
              />
              <ValuePair
                label="База данных"
                value={formatStatusLabel(healthChecks?.database?.status)}
              />
              <ValuePair
                label="ML-модель"
                value={formatStatusLabel(healthChecks?.ml_model?.status)}
              />
            </div>

            <div className="health-chip-row">
              <HealthChip label="Сенсоры" payload={healthChecks?.sensors} />
              <HealthChip label="SMART" payload={healthChecks?.smart} />
              <HealthChip label="Backend" payload={healthChecks?.backend} />
              <HealthChip label="LHM" payload={{ status: lhmHealthState }} />
              <HealthChip label="smartctl" payload={{ status: smartctlHealthState }} />
            </div>
          </section>

          <section className="charts-grid">
            {Object.entries(visibleCharts).map(([chartKey, chart]) => (
              <ChartSection key={chartKey} chartKey={chartKey} chart={chart} />
            ))}
          </section>

          <section className="lists-grid">
            <MessageList
              title="Предупреждения"
              items={warnings}
              emptyText="Предупреждений сейчас нет."
            />
            <MessageList
              title="Рекомендации"
              items={recommendations}
              emptyText="Рекомендаций сейчас нет."
            />
          </section>
        </>
      )}
    </div>
  );
}

export default App;
