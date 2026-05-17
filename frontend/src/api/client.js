const BACKEND_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const DEV_API_BASE_URL = import.meta.env.DEV ? "/api" : BACKEND_BASE_URL;
const API_BASE_URL = import.meta.env.VITE_API_PROXY_BYPASS === "true"
  ? BACKEND_BASE_URL
  : DEV_API_BASE_URL;

function buildNetworkError(path, error) {
  const details =
    error instanceof Error && error.message ? `: ${error.message}` : "";
  return new Error(
    `Failed to load ${path}. Check the Vite dev server and backend API (${BACKEND_BASE_URL})${details}`,
  );
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
    },
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${path}`);
  }

  return response.json();
}

async function safeRequest(path, options) {
  try {
    return await requestJson(path, options);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw buildNetworkError(path, error);
  }
}

export function getDashboard(options) {
  return safeRequest("/dashboard", options);
}

export function getDashboardCharts(limit = 120, options) {
  return safeRequest(`/dashboard/charts?limit=${limit}`, options);
}

export function getHealth(options) {
  return safeRequest("/health", options);
}

export { BACKEND_BASE_URL };
