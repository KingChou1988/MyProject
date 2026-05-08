"""Serial file download tool - main GUI."""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from serial_handler import SerialHandler
from download_manager import DownloadManager, DownloadState


BAUD_RATES = [4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200, 128000, 230400, 256000, 460800, 921600]


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Serial File Download")
        self.root.geometry("600x380")
        self.root.resizable(False, False)

        self.serial = SerialHandler()
        self.download = DownloadManager()

        self._connected = False
        self._downloading = False
        self._filepath = ""

        self._setup_serial()
        self._setup_wiring()

        self._build_ui()
        self._update_state()
        self._refresh_ports()

    # ── Wiring ───────────────────────────────────────────────────────────

    def _setup_serial(self):
        self.serial.set_packet_callback(self._on_packet)
        self.serial.set_error_callback(self._on_serial_error)

    def _setup_wiring(self):
        dm = self.download
        dm.set_send_callback(self.serial.send)
        dm.on_progress = lambda seq, total, _size: self.root.after(0, self._on_progress, seq, total)
        dm.on_state_change = lambda s: self.root.after(0, self._on_download_state, s)
        dm.on_error = lambda msg: self.root.after(0, self._on_download_error, msg)

    # ── Packet handler (called from serial read thread) ──────────────────

    def _on_packet(self, packet: bytes):
        self.download.handle_packet(packet)

    def _on_serial_error(self, msg: str):
        self.root.after(0, self._show_error, msg)

    # ── Callbacks (main thread) ──────────────────────────────────────────

    def _on_progress(self, seq: int, total: int):
        self._progress_bar.configure(mode='determinate', maximum=total, value=seq)

    def _on_download_state(self, state: DownloadState):
        if state == DownloadState.REQUESTING:
            self._status_label.config(text="Requesting download...")
            self._download_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)

        elif state == DownloadState.TRANSFERRING:
            self._status_label.config(text="Transferring...")
            self._progress_bar.configure(mode='determinate', maximum=1, value=0)

        elif state == DownloadState.WAITING_RESULT:
            self._status_label.config(text="Waiting for device result...")

        elif state == DownloadState.DONE:
            self._status_label.config(text="Download completed successfully.")
            self._finish_download()
            messagebox.showinfo("Done", "File download completed successfully.")

        elif state == DownloadState.ERROR:
            self._status_label.config(text="Download failed.")
            self._finish_download()

        elif state == DownloadState.STOPPED:
            self._status_label.config(text="Download stopped.")
            self._finish_download()

        self._update_state()

    def _on_download_error(self, msg: str):
        self._show_error(msg)

    def _finish_download(self):
        self._downloading = False
        self._download_btn.configure(text="Download")
        self._stop_btn.config(state=tk.DISABLED)

    def _show_error(self, msg: str):
        messagebox.showerror("Error", msg)

    # ── UI actions ───────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = SerialHandler.list_ports()
        self._port_combo['values'] = ports
        if ports and not self._port_var.get():
            self._port_combo.current(0)

    def _connect(self):
        if self._connected:
            self._disconnect()
            return

        port = self._port_var.get()
        if not port:
            messagebox.showwarning("Warning", "Please select a serial port.")
            return

        try:
            baudrate = int(self._baud_var.get())
        except ValueError:
            messagebox.showwarning("Warning", "Invalid baud rate.")
            return

        try:
            self.serial.open(port, baudrate)
            self._connected = True
            self._connect_btn.configure(text="Disconnect")
            self._status_label.config(text=f"Connected to {port} @ {baudrate}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open serial port:\n{e}")
            return

        self._update_state()

    def _disconnect(self):
        self.serial.close()
        self._connected = False
        self._connect_btn.configure(text="Connect")
        self._status_label.config(text="Disconnected.")
        self._update_state()

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Select file to download")
        if path:
            self._filepath = path
            self._file_entry.configure(state=tk.NORMAL)
            self._file_entry.delete(0, tk.END)
            self._file_entry.insert(0, path)
            self._file_entry.configure(state='readonly')
            self._update_state()

    def _start_download(self):
        if self._downloading:
            return
        if not self._filepath or not os.path.isfile(self._filepath):
            messagebox.showwarning("Warning", "Please select a valid file.")
            return

        self._downloading = True
        self._download_btn.configure(text="Download", state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._progress_bar.configure(mode='indeterminate')
        self._progress_bar.start()

        self.download.start(self._filepath)

        # Send CMD 9
        packet = self.download.build_request_packet()
        self.serial.send(packet)

    def _stop_download(self):
        self.download.stop()
        self._status_label.config(text="Stopping...")

    # ── State management ─────────────────────────────────────────────────

    def _update_state(self):
        # Port controls
        can_connect = not self._connected and not self._downloading
        self._port_combo.config(state='readonly' if not self._connected else tk.DISABLED)
        self._baud_combo.config(state='readonly' if not self._connected else tk.DISABLED)
        self._refresh_btn.config(state=tk.NORMAL if not self._connected else tk.DISABLED)

        # File button
        self._browse_btn.config(state=tk.NORMAL if not self._downloading else tk.DISABLED)

        # Connect button
        if self._connected:
            self._connect_btn.configure(state=tk.NORMAL if not self._downloading else tk.DISABLED)
        else:
            self._connect_btn.configure(state=tk.NORMAL)

        # Download button: need connected + file selected + not already downloading
        can_download = self._connected and bool(self._filepath) and not self._downloading
        if not self._downloading:
            self._download_btn.configure(state=tk.NORMAL if can_download else tk.DISABLED)

        # Stop button
        self._stop_btn.configure(state=tk.NORMAL if self._downloading else tk.DISABLED)

    # ── UI layout ────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        # ── Serial settings ──
        serial_frame = ttk.LabelFrame(self.root, text="Serial Port Settings")
        serial_frame.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(serial_frame)
        row1.pack(fill=tk.X, **pad)

        ttk.Label(row1, text="Port:").pack(side=tk.LEFT)
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(row1, textvariable=self._port_var, width=15, state='readonly')
        self._port_combo.pack(side=tk.LEFT, padx=4)

        self._refresh_btn = ttk.Button(row1, text="Refresh", command=self._refresh_ports, width=7)
        self._refresh_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(row1, text="Baud Rate:").pack(side=tk.LEFT, padx=(16, 0))
        self._baud_var = tk.StringVar(value='115200')
        self._baud_combo = ttk.Combobox(row1, textvariable=self._baud_var,
                                         values=[str(b) for b in BAUD_RATES], width=10)
        self._baud_combo.pack(side=tk.LEFT, padx=4)

        self._connect_btn = ttk.Button(row1, text="Connect", command=self._connect, width=9)
        self._connect_btn.pack(side=tk.RIGHT, padx=4)

        # ── File selection ──
        file_frame = ttk.LabelFrame(self.root, text="File Selection")
        file_frame.pack(fill=tk.X, **pad)

        file_row = ttk.Frame(file_frame)
        file_row.pack(fill=tk.X, **pad)

        self._file_entry = ttk.Entry(file_row, state='readonly')
        self._file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self._browse_btn = ttk.Button(file_row, text="Browse...", command=self._browse_file, width=10)
        self._browse_btn.pack(side=tk.RIGHT)

        # ── Progress ──
        progress_frame = ttk.LabelFrame(self.root, text="Progress")
        progress_frame.pack(fill=tk.X, **pad)

        self._progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self._progress_bar.pack(fill=tk.X, **pad)

        self._status_label = ttk.Label(progress_frame, text="Ready.", anchor=tk.W)
        self._status_label.pack(fill=tk.X, **pad)

        # ── Action buttons ──
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill=tk.X, **pad)

        self._download_btn = ttk.Button(action_frame, text="Download",
                                        command=self._start_download, state=tk.DISABLED)
        self._download_btn.pack(side=tk.LEFT, padx=4)

        self._stop_btn = ttk.Button(action_frame, text="Stop",
                                    command=self._stop_download, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.LEFT, padx=4)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
