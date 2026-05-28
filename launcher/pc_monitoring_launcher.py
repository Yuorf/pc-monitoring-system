from __future__ import annotations

import atexit
import collections
import ctypes
import http.client
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8000
APP_URL = f"http://{HOST}:{PORT}/"
WINDOW_TITLE = "PC Monitoring System"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
WINDOW_MIN_WIDTH = 1024
WINDOW_MIN_HEIGHT = 640
BACKEND_PROCESS_FLAG = "--pcms-backend-process"
APP_ROOT_ENV_NAME = "PCMS_APP_ROOT"
STARTUP_TIMEOUT_SECONDS = 45.0
POLL_INTERVAL_SECONDS = 0.5
ERROR_MESSAGEBOX_ICON = 0x10
READY_LOG_MARKERS = (
    "Application startup complete.",
    "Uvicorn running on",
)
ADMIN_REQUIRED_MESSAGE = (
    "Для полного доступа к аппаратным датчикам и SMART-диагностике "
    "приложение необходимо запустить с правами администратора."
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def show_error(title: str, message: str) -> None:
    print(f"{title}: {message}", file=sys.stderr)
    if os.name != "nt":
        return

    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, ERROR_MESSAGEBOX_ICON)
    except Exception:
        pass


def show_warning(message: str) -> None:
    print(f"Предупреждение: {message}", file=sys.stderr)


def is_user_admin() -> bool:
    if os.name != "nt":
        return True

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    if os.name != "nt":
        return False

    executable = sys.executable
    arguments = (
        sys.argv[1:]
        if is_frozen()
        else [str(Path(__file__).resolve()), *sys.argv[1:]]
    )
    parameters = subprocess.list2cmdline(arguments)

    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            None,
            1,
        )
    except Exception:
        return False

    return result > 32


def ensure_admin_rights() -> int | None:
    if is_user_admin():
        return None

    if relaunch_as_admin():
        return 0

    show_error("PC Monitoring System", ADMIN_REQUIRED_MESSAGE)
    return 1


def iter_candidate_roots() -> list[Path]:
    roots: list[Path] = []

    env_root = os.environ.get(APP_ROOT_ENV_NAME)
    if env_root:
        roots.append(Path(env_root).resolve())

    if is_frozen():
        executable_dir = Path(sys.executable).resolve().parent
        roots.extend([executable_dir, executable_dir / "_internal"])

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass).resolve())
    else:
        roots.append(Path(__file__).resolve().parents[1])

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)

    return unique_roots


def find_app_root() -> Path:
    for root in iter_candidate_roots():
        if (root / "backend" / "app" / "main.py").is_file():
            return root

    searched_paths = "\n".join(str(path) for path in iter_candidate_roots())
    raise FileNotFoundError(
        "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043d\u0430\u0439\u0442\u0438 "
        "\u043a\u043e\u0440\u0435\u043d\u044c \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f. "
        "\u041f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u044b \u043f\u0443\u0442\u0438:\n"
        f"{searched_paths}"
    )


def get_backend_dir(app_root: Path) -> Path:
    return app_root / "backend"


def get_backend_main(app_root: Path) -> Path:
    return get_backend_dir(app_root) / "app" / "main.py"


def get_frontend_dist_index(app_root: Path) -> Path:
    return app_root / "frontend" / "dist" / "index.html"


def check_frontend_dist(app_root: Path) -> None:
    dist_index = get_frontend_dist_index(app_root)
    if dist_index.is_file():
        return

    raise FileNotFoundError(
        "\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d production frontend:\n"
        f"{dist_index}\n\n"
        "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0441\u043e\u0431\u0435\u0440\u0438\u0442\u0435 frontend:\n"
        "powershell -ExecutionPolicy Bypass -File .\\scripts\\build-frontend.ps1"
    )


def build_backend_command() -> list[str]:
    if is_frozen():
        return [sys.executable, BACKEND_PROCESS_FLAG]

    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]


def build_creation_flags() -> int:
    flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags |= subprocess.CREATE_NO_WINDOW
    return flags


class OutputCollector:
    def __init__(self, max_lines: int = 120) -> None:
        self._lines: collections.deque[str] = collections.deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        with self._lock:
            self._lines.append(text)

    def dump(self) -> str:
        with self._lock:
            if not self._lines:
                return "\u041b\u043e\u0433 backend \u043f\u043e\u043a\u0430 \u043f\u0443\u0441\u0442."
            return "\n".join(self._lines)

    def backend_ready(self) -> bool:
        with self._lock:
            return any(
                any(marker in line for marker in READY_LOG_MARKERS)
                for line in self._lines
            )


def start_output_reader(
    process: subprocess.Popen[bytes],
    collector: OutputCollector,
) -> threading.Thread | None:
    if process.stdout is None:
        return None

    def reader() -> None:
        assert process.stdout is not None
        for raw_line in iter(process.stdout.readline, b""):
            collector.append(raw_line.decode("utf-8", errors="replace"))

    thread = threading.Thread(target=reader, name="backend-output-reader", daemon=True)
    thread.start()
    return thread


