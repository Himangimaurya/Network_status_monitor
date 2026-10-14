"""Check internet connectivity and display useful system network information."""

from datetime import datetime
import http.client
import os
import platform
import queue
import socket
import subprocess
import threading
import time
import uuid

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk
except ImportError:
    # Cloud servers can reuse the network checker even when Tk is not installed.
    tk = None
    scrolledtext = None
    ttk = None


# Change this domain to a reserved invalid name to test DNS failure.
DNS_DOMAIN = "google.com"
WEB_HOST = "www.google.com"
WEB_PATH = "/"
TCP_TARGETS = (("8.8.8.8", 53), ("1.1.1.1", 53))
CONNECT_TIMEOUT = 3
WEB_TIMEOUT = 5
MONITOR_INTERVAL = 5


class Colors:
    """Provide ANSI colors and enable their display in supported Windows terminals."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

    @staticmethod
    def enable_windows_colors():
        """Ask Windows to support ANSI colors when running in a console."""
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            output_handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(output_handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(output_handle, mode.value | 0x0004)
        except (AttributeError, OSError):
            # The program still works if ANSI color support cannot be enabled.
            pass

    @staticmethod
    def paint(text, color):
        """Wrap text in ANSI color codes for terminal output."""
        return "{}{}{}".format(color, text, Colors.RESET)


class NetworkChecker:
    """Run local network, TCP reachability, DNS, and HTTP checks."""

    def __init__(self, dns_domain=DNS_DOMAIN, web_host=WEB_HOST):
        """Store the domain names used by the DNS and web checks."""
        self.dns_domain = dns_domain
        self.web_host = web_host

    def check_local_network(self):
        """Find an assigned IP; this demonstrates network interfaces and addressing."""
        probe = None
        try:
            # A UDP connect selects a route and local interface without sending data.
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 53))
            local_ip = probe.getsockname()[0]
            if local_ip and not local_ip.startswith("127."):
                return {"passed": True, "ip": local_ip, "detail": ""}
        except OSError:
            pass
        finally:
            if probe is not None:
                probe.close()

        try:
            addresses = socket.getaddrinfo(
                socket.gethostname(), None, family=socket.AF_INET
            )
            for address in addresses:
                local_ip = address[4][0]
                if local_ip and not local_ip.startswith("127."):
                    return {"passed": True, "ip": local_ip, "detail": ""}
        except (socket.gaierror, OSError):
            pass
        return {
            "passed": False,
            "ip": "Unavailable",
            "detail": "No non-loopback local IP address was found",
        }

    def check_internet_reachability(self):
        """Try public DNS server connections; this demonstrates TCP connectivity."""
        last_error = "Connection failed"
        for host, port in TCP_TARGETS:
            start_time = time.monotonic()
            try:
                connection = socket.create_connection(
                    (host, port), timeout=CONNECT_TIMEOUT
                )
                connection.close()
                latency_ms = (time.monotonic() - start_time) * 1000
                return {
                    "passed": True,
                    "target": "{}:{}".format(host, port),
                    "latency_ms": latency_ms,
                    "detail": "",
                }
            except (socket.timeout, OSError) as error:
                last_error = str(error)

        return {
            "passed": False,
            "target": "Both public DNS servers",
            "latency_ms": None,
            "detail": last_error,
        }

    def check_dns_resolution(self):
        """Resolve a domain name to an IP; this demonstrates DNS name resolution."""
        try:
            ip_address = socket.gethostbyname(self.dns_domain)
            return {"passed": True, "ip": ip_address, "detail": ""}
        except (socket.gaierror, OSError) as error:
            return {"passed": False, "ip": None, "detail": str(error)}

    def check_web_server(self):
        """Send an HTTPS GET request; this demonstrates client-server request/response."""
        connection = None
        start_time = time.monotonic()
        try:
            connection = http.client.HTTPSConnection(
                self.web_host, timeout=WEB_TIMEOUT
            )
            connection.request(
                "GET",
                WEB_PATH,
                headers={"User-Agent": "NetworkStatusMonitor/1.0"},
            )
            response = connection.getresponse()
            status_code = response.status
            response.read(1024)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "passed": 200 <= status_code < 400,
                "status_code": status_code,
                "latency_ms": elapsed_ms,
                "detail": "",
            }
        except (
            socket.timeout,
            socket.gaierror,
            OSError,
            http.client.HTTPException,
        ) as error:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "passed": False,
                "status_code": None,
                "latency_ms": elapsed_ms,
                "detail": str(error),
            }
        finally:
            if connection is not None:
                connection.close()

    def run_all_checks(self):
        """Run each connectivity layer and return the results and final verdict."""
        local = self.check_local_network()
        internet = self.check_internet_reachability()
        dns = self.check_dns_resolution()
        web = self.check_web_server()
        return {
            "timestamp": datetime.now(),
            "local": local,
            "internet": internet,
            "dns": dns,
            "web": web,
            "status": self.determine_status(local, internet, dns, web),
        }

    @staticmethod
    def determine_status(local, internet, dns, web):
        """Choose a readable overall status from the four check results."""
        if not local["passed"]:
            return "OFFLINE (No Network)"
        if not internet["passed"]:
            return "LOCAL NETWORK ONLY (No Internet)"
        if not dns["passed"]:
            return "CONNECTED BUT DNS PROBLEM"
        if not web["passed"]:
            return "CONNECTED, WEB SERVER UNAVAILABLE"
        return "ONLINE"


class SystemInfo:
    """Collect operating system and network identity information."""

    @staticmethod
    def get_local_ip():
        """Find the local IP address using the same route-based method as the check."""
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 53))
            address = probe.getsockname()[0]
            if not address.startswith("127."):
                return address
        except OSError:
            pass
        finally:
            if probe is not None:
                probe.close()

        try:
            for address in socket.getaddrinfo(
                socket.gethostname(), None, family=socket.AF_INET
            ):
                local_ip = address[4][0]
                if not local_ip.startswith("127."):
                    return local_ip
        except (socket.gaierror, OSError):
            pass
        return "Unavailable"

    @staticmethod
    def get_mac_address():
        """Format the hardware node identifier as six colon-separated bytes."""
        node = uuid.getnode()
        return ":".join(
            "{:02X}".format((node >> shift) & 0xFF)
            for shift in range(40, -1, -8)
        )

    @staticmethod
    def collect():
        """Return the requested host, OS, architecture, and Python details."""
        return {
            "hostname": socket.gethostname(),
            "local_ip": SystemInfo.get_local_ip(),
            "operating_system": "{} {}".format(
                platform.system(), platform.release()
            ),
            "architecture": platform.machine() or "Unavailable",
            "mac_address": SystemInfo.get_mac_address(),
            "python_version": platform.python_version(),
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


class NetworkLogger:
    """Append each connectivity check and show recent log entries."""

    def __init__(self, filename="network_log.txt"):
        """Remember the file that stores check history."""
        self.filename = filename

    def log_result(self, result):
        """Append timestamp, status, and TCP latency to the history file."""
        latency = result["internet"]["latency_ms"]
        latency_text = "{:.1f} ms".format(latency) if latency is not None else "N/A"
        line = "{} | {} | latency={}\n".format(
            result["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            result["status"],
            latency_text,
        )
        try:
            with open(self.filename, "a", encoding="utf-8") as log_file:
                log_file.write(line)
            return None
        except OSError as error:
            return "Could not write log file '{}': {}".format(self.filename, error)

    def get_last_entries(self, count=10):
        """Read and return at most the most recent requested number of log lines."""
        try:
            with open(self.filename, "r", encoding="utf-8") as log_file:
                return log_file.readlines()[-count:], None
        except FileNotFoundError:
            return [], "No log file yet. Run a connection check first."
        except OSError as error:
            return [], "Could not read log file '{}': {}".format(
                self.filename, error
            )


class Monitor:
    """Repeat connectivity checks and summarize their success and latency."""

    def __init__(self, checker, logger, interval=MONITOR_INTERVAL):
        """Keep the checker, file logger, interval, and empty statistics."""
        self.checker = checker
        self.logger = logger
        self.interval = interval
        self.total_checks = 0
        self.successful_checks = 0
        self.failed_checks = 0
        self.latencies = []
        self.last_status = None
        self.last_status_change = "No status change yet"

    def record_result(self, result):
        """Update monitoring totals and note when the overall status changes."""
        self.total_checks += 1
        if result["status"] == "ONLINE":
            self.successful_checks += 1
        else:
            self.failed_checks += 1

        latency = result["internet"]["latency_ms"]
        if latency is not None:
            self.latencies.append(latency)

        if self.last_status is not None and result["status"] != self.last_status:
            self.last_status_change = "{} at {}".format(
                "Went ONLINE" if result["status"] == "ONLINE" else "Went OFFLINE",
                result["timestamp"].strftime("%H:%M:%S"),
            )
        elif self.last_status is None:
            self.last_status_change = "Initial status: {} at {}".format(
                result["status"],
                result["timestamp"].strftime("%H:%M:%S"),
            )
        self.last_status = result["status"]

    def summary(self):
        """Calculate uptime percentage and average measured TCP latency."""
        uptime = (
            self.successful_checks / self.total_checks * 100
            if self.total_checks
            else 0.0
        )
        average_latency = (
            sum(self.latencies) / len(self.latencies) if self.latencies else None
        )
        return {
            "total": self.total_checks,
            "successful": self.successful_checks,
            "failed": self.failed_checks,
            "uptime": uptime,
            "average_latency": average_latency,
            "last_status_change": self.last_status_change,
        }

    def run(self):
        """Run checks every five seconds until Ctrl+C, then show final statistics."""
        print("Live monitoring started. Press Ctrl+C to stop.")
        try:
            while True:
                cycle_start = time.monotonic()
                result = self.checker.run_all_checks()
                self.record_result(result)
                log_error = self.logger.log_result(result)
                clear_screen()
                display_report(result)
                display_monitor_summary(self.summary())
                if log_error:
                    print(Colors.paint(log_error, Colors.YELLOW))

                remaining = self.interval - (time.monotonic() - cycle_start)
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("\nMonitoring stopped by the user.")
            display_monitor_summary(self.summary(), final=True)


class NetworkMonitorWindow:
    """Show the network checker in a graphical Tkinter dashboard."""

    BACKGROUND = "#101827"
    PANEL = "#1b2738"
    TEXT = "#edf2f7"
    MUTED = "#9aaabd"
    GREEN = "#4ade80"
    RED = "#f87171"
    YELLOW = "#facc15"
    BLUE = "#60a5fa"

    def __init__(self, root):
        """Build the application window and initialize monitoring state."""
        self.root = root
        self.root.title("Internet Connection & Network Status Monitor")
        self.root.geometry("1050x760")
        self.root.minsize(820, 620)
        self.root.configure(bg=self.BACKGROUND)

        self.checker = NetworkChecker()
        self.logger = NetworkLogger()
        self.monitor = Monitor(self.checker, self.logger)
        self.messages = queue.Queue()
        self.check_in_progress = False
        self.monitoring = False
        self.closed = False
        self.monitor_after_id = None

        self._configure_styles()
        self._build_window()
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self.root.after(100, self._process_messages)
        self.root.after(250, self.start_quick_check)

    def _configure_styles(self):
        """Set readable colors and spacing for the table and notebook tabs."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=self.PANEL,
            fieldbackground=self.PANEL,
            foreground=self.TEXT,
            rowheight=32,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#26364b",
            foreground=self.TEXT,
            font=("Segoe UI", 10, "bold"),
            padding=8,
        )
        style.map("Treeview", background=[("selected", "#334b68")])
        style.configure(
            "TNotebook",
            background=self.BACKGROUND,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background="#26364b",
            foreground=self.TEXT,
            padding=(14, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.PANEL)],
            foreground=[("selected", self.TEXT)],
        )

    def _build_window(self):
        """Create the header, action buttons, dashboard, and information tabs."""
        outer = tk.Frame(self.root, bg=self.BACKGROUND, padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=self.BACKGROUND)
        header.pack(fill="x", pady=(0, 16))
        tk.Label(
            header,
            text="NETWORK STATUS MONITOR",
            bg=self.BACKGROUND,
            fg=self.TEXT,
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Connectivity checks, system information, and live monitoring",
            bg=self.BACKGROUND,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        controls = tk.Frame(outer, bg=self.BACKGROUND)
        controls.pack(fill="x", pady=(0, 14))
        self.check_button = self._make_button(
            controls, "Check Connection", self.start_quick_check, "#2563eb"
        )
        self.check_button.pack(side="left")
        self.monitor_button = self._make_button(
            controls, "Start Live Monitoring", self.toggle_monitoring, "#15803d"
        )
        self.monitor_button.pack(side="left", padx=(8, 0))
        self.info_button = self._make_button(
            controls, "Refresh System Info", self.load_system_information, "#374151"
        )
        self.info_button.pack(side="left", padx=(8, 0))
        self.status_text = tk.StringVar(value="Ready — run a connection check")
        tk.Label(
            controls,
            textvariable=self.status_text,
            bg=self.BACKGROUND,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        ).pack(side="right")

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.dashboard_tab = tk.Frame(self.notebook, bg=self.BACKGROUND, padx=14, pady=14)
        self.system_tab = tk.Frame(self.notebook, bg=self.BACKGROUND, padx=18, pady=18)
        self.logs_tab = tk.Frame(self.notebook, bg=self.BACKGROUND, padx=18, pady=18)
        self.concepts_tab = tk.Frame(self.notebook, bg=self.BACKGROUND, padx=18, pady=18)
        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.system_tab, text="System Information")
        self.notebook.add(self.logs_tab, text="Recent Logs")
        self.notebook.add(self.concepts_tab, text="Concepts Guide")
        self._build_dashboard()
        self._build_system_tab()
        self._build_logs_tab()
        self._build_concepts_tab()

    def _make_button(self, parent, text, command, background):
        """Create a consistently styled button for the top action bar."""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg="white",
            activebackground=background,
            activeforeground="white",
            disabledforeground="#aab4c0",
            relief="flat",
            padx=13,
            pady=9,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )

    def _build_dashboard(self):
        """Create the overall result, layer-by-layer checks, and live statistics."""
        self.verdict_label = tk.Label(
            self.dashboard_tab,
            text="Waiting for first check",
            bg=self.PANEL,
            fg=self.MUTED,
            anchor="w",
            padx=16,
            pady=13,
            font=("Segoe UI", 16, "bold"),
        )
        self.verdict_label.pack(fill="x", pady=(0, 14))

        summary = tk.Frame(self.dashboard_tab, bg=self.BACKGROUND)
        summary.pack(fill="x", pady=(0, 14))
        self.stat_labels = {}
        for index, (title, key) in enumerate((
            ("TOTAL CHECKS", "total"),
            ("SUCCESSFUL", "successful"),
            ("FAILED", "failed"),
            ("UPTIME", "uptime"),
            ("AVG LATENCY", "average_latency"),
        )):
            card = tk.Frame(summary, bg=self.PANEL, padx=12, pady=10)
            card.grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=(0, 8),
                pady=(0, 8),
            )
            tk.Label(
                card,
                text=title,
                bg=self.PANEL,
                fg=self.MUTED,
                font=("Segoe UI", 8, "bold"),
            ).pack(anchor="w")
            value = tk.Label(
                card,
                text="—",
                bg=self.PANEL,
                fg=self.TEXT,
                font=("Segoe UI", 15, "bold"),
            )
            value.pack(anchor="w", pady=(4, 0))
            self.stat_labels[key] = value
        for column in range(3):
            summary.grid_columnconfigure(column, weight=1, uniform="stat-card")

        tk.Label(
            self.dashboard_tab,
            text="CONNECTIVITY CHECKS",
            bg=self.BACKGROUND,
            fg=self.TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 7))
        self.check_table = ttk.Treeview(
            self.dashboard_tab,
            columns=("step", "result"),
            show="headings",
            height=4,
        )
        self.check_table.heading("step", text="Check")
        self.check_table.heading("result", text="Result")
        self.check_table.column("step", width=210, anchor="w")
        self.check_table.column("result", width=600, anchor="w")
        self.check_table.tag_configure("PASS", foreground=self.GREEN)
        self.check_table.tag_configure("FAIL", foreground=self.RED)
        self.check_table.tag_configure("WAIT", foreground=self.MUTED)
        for identifier, label in (
            ("local", "Local Network"),
            ("internet", "Internet Reachability"),
            ("dns", "DNS Resolution"),
            ("web", "Web Server Response"),
        ):
            self.check_table.insert(
                "", "end", iid=identifier, values=(label, "Not checked"), tags=("WAIT",)
            )
        self.check_table.pack(fill="x", pady=(0, 14))

        self.last_change_label = tk.Label(
            self.dashboard_tab,
            text="Last status change: No status change yet",
            bg=self.BACKGROUND,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        )
        self.last_change_label.pack(anchor="w")
        tk.Label(
            self.dashboard_tab,
            text="Checks use bounded TCP and HTTPS timeouts; live updates continue every 5 seconds.",
            bg=self.BACKGROUND,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(7, 0))

    def _build_system_tab(self):
        """Create labeled fields for the operating system and network details."""
        self.system_values = {}
        for row_number, (key, label) in enumerate(
            (
                ("hostname", "Hostname"),
                ("local_ip", "Local IP address"),
                ("operating_system", "Operating system"),
                ("architecture", "Architecture"),
                ("mac_address", "MAC address"),
                ("python_version", "Python version"),
                ("current_time", "Current date/time"),
            )
        ):
            tk.Label(
                self.system_tab,
                text=label,
                bg=self.BACKGROUND,
                fg=self.MUTED,
                font=("Segoe UI", 10, "bold"),
            ).grid(row=row_number, column=0, sticky="w", padx=(0, 24), pady=9)
            value = tk.Label(
                self.system_tab,
                text="Click Refresh System Info to load",
                bg=self.BACKGROUND,
                fg=self.TEXT,
                font=("Segoe UI", 10),
                anchor="w",
            )
            value.grid(row=row_number, column=1, sticky="w", pady=9)
            self.system_values[key] = value
        self.system_tab.grid_columnconfigure(1, weight=1)

    def _build_logs_tab(self):
        """Create a text area and button for the latest ten saved checks."""
        self.log_text = scrolledtext.ScrolledText(
            self.logs_tab,
            bg=self.PANEL,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 10),
            height=18,
        )
        self.log_text.pack(fill="both", expand=True, pady=(0, 10))
        self.log_text.configure(state="disabled")
        self._make_button(
            self.logs_tab, "Refresh Last 10 Logs", self.refresh_logs, "#374151"
        ).pack(anchor="w")

    def _build_concepts_tab(self):
        """Show short CN and OS explanations inside the graphical application."""
        explanation = (
            "IP address\n"
            "A number used to identify a device on a network.\n\n"
            "DNS\n"
            "The Domain Name System finds an IP address for a website name.\n\n"
            "TCP\n"
            "Transmission Control Protocol provides a reliable connection between "
            "a client and a server.\n\n"
            "Client-server and request/response\n"
            "A client sends a request to a server; the server processes it and "
            "returns a response. This app sends an HTTPS request to a web server.\n\n"
            "Latency\n"
            "The time taken for a network operation, measured in milliseconds.\n\n"
            "Operating system\n"
            "The OS gives applications access to information such as the computer's "
            "hostname, local network route, and platform details."
        )
        tk.Label(
            self.concepts_tab,
            text=explanation,
            justify="left",
            anchor="nw",
            bg=self.BACKGROUND,
            fg=self.TEXT,
            font=("Segoe UI", 11),
            wraplength=850,
        ).pack(fill="both", expand=True)

    def _start_worker(self, job_name, function):
        """Run a potentially slow operation away from Tk's user-interface thread."""
        if self.check_in_progress:
            return
        self.check_in_progress = True
        self.status_text.set("Checking network — please wait...")
        self.check_button.configure(state="disabled")
        self.info_button.configure(state="disabled")

        def worker():
            try:
                self.messages.put((job_name, function(), None))
            except Exception as error:
                self.messages.put((job_name, None, str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def start_quick_check(self):
        """Start one connection check and save its result to the log."""
        self._start_worker("check", self._check_and_log)

    def _check_and_log(self):
        """Run all network checks and append their result to the history file."""
        result = self.checker.run_all_checks()
        log_error = self.logger.log_result(result)
        return result, log_error

    def load_system_information(self):
        """Load the host and network details without freezing the window."""
        self._start_worker("system", SystemInfo.collect)

    def toggle_monitoring(self):
        """Start live checks or stop scheduling any future monitoring checks."""
        if self.monitoring:
            self.monitoring = False
            if self.monitor_after_id is not None:
                self.root.after_cancel(self.monitor_after_id)
                self.monitor_after_id = None
            self.monitor_button.configure(text="Start Live Monitoring")
            self.status_text.set("Live monitoring stopped")
            return

        self.monitoring = True
        self.monitor = Monitor(self.checker, self.logger)
        self.monitor_button.configure(text="Stop Live Monitoring")
        self.status_text.set("Live monitoring started")
        self._begin_monitor_check()

    def _begin_monitor_check(self):
        """Run a monitoring check unless stopped or another check is in progress."""
        self.monitor_after_id = None
        if self.monitoring and not self.check_in_progress:
            self._start_worker("monitor", self._check_and_log)

    def _process_messages(self):
        """Handle finished background tasks safely on Tk's main thread."""
        if self.closed:
            return
        try:
            while True:
                job_name, payload, error = self.messages.get_nowait()
                self.check_in_progress = False
                self.check_button.configure(state="normal")
                self.info_button.configure(state="normal")

                if error:
                    self.status_text.set("Operation failed: {}".format(error))
                elif job_name == "system":
                    for key, value in payload.items():
                        self.system_values[key].configure(text=value)
                    self.status_text.set("System information updated")
                elif job_name in ("check", "monitor"):
                    result, log_error = payload
                    self._show_result(result)
                    self.monitor.record_result(result)
                    self._show_monitor_summary()
                    self.status_text.set(
                        "Last checked at {}".format(
                            result["timestamp"].strftime("%H:%M:%S")
                        )
                    )
                    if log_error:
                        self.status_text.set(log_error)

                if self.monitoring:
                    self.monitor_after_id = self.root.after(
                        MONITOR_INTERVAL * 1000, self._begin_monitor_check
                    )
        except queue.Empty:
            pass
        self.root.after(100, self._process_messages)

    def _show_result(self, result):
        """Render the four check outcomes and color the overall connection status."""
        local = result["local"]
        internet = result["internet"]
        dns = result["dns"]
        web = result["web"]
        rows = (
            (
                "local",
                local["passed"],
                "IP: {}".format(local["ip"]) if local["passed"] else local["detail"],
            ),
            (
                "internet",
                internet["passed"],
                "{}; {:.1f} ms".format(
                    internet["target"], internet["latency_ms"]
                )
                if internet["passed"]
                else "{} ({})".format(internet["target"], internet["detail"]),
            ),
            (
                "dns",
                dns["passed"],
                "{} -> {}".format(DNS_DOMAIN, dns["ip"])
                if dns["passed"]
                else "{} ({})".format(DNS_DOMAIN, dns["detail"]),
            ),
            (
                "web",
                web["passed"],
                "HTTP {} {}; {:.1f} ms".format(
                    web["status_code"],
                    http.client.responses.get(web["status_code"], "Response"),
                    web["latency_ms"],
                )
                if web["passed"]
                else "No response ({})".format(web["detail"]),
            ),
        )
        for identifier, passed, detail in rows:
            self.check_table.item(
                identifier,
                values=(
                    self.check_table.item(identifier, "values")[0],
                    "{} — {}".format("PASS" if passed else "FAIL", detail),
                ),
                tags=("PASS" if passed else "FAIL",),
            )

        status = result["status"]
        if status == "ONLINE":
            color = self.GREEN
        elif status in (
            "LOCAL NETWORK ONLY (No Internet)",
            "CONNECTED BUT DNS PROBLEM",
        ):
            color = self.YELLOW
        else:
            color = self.RED
        self.verdict_label.configure(text=status, fg=color)
        self.stat_labels["average_latency"].configure(
            text=(
                "{:.1f} ms ({})".format(
                    internet["latency_ms"],
                    latency_quality(internet["latency_ms"]),
                )
                if internet["latency_ms"] is not None
                else "N/A"
            )
        )
        self.refresh_logs()

    def _show_monitor_summary(self):
        """Update dashboard statistics from the live monitor's collected checks."""
        summary = self.monitor.summary()
        self.stat_labels["total"].configure(text=str(summary["total"]))
        self.stat_labels["successful"].configure(text=str(summary["successful"]))
        self.stat_labels["failed"].configure(text=str(summary["failed"]))
        self.stat_labels["uptime"].configure(text="{:.1f}%".format(summary["uptime"]))
        average = summary["average_latency"]
        average_text = "{:.1f} ms".format(average) if average is not None else "N/A"
        self.stat_labels["average_latency"].configure(text=average_text)
        self.last_change_label.configure(
            text="Last status change: {}".format(summary["last_status_change"])
        )

    def refresh_logs(self):
        """Load the ten newest log entries into the Recent Logs tab."""
        entries, error = self.logger.get_last_entries()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        if error:
            self.log_text.insert(tk.END, error)
        else:
            self.log_text.insert(tk.END, "".join(entries))
        self.log_text.configure(state="disabled")

    def _close_window(self):
        """Stop scheduling checks and close the graphical application."""
        self.closed = True
        self.monitoring = False
        if self.monitor_after_id is not None:
            self.root.after_cancel(self.monitor_after_id)
        self.root.destroy()


def clear_screen():
    """Clear the terminal using its platform-specific clear command."""
    command = ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
    try:
        subprocess.run(command, check=False)
    except OSError:
        # Keep the monitor usable if the terminal's clear command is unavailable.
        pass


def latency_quality(latency_ms):
    """Convert a measured latency into the requested quality label."""
    if latency_ms is None:
        return "Unavailable"
    if latency_ms < 50:
        return "Excellent"
    if latency_ms < 150:
        return "Good"
    if latency_ms < 300:
        return "Average"
    return "Poor"


def display_check(step, label, result, success_detail, failure_detail):
    """Print one connectivity step with a colored PASS or FAIL label."""
    if result["passed"]:
        mark = Colors.paint("PASS", Colors.GREEN)
        detail = success_detail
    else:
        mark = Colors.paint("FAIL", Colors.RED)
        detail = failure_detail
    print("[{}] {:<22}: {}  ({})".format(step, label, mark, detail))


def display_report(result):
    """Draw a complete connectivity report with colored results."""
    print("==============================================")
    print("        NETWORK STATUS REPORT")
    print("==============================================")

    local = result["local"]
    display_check(
        "1",
        "Local Network",
        local,
        "IP: {}".format(local["ip"]),
        local["detail"],
    )

    internet = result["internet"]
    if internet["passed"]:
        internet_detail = "{}; {:.1f} ms".format(
            internet["target"], internet["latency_ms"]
        )
    else:
        internet_detail = "{} ({})".format(
            internet["target"], internet["detail"]
        )
    display_check(
        "2", "Internet Reachable", internet, internet_detail, internet_detail
    )

    dns = result["dns"]
    dns_detail = (
        "{} -> {}".format(DNS_DOMAIN, dns["ip"])
        if dns["passed"]
        else "{} ({})".format(DNS_DOMAIN, dns["detail"])
    )
    display_check("3", "DNS Resolution", dns, dns_detail, dns_detail)

    web = result["web"]
    web_detail = (
        "HTTP {} {}; {:.1f} ms".format(
            web["status_code"],
            http.client.responses.get(web["status_code"], "Response"),
            web["latency_ms"],
        )
        if web["passed"]
        else "{} ({})".format(
            "HTTP {}".format(web["status_code"])
            if web["status_code"] is not None
            else "No response",
            web["detail"],
        )
    )
    display_check("4", "Web Server Response", web, web_detail, web_detail)

    latency = internet["latency_ms"]
    quality = latency_quality(latency)
    status = result["status"]
    if status == "ONLINE":
        status_color = Colors.GREEN
    elif status in (
        "LOCAL NETWORK ONLY (No Internet)",
        "CONNECTED BUT DNS PROBLEM",
    ):
        status_color = Colors.YELLOW
    else:
        status_color = Colors.RED
    print("----------------------------------------------")
    print("Latency Quality : {}".format(quality))
    print("Overall Status  : {}".format(Colors.paint(status, status_color)))
    print("==============================================")


def display_monitor_summary(summary, final=False):
    """Print monitoring totals, uptime, average latency, and status-change time."""
    heading = "FINAL MONITORING SUMMARY" if final else "LIVE MONITORING SUMMARY"
    print("\n{}".format(heading))
    print("----------------------------------------------")
    print("Total checks       : {}".format(summary["total"]))
    print("Successful checks  : {}".format(summary["successful"]))
    print("Failed checks      : {}".format(summary["failed"]))
    print("Uptime             : {:.1f}%".format(summary["uptime"]))
    average = summary["average_latency"]
    average_text = "{:.1f} ms".format(average) if average is not None else "N/A"
    print("Average latency    : {}".format(average_text))
    print("Last status change : {}".format(summary["last_status_change"]))
    print("----------------------------------------------")


def show_system_information():
    """Display network identity and operating system details."""
    information = SystemInfo.collect()
    print("\nSYSTEM NETWORK INFORMATION")
    print("----------------------------------------------")
    print("Hostname          : {}".format(information["hostname"]))
    print("Local IP address  : {}".format(information["local_ip"]))
    print("Operating system  : {}".format(information["operating_system"]))
    print("Architecture       : {}".format(information["architecture"]))
    print("MAC address       : {}".format(information["mac_address"]))
    print("Python version    : {}".format(information["python_version"]))
    print("Current date/time : {}".format(information["current_time"]))


def view_recent_logs(logger):
    """Show the last ten saved checks or an understandable file error."""
    entries, error = logger.get_last_entries()
    print("\nLAST 10 CONNECTION CHECKS")
    print("----------------------------------------------")
    if error:
        print(error)
        return
    for entry in entries:
        print(entry.rstrip())


def explain_concepts():
    """Explain the networking and operating system ideas used by the program."""
    print(
        "\nNETWORKING AND OPERATING SYSTEM CONCEPTS\n"
        "----------------------------------------------\n"
        "IP address: A number that identifies a device on a network.\n"
        "DNS: The service that finds an IP address for a domain name.\n"
        "TCP: A reliable connection protocol used to communicate with a server.\n"
        "Client-server: A client asks a server for a service or information.\n"
        "Request/response: The client sends a request and the server replies.\n"
        "Latency: The time taken for a network operation, measured here in ms.\n"
        "Operating system: It provides hostname, network routes, and system details.\n"
    )


def get_menu_choice():
    """Read a menu choice and return it, handling end-of-input safely."""
    try:
        return input("Enter your choice: ").strip()
    except EOFError:
        return "6"


def main():
    """Start the graphical network monitoring application."""
    if tk is None:
        raise RuntimeError("Tkinter is unavailable; run the web app with web_app.py.")
    root = tk.Tk()
    NetworkMonitorWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
