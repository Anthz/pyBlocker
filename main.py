import sys
import os
import psutil
import time
import logging
from datetime import datetime, timedelta
import threading

from PyQt5 import QtWidgets, QtGui, QtCore
from plyer import notification

# Setup Logging
logging.basicConfig(
    filename='app_blocker.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Check for Administrative Privileges
def is_admin():
    if os.name == 'nt':
        import ctypes
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    else:
        return os.geteuid() == 0

def request_admin():
    if os.name == 'nt':
        import ctypes
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, ' '.join(sys.argv), None, 1
            )
            sys.exit(0)
        except Exception as e:
            logging.error(f"Failed to elevate privileges: {e}")
            QtWidgets.QMessageBox.critical(None, "Admin Privileges Required",
                                           "Failed to obtain administrative privileges.")
            sys.exit(1)
    else:
        QtWidgets.QMessageBox.critical(None, "Admin Privileges Required",
                                       "This application requires administrative privileges. Please run it as root.")
        sys.exit(1)

# Notification Function
def send_notification(title, message):
    try:
        notification.notify(
            title=title,
            message=message,
            app_name="App Blocker",
            timeout=5
        )
    except Exception as e:
        logging.error(f"Failed to send notification: {e}")

# Worker Thread for Blocking Applications
class BlockerThread(QtCore.QThread):
    update_stats = QtCore.pyqtSignal(int, int, int)  # time_remaining, blocked_apps, attempts

    def __init__(self, app_paths=None, process_names=None, duration_minutes=30, start_time=None, notify=False, check_frequency=1):
        super().__init__()
        self.app_paths = [os.path.abspath(path) for path in app_paths] if app_paths else []
        self.process_names = [pn.lower() for pn in process_names] if process_names else []
        self.duration_minutes = duration_minutes
        self.start_time = start_time
        self.notify = notify
        self.check_frequency = check_frequency
        self.running = True
        self.attempts = 0

    def run(self):
        # Schedule Start Time if Provided
        if self.start_time:
            try:
                start_datetime = datetime.strptime(self.start_time, "%H:%M").replace(
                    year=datetime.now().year,
                    month=datetime.now().month,
                    day=datetime.now().day
                )
                now = datetime.now()
                if start_datetime < now:
                    # If the start time has already passed today, schedule for tomorrow
                    start_datetime += timedelta(days=1)
                wait_seconds = (start_datetime - now).total_seconds()
                logging.info(f"Scheduled to start blocking at {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
                if self.notify:
                    send_notification("App Blocker", f"Blocking scheduled at {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
                # Countdown Timer
                while wait_seconds > 0 and self.running:
                    mins, secs = divmod(int(wait_seconds), 60)
                    self.update_stats.emit(wait_seconds, 0, self.attempts)
                    time.sleep(1)
                    wait_seconds -= 1
            except ValueError:
                logging.error("Incorrect time format. Please use HH:MM (24-hour format).")
                if self.notify:
                    send_notification("App Blocker", "Incorrect time format. Use HH:MM (24-hour format).")
                return

        end_time = datetime.now() + timedelta(minutes=self.duration_minutes)
        logging.info(f"Started blocking applications for {self.duration_minutes} minutes.")
        if self.notify:
            send_notification("App Blocker", f"Started blocking applications for {self.duration_minutes} minutes.")

        # Blocking Loop
        while datetime.now() < end_time and self.running:
            blocked_apps = 0
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    # Check by Path
                    if self.app_paths and proc.exe():
                        proc_path = os.path.abspath(proc.exe())
                        if proc_path in self.app_paths:
                            proc_name = proc.name()
                            proc.terminate()
                            proc.wait(timeout=3)
                            logging.info(f"Terminated process {proc.pid} ({proc_name}).")
                            blocked_apps += 1
                            self.attempts += 1
                            if self.notify:
                                send_notification("App Blocker", f"Terminated {proc_name} (PID: {proc.pid}).")

                    # Check by Process Name
                    if self.process_names:
                        proc_name_lower = proc.name().lower()
                        if proc_name_lower in self.process_names:
                            proc.terminate()
                            proc.wait(timeout=3)
                            logging.info(f"Terminated process {proc.pid} ({proc.name()}).")
                            blocked_apps += 1
                            self.attempts += 1
                            if self.notify:
                                send_notification("App Blocker", f"Terminated {proc.name()} (PID: {proc.pid}).")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as e:
                    logging.warning(f"Failed to terminate process {proc.pid}: {e}")
            # Calculate Time Remaining
            time_remaining = int((end_time - datetime.now()).total_seconds())
            self.update_stats.emit(time_remaining, blocked_apps, self.attempts)
            time.sleep(self.check_frequency)  # Adjustable Check Frequency

        if self.running:
            logging.info("Finished blocking applications.")
            if self.notify:
                send_notification("App Blocker", "Finished blocking applications.")

    def stop(self):
        self.running = False
        self.wait()

# Main Application Window
class AppBlockerGUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("App Blocker")
        self.setWindowIcon(QtGui.QIcon("app_icon.png"))  # Optional: Add an icon file
        self.setMinimumSize(500, 400)

        # Initialize Variables
        self.blocker_thread = None
        self.time_remaining = 0
        self.blocked_apps = 0
        self.attempts = 0

        # Layouts
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # Application Paths Section
        app_paths_layout = QtWidgets.QVBoxLayout()
        app_paths_label = QtWidgets.QLabel("<b>Applications to Block:</b>")
        app_paths_layout.addWidget(app_paths_label)

        self.app_paths_list = QtWidgets.QListWidget()
        self.app_paths_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        app_paths_layout.addWidget(self.app_paths_list)

        app_paths_buttons_layout = QtWidgets.QHBoxLayout()
        self.add_app_button = QtWidgets.QPushButton("Add")
        self.add_app_button.clicked.connect(self.add_application)
        self.remove_app_button = QtWidgets.QPushButton("Remove")
        self.remove_app_button.clicked.connect(self.remove_application)
        app_paths_buttons_layout.addWidget(self.add_app_button)
        app_paths_buttons_layout.addWidget(self.remove_app_button)
        app_paths_layout.addLayout(app_paths_buttons_layout)

        main_layout.addLayout(app_paths_layout)

        # Process Names Section
        process_names_layout = QtWidgets.QVBoxLayout()
        process_names_label = QtWidgets.QLabel("<b>Process Names to Block:</b>")
        process_names_layout.addWidget(process_names_label)

        self.names_input = QtWidgets.QLineEdit()
        self.names_input.setPlaceholderText("Enter process names separated by semicolons (;), e.g., notepad.exe;calculator.exe")
        process_names_layout.addWidget(self.names_input)

        main_layout.addLayout(process_names_layout)

        # Duration and Start Time
        timing_layout = QtWidgets.QHBoxLayout()

        # Duration
        duration_layout = QtWidgets.QHBoxLayout()
        duration_label = QtWidgets.QLabel("Duration (minutes):")
        self.duration_input = QtWidgets.QSpinBox()
        self.duration_input.setRange(1, 1440)  # 1 minute to 24 hours
        self.duration_input.setValue(30)
        duration_layout.addWidget(duration_label)
        duration_layout.addWidget(self.duration_input)
        timing_layout.addLayout(duration_layout)

        # Start Time
        self.start_time_checkbox = QtWidgets.QCheckBox("Schedule Start")
        self.start_time_input = QtWidgets.QTimeEdit()
        self.start_time_input.setDisplayFormat("HH:mm")
        self.start_time_input.setTime(QtCore.QTime.currentTime())
        self.start_time_input.setEnabled(False)
        self.start_time_checkbox.stateChanged.connect(self.toggle_start_time)
        timing_layout.addWidget(self.start_time_checkbox)
        timing_layout.addWidget(self.start_time_input)

        main_layout.addLayout(timing_layout)

        # Check Frequency
        frequency_layout = QtWidgets.QHBoxLayout()
        frequency_label = QtWidgets.QLabel("Check Frequency (seconds):")
        self.frequency_input = QtWidgets.QSpinBox()
        self.frequency_input.setRange(1, 60)
        self.frequency_input.setValue(1)
        frequency_layout.addWidget(frequency_label)
        frequency_layout.addWidget(self.frequency_input)
        main_layout.addLayout(frequency_layout)

        # Notifications and Admin Privileges
        options_layout = QtWidgets.QHBoxLayout()
        self.notify_checkbox = QtWidgets.QCheckBox("Enable Notifications")
        self.notify_checkbox.setChecked(True)
        self.admin_checkbox = QtWidgets.QCheckBox("Run as Administrator")
        self.admin_checkbox.setChecked(False)
        options_layout.addWidget(self.notify_checkbox)
        options_layout.addWidget(self.admin_checkbox)
        main_layout.addLayout(options_layout)

        # Buttons
        buttons_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start Blocking")
        self.start_button.clicked.connect(self.start_blocking)
        self.stop_button = QtWidgets.QPushButton("Stop Blocking")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_blocking)
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)
        main_layout.addLayout(buttons_layout)

        # Status Labels
        status_layout = QtWidgets.QVBoxLayout()
        self.time_label = QtWidgets.QLabel("Time Remaining: N/A")
        self.apps_label = QtWidgets.QLabel("Blocked Applications: 0")
        self.attempts_label = QtWidgets.QLabel("Termination Attempts: 0")
        status_layout.addWidget(self.time_label)
        status_layout.addWidget(self.apps_label)
        status_layout.addWidget(self.attempts_label)
        main_layout.addLayout(status_layout)

        # Set Layout
        self.setLayout(main_layout)

        # System Tray
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        tray_icon_path = "app_icon.png"  # Optional: Add an icon file
        if os.path.exists(tray_icon_path):
            self.tray_icon.setIcon(QtGui.QIcon(tray_icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        tray_menu = QtWidgets.QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.qApp.quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def toggle_start_time(self, state):
        if state == QtCore.Qt.Checked:
            self.start_time_input.setEnabled(True)
        else:
            self.start_time_input.setEnabled(False)

    def add_application(self):
        options = QtWidgets.QFileDialog.Options()
        options |= QtWidgets.QFileDialog.ReadOnly
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Select Application Executable",
            "",
            "Executable Files (*.exe);;All Files (*)",
            options=options
        )
        if file_paths:
            for path in file_paths:
                if not self.app_paths_list.findItems(path, QtCore.Qt.MatchExactly):
                    self.app_paths_list.addItem(path)

    def remove_application(self):
        selected_items = self.app_paths_list.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.app_paths_list.takeItem(self.app_paths_list.row(item))

    def start_blocking(self):
        # Gather Inputs
        app_paths = [self.app_paths_list.item(i).text() for i in range(self.app_paths_list.count())]
        process_names = [name.strip() for name in self.names_input.text().split(';') if name.strip()]
        duration = self.duration_input.value()
        notify = self.notify_checkbox.isChecked()
        admin = self.admin_checkbox.isChecked()
        check_frequency = self.frequency_input.value()

        if not app_paths and not process_names:
            QtWidgets.QMessageBox.warning(self, "Input Required", "Please specify application paths or process names to block.")
            return

        start_time = None
        if self.start_time_checkbox.isChecked():
            start_time = self.start_time_input.time().toString("HH:mm")

        # Handle Administrative Privileges
        if admin and not is_admin():
            request_admin()

        # Disable Inputs
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.add_app_button.setEnabled(False)
        self.remove_app_button.setEnabled(False)
        self.names_input.setEnabled(False)
        self.duration_input.setEnabled(False)
        self.start_time_checkbox.setEnabled(False)
        self.start_time_input.setEnabled(False)
        self.frequency_input.setEnabled(False)
        self.notify_checkbox.setEnabled(False)
        self.admin_checkbox.setEnabled(False)

        # Initialize Blocking Thread
        self.blocker_thread = BlockerThread(
            app_paths=app_paths,
            process_names=process_names,
            duration_minutes=duration,
            start_time=start_time,
            notify=notify,
            check_frequency=check_frequency
        )
        self.blocker_thread.update_stats.connect(self.update_stats)
        self.blocker_thread.finished.connect(self.blocking_finished)
        self.blocker_thread.start()

    def stop_blocking(self):
        if self.blocker_thread and self.blocker_thread.isRunning():
            self.blocker_thread.stop()
            self.blocker_thread = None
            logging.info("Blocking stopped by user.")
            if self.notify_checkbox.isChecked():
                send_notification("App Blocker", "Blocking session stopped by user.")
            QtWidgets.QMessageBox.information(self, "Blocked Stopped", "Blocking session has been stopped.")

        # Reset Labels
        self.time_label.setText("Time Remaining: N/A")
        self.apps_label.setText("Blocked Applications: 0")
        self.attempts_label.setText("Termination Attempts: 0")

        # Enable Inputs
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.add_app_button.setEnabled(True)
        self.remove_app_button.setEnabled(True)
        self.names_input.setEnabled(True)
        self.duration_input.setEnabled(True)
        self.start_time_checkbox.setEnabled(True)
        self.frequency_input.setEnabled(True)
        self.notify_checkbox.setEnabled(True)
        self.admin_checkbox.setEnabled(True)

    def update_stats(self, time_remaining, blocked_apps, attempts):
        # Update Labels
        if time_remaining > 0:
            mins, secs = divmod(time_remaining, 60)
            self.time_label.setText(f"Time Remaining: {mins}m {secs}s")
        else:
            self.time_label.setText("Time Remaining: 0m 0s")

        self.apps_label.setText(f"Blocked Applications: {blocked_apps}")
        self.attempts_label.setText(f"Termination Attempts: {attempts}")

        # Update Tray Icon Tooltip
        mins, secs = divmod(time_remaining, 60) if time_remaining > 0 else (0, 0)
        self.tray_icon.setToolTip(
            f"App Blocker\nTime Remaining: {mins}m {secs}s\nBlocked Apps: {blocked_apps}\nAttempts: {attempts}"
        )

    def blocking_finished(self):
        logging.info("Blocking session completed.")
        if self.blocker_thread and self.blocker_thread.notify:
            send_notification("App Blocker", "Finished blocking applications.")

        # Reset Labels
        self.time_label.setText("Time Remaining: N/A")
        self.apps_label.setText("Blocked Applications: 0")
        self.attempts_label.setText("Termination Attempts: 0")

        # Enable Inputs
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.add_app_button.setEnabled(True)
        self.remove_app_button.setEnabled(True)
        self.names_input.setEnabled(True)
        self.duration_input.setEnabled(True)
        self.start_time_checkbox.setEnabled(True)
        self.frequency_input.setEnabled(True)
        self.notify_checkbox.setEnabled(True)
        self.admin_checkbox.setEnabled(True)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "App Blocker",
            "Application minimized to tray.",
            QtWidgets.QSystemTrayIcon.Information,
            2000
        )

    def on_tray_icon_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show()

# Entry Point
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = AppBlockerGUI()
    window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()