def spawn_backend_process(app_root: Path) -> tuple[subprocess.Popen[bytes], OutputCollector]:
    backend_dir = get_backend_dir(app_root)
    backend_main = get_backend_main(app_root)
    if not backend_main.is_file():
        raise FileNotFoundError(
            "\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d backend/app/main.py:\n"
            f"{backend_main}"
        )

    collector = OutputCollector()
    env = os.environ.copy()
    env["DEBUG"] = "false"
    env["PYTHONUTF8"] = "1"
    env[APP_ROOT_ENV_NAME] = str(app_root)

    process = subprocess.Popen(
        build_backend_command(),
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=build_creation_flags(),
    )
    start_output_reader(process, collector)
    return process, collector


def backend_health_ready() -> bool:
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(HOST, PORT, timeout=3)
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read()
        return 200 <= response.status < 300
    except (ConnectionError, OSError, TimeoutError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def wait_for_backend_health(process: subprocess.Popen[bytes], collector: OutputCollector) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Backend \u0437\u0430\u0432\u0435\u0440\u0448\u0438\u043b\u0441\u044f \u0434\u043e "
                "\u043e\u0442\u0432\u0435\u0442\u0430 health-check.\n\n"
                f"\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0432\u044b\u0432\u043e\u0434 backend:\n"
                f"{collector.dump()}"
            )

        if backend_health_ready():
            return

        if collector.backend_ready():
            time.sleep(1.0)
            return

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        "Backend \u043d\u0435 \u043e\u0442\u0432\u0435\u0442\u0438\u043b \u043d\u0430 /health "
        "\u0437\u0430 \u043e\u0442\u0432\u0435\u0434\u0451\u043d\u043d\u043e\u0435 \u0432\u0440\u0435\u043c\u044f.\n\n"
        f"\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0432\u044b\u0432\u043e\u0434 backend:\n"
        f"{collector.dump()}"
    )


def open_application_in_browser() -> bool:
    try:
        return bool(webbrowser.open(APP_URL))
    except Exception:
        return False


def open_application_in_webview(*, owns_backend: bool) -> bool:
    try:
        import webview
    except ImportError:
        show_warning("pywebview недоступен. Открываю интерфейс в системном браузере.")
        return False

    try:
        print("Открываю интерфейс во встроенном окне WebView.")
        if owns_backend:
            print("Закройте окно приложения, чтобы завершить backend.")
        webview.create_window(
            WINDOW_TITLE,
            APP_URL,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT),
        )
        webview.start(debug=False)
        return True
    except Exception as error:
        show_warning(
            f"Не удалось запустить WebView ({error}). Открываю интерфейс в системном браузере."
        )
        return False


def terminate_backend_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def register_exit_handlers(process: subprocess.Popen[bytes]) -> None:
    atexit.register(terminate_backend_process, process)

    def handle_signal(signum: int, _frame: object) -> None:
        terminate_backend_process(process)
        raise SystemExit(0)

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            signal.signal(signal_value, handle_signal)


def run_backend_mode() -> int:
    app_root = find_app_root()
    backend_dir = get_backend_dir(app_root)
    backend_main = get_backend_main(app_root)

    if not backend_main.is_file():
        show_error(
            "Launcher backend mode",
            f"\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d backend:\n{backend_main}",
        )
        return 1

    os.environ["DEBUG"] = "false"
    os.environ["PYTHONUTF8"] = "1"
    os.chdir(backend_dir)

    backend_path = str(backend_dir)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT)
    return 0


def run_launcher_mode() -> int:
    app_root = find_app_root()
    check_frontend_dist(app_root)

    if backend_health_ready():
        print("Backend уже запущен. Открываю интерфейс приложения.")
        if open_application_in_webview(owns_backend=False):
            return 0
        if not open_application_in_browser():
            show_error("Launcher", f"Не удалось открыть интерфейс приложения: {APP_URL}")
            return 1
        return 0

    backend_process: subprocess.Popen[bytes] | None = None
    try:
        backend_process, collector = spawn_backend_process(app_root)
        register_exit_handlers(backend_process)
        wait_for_backend_health(backend_process, collector)

        if open_application_in_webview(owns_backend=True):
            return 0

        if not open_application_in_browser():
            show_error("Launcher", f"Не удалось открыть интерфейс приложения: {APP_URL}")
            return 1
        print("\u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043e.")
        print(
            f"\u0418\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441 "
            f"\u043e\u0442\u043a\u0440\u044b\u0442 \u043f\u043e \u0430\u0434\u0440\u0435\u0441\u0443: {APP_URL}"
        )
        print(
            "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 Ctrl+C, \u0447\u0442\u043e\u0431\u044b "
            "\u043e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c backend."
        )

        return backend_process.wait()
    except KeyboardInterrupt:
        print("\n\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 launcher...")
        return 0
    finally:
        terminate_backend_process(backend_process)


def main() -> int:
    try:
        admin_result = ensure_admin_rights()
        if admin_result is not None:
            return admin_result
        if BACKEND_PROCESS_FLAG in sys.argv[1:]:
            return run_backend_mode()
        return run_launcher_mode()
    except Exception as error:
        show_error("Launcher", str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
