import { useCallback, useEffect, useRef, useState } from "react";
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
  usage: "Component Load",
  temperatures: "Component Temperatures",
  power: "Power Draw",
  cooling: "Cooling",
  disk_health: "Disk Health",
};

const STATUS_LABELS = {
  ok: "OK",
  warning: "Warning",
  critical: "Critical",
  unknown: "Unknown",
  error: "Error",
  partial: "Partial",
  high_risk: "High risk",
  normal: "Normal",
  available: "Available",
  started: "Started",
  already_running: "Running",
  disabled: "Disabled",
  not_found: "Not found",
};

function formatStatusLabel(status) {
  if (!status) {
    return "Unknown";
  }
  return STATUS_LABELS[status] || status;
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

function formatMetric(value, unit = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "No data";
  }

  const numericValue = Number(value);
  const formatted = Number.isInteger(numericValue)
    ? numericValue.toString()
    : numericValue.toFixed(digits);

  return unit ? `${formatted} ${unit}` : formatted;
}

function formatDateTime(value) {
  if (!value) {
    return "No data";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
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

  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getStatusClass(status) {
  return `status-badge status-${status || "unknown"}`;
}

function StatusBadge({ status }) {
  return (
    <span className={getStatusClass(status)}>
      {formatStatusLabel(status)}
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

  return (
    <article className={`metric-card ${isCritical ? "metric-card-critical" : ""}`}>
      <div className="metric-card-header">
        <div>
          <p className="eyebrow">{card?.title || "Component"}</p>
          <h3>{card?.id?.toUpperCase() || "N/A"}</h3>
        </div>
        <StatusBadge status={card?.status} />
      </div>

      <div className="metric-card-values">
        <div>
          <span className="metric-label">Primary</span>
          <strong className="metric-value">
            {formatMetric(card?.primary_value, card?.primary_unit)}
          </strong>
        </div>
        <div>
          <span className="metric-label">Secondary</span>
          <strong className="metric-value">
            {formatMetric(card?.secondary_value, card?.secondary_unit)}
          </strong>
        </div>
      </div>

      <div className="metric-details">
        {Object.entries(details).map(([key, value]) => (
          <ValuePair
            key={key}
            label={key.replaceAll("_", " ")}
            value={typeof value === "boolean" ? (value ? "Yes" : "No") : formatMetric(value)}
          />
        ))}
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
                <strong>{item?.component || "System"}</strong>
                <span>{item?.metric || item?.priority || "info"}</span>
              </div>
              <p>{item?.message || item?.reason || "No data"}</p>
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
          <p className="eyebrow">Chart</p>
          <h3>{CHART_TITLES[chartKey] || chart?.title || chartKey}</h3>
        </div>
        <span className="chart-meta">
          {chart?.type || "line"} {chart?.unit ? `· ${chart.unit}` : ""}
        </span>
      </div>

      {!hasAnyPoints ? (
        <p className="empty-state">No chart data available.</p>
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

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [charts, setCharts] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const requestInFlightRef = useRef(false);
  const abortControllerRef = useRef(null);

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (requestInFlightRef.current) {
      return;
    }

    requestInFlightRef.current = true;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

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
      setError("");
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }

      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load dashboard data.",
      );
    } finally {
      requestInFlightRef.current = false;
      abortControllerRef.current = null;
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const initialLoadId = window.setTimeout(() => {
      void loadData();
    }, 0);

    const intervalId = window.setInterval(() => {
      void loadData({ silent: true });
    }, 10000);

    return () => {
      window.clearTimeout(initialLoadId);
      window.clearInterval(intervalId);
      abortControllerRef.current?.abort();
    };
  }, [loadData]);

  const cards = dashboard?.cards || [];
  const warnings = dashboard?.warnings?.items || [];
  const recommendations = dashboard?.recommendations?.items || [];
  const chartsMap = charts?.charts || {};
  const healthChecks = health?.checks || {};
  const externalTools = healthChecks?.external_tools || dashboard?.external_tools || {};
  const mlPrediction = dashboard?.ml_prediction || {};
  const device = dashboard?.device || {};
  const updatedAt = dashboard?.overall?.updated_at || charts?.updated_at;
  const lhmHealthState = getToolHealthState(externalTools?.libre_hardware_monitor);
  const smartctlHealthState = getToolHealthState(externalTools?.smartctl);

  return (
    <div className="app-shell">
      <div className="background-glow background-glow-left" />
      <div className="background-glow background-glow-right" />

      <header className="hero panel">
        <div className="hero-copy">
          <p className="eyebrow">PC Monitoring System</p>
          <h1>Workstation Health Dashboard</h1>
          <p className="hero-text">
            Backend connection: <code>{BACKEND_BASE_URL}</code>
          </p>
          <div className="device-grid">
            <ValuePair label="Device" value={device?.name || "No data"} />
            <ValuePair label="CPU" value={device?.cpu || "No data"} />
            <ValuePair label="GPU" value={device?.gpu || "No data"} />
            <ValuePair label="Updated at" value={formatDateTime(updatedAt)} />
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-status-card">
            <span className="metric-label">Overall status</span>
            <StatusBadge status={dashboard?.overall?.status} />
            <strong className="health-score">
              {dashboard?.overall?.health_score ?? "No data"}
            </strong>
            <span className="metric-label">Health score</span>
          </div>
          <button
            className="refresh-button"
            type="button"
            onClick={() => loadData({ silent: true })}
            disabled={refreshing || loading}
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      {error ? (
        <div className="alert-panel">
          {error}
          <br />
          <span className="alert-hint">
            Make sure Vite is running on <code>http://localhost:5173</code> and the
            backend API is available on <code>{BACKEND_BASE_URL}</code>.
          </span>
        </div>
      ) : null}

      {loading ? (
        <div className="panel loading-panel">Loading dashboard...</div>
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
                <p className="eyebrow">Disk ML forecast</p>
                <h3>SMART failure prediction</h3>
              </div>
              <StatusBadge status={mlPrediction?.status} />
            </div>

            <div className="spotlight-grid">
              <div className="spotlight-risk">
                <span className="metric-label">Risk percent</span>
                <strong className="risk-value">
                  {formatMetric(mlPrediction?.risk_percent, "%", 2)}
                </strong>
              </div>
              <ValuePair
                label="Source drive"
                value={
                  mlPrediction?.source_drive?.name
                  || mlPrediction?.source_drive?.model
                  || "No data"
                }
              />
              <ValuePair
                label="Drive model"
                value={mlPrediction?.source_drive?.model || "No data"}
              />
              <ValuePair
                label="Recommendation"
                value={mlPrediction?.recommendation || "No data"}
              />
            </div>
          </section>

          <section className="panel tools-panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Runtime checks</p>
                <h3>External tools and backend health</h3>
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
                label="Database"
                value={formatStatusLabel(healthChecks?.database?.status)}
              />
              <ValuePair
                label="ML model"
                value={formatStatusLabel(healthChecks?.ml_model?.status)}
              />
            </div>

            <div className="health-chip-row">
              <HealthChip label="Sensors" payload={healthChecks?.sensors} />
              <HealthChip label="SMART" payload={healthChecks?.smart} />
              <HealthChip label="Backend" payload={healthChecks?.backend} />
              <HealthChip label="LHM" payload={{ status: lhmHealthState }} />
              <HealthChip label="smartctl" payload={{ status: smartctlHealthState }} />
            </div>
          </section>

          <section className="charts-grid">
            {Object.entries(chartsMap).map(([chartKey, chart]) => (
              <ChartSection key={chartKey} chartKey={chartKey} chart={chart} />
            ))}
          </section>

          <section className="lists-grid">
            <MessageList
              title="Warnings"
              items={warnings}
              emptyText="No warnings right now."
            />
            <MessageList
              title="Recommendations"
              items={recommendations}
              emptyText="No recommendations right now."
            />
          </section>
        </>
      )}
    </div>
  );
}

export default App;
