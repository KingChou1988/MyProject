"""Download manager - state machine for the file download protocol."""

import os
import struct
import threading
from enum import Enum

from protocol import (
    HEADER, OVERHEAD,
    CMD_FILE_DOWNLOAD_REQUEST, CMD_FILE_DOWNLOAD_DATA, CMD_FILE_DOWNLOAD_RESULT,
    RESULT_TRUE, RESULT_FALSE,
    build_download_request, build_data_packet,
    parse_data_request, parse_download_result, parse_download_response,
)
from crc32 import crc32_file


class DownloadState(Enum):
    IDLE = "idle"
    REQUESTING = "requesting"      # Sent CMD 9, waiting for response
    TRANSFERRING = "transferring"  # Sending data packets (CMD 10)
    WAITING_RESULT = "waiting_result"  # Waiting for CMD 11
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


class DownloadManager:
    def __init__(self):
        self._state = DownloadState.IDLE
        self._filepath = ""
        self._file_size = 0
        self._file_crc = 0
        self._filename = ""
        self._file_handle = None
        self._last_seq = -1
        self._total_packets = 0
        self._lock = threading.Lock()
        self._stop_requested = False

        self._send_callback = None      # (bytes)

        # Callbacks (set from GUI thread)
        self.on_progress = None       # (seq, total, chunk_size)
        self.on_state_change = None   # (new_state)
        self.on_error = None          # (message)

    @property
    def state(self) -> DownloadState:
        with self._lock:
            return self._state

    @state.setter
    def state(self, value: DownloadState):
        with self._lock:
            self._state = value
        if self.on_state_change:
            self.on_state_change(value)

    def start(self, filepath: str):
        """Initialize download with a file. Call after serial is connected."""
        self._filepath = filepath
        self._file_size = os.path.getsize(filepath)
        self._file_crc = crc32_file(filepath)
        self._filename = os.path.basename(filepath)
        self._stop_requested = False
        self._last_seq = -1

        # Open file for reading
        if self._file_handle:
            self._file_handle.close()
        self._file_handle = open(filepath, 'rb')

        self.state = DownloadState.REQUESTING

    def stop(self):
        """Request download stop."""
        self._stop_requested = True
        if self.state not in (DownloadState.DONE, DownloadState.ERROR):
            self.state = DownloadState.STOPPED
        self._close_file()

    def _close_file(self):
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

    def build_request_packet(self) -> bytes:
        """Build Command 9 packet to send to device."""
        return build_download_request(self._file_size, self._file_crc, self._filename)

    def handle_packet(self, packet: bytes):
        """Process an incoming packet. Called from serial read thread."""
        if self._stop_requested:
            return

        if len(packet) < OVERHEAD:
            return

        # Parse command from packet (bytes 3-4, big-endian uint16)
        command = (packet[3] << 8) | packet[4]

        try:
            if command == CMD_FILE_DOWNLOAD_REQUEST and self.state == DownloadState.REQUESTING:
                self._handle_cmd9_response(packet)

            elif command == CMD_FILE_DOWNLOAD_DATA and self.state == DownloadState.TRANSFERRING:
                self._handle_cmd10_request(packet)

            elif command == CMD_FILE_DOWNLOAD_RESULT:
                self._handle_cmd11_result(packet)

        except Exception as e:
            self.state = DownloadState.ERROR
            if self.on_error:
                self.on_error(f"Protocol error: {e}")
            self._close_file()

    def _handle_cmd9_response(self, packet: bytes):
        """Handle device response to file download request."""
        accepted = parse_download_response(packet)
        if accepted:
            self.state = DownloadState.TRANSFERRING
        else:
            self.state = DownloadState.ERROR
            if self.on_error:
                self.on_error("Device rejected the download request.")

    def _handle_cmd10_request(self, packet: bytes):
        """Handle device data request (CMD 10 uplink)."""
        if not self._file_handle:
            return

        packet_size, seq = parse_data_request(packet)
        if packet_size < 1 or packet_size > 32768:
            self.state = DownloadState.ERROR
            if self.on_error:
                self.on_error(f"Invalid packet size from device: {packet_size}")
            return

        self._last_seq = seq

        offset = seq * packet_size
        if offset >= self._file_size:
            # Device is requesting beyond file end - all data sent
            self.state = DownloadState.WAITING_RESULT
            return

        self._file_handle.seek(offset)
        chunk = self._file_handle.read(packet_size)

        if not chunk:
            self.state = DownloadState.WAITING_RESULT
            return

        response = build_data_packet(seq, chunk)

        total = max(1, (self._file_size + packet_size - 1) // packet_size)
        if self.on_progress:
            self.on_progress(seq + 1, total, len(chunk))

        if self._send_callback:
            self._send_callback(response)

    def set_send_callback(self, callback):
        """Set callback for sending data: callback(bytes)."""
        self._send_callback = callback

    def _handle_cmd11_result(self, packet: bytes):
        """Handle download result from device."""
        success = parse_download_result(packet)
        if success:
            self.state = DownloadState.DONE
        else:
            self.state = DownloadState.ERROR
            if self.on_error:
                self.on_error("Device reported download failure.")
        self._close_file()
