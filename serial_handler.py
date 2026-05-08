"""Serial port communication with background read thread."""

import threading
import serial
import serial.tools.list_ports
from protocol import HEADER, OVERHEAD, parse_packet_header


class SerialHandler:
    def __init__(self):
        self._port = None
        self._lock = threading.Lock()
        self._read_thread = None
        self._running = False
        self._packet_callback = None
        self._error_callback = None

    @staticmethod
    def list_ports() -> list[str]:
        """Return list of available serial port names."""
        ports = serial.tools.list_ports.comports()
        return [p.device for p in sorted(ports)]

    def open(self, port: str, baudrate: int = 115200):
        """Open a serial port."""
        self._port = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )
        self._running = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

    def close(self):
        """Close the serial port."""
        self._running = False
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
                self._port = None

    def is_open(self) -> bool:
        """Check if port is open."""
        with self._lock:
            return self._port is not None and self._port.is_open

    def set_packet_callback(self, callback):
        """Set callback for received packets: callback(packet_bytes)."""
        self._packet_callback = callback

    def set_error_callback(self, callback):
        """Set callback for errors: callback(error_message)."""
        self._error_callback = callback

    def send(self, data: bytes):
        """Send raw data over serial."""
        with self._lock:
            if self._port and self._port.is_open:
                self._port.write(data)

    def _read_loop(self):
        """Background thread: read bytes and assemble complete packets."""
        buf = bytearray()
        while self._running:
            try:
                with self._lock:
                    if not self._port or not self._port.is_open:
                        break
                    waiting = self._port.in_waiting
                    if waiting > 0:
                        chunk = self._port.read(waiting)
                if waiting > 0:
                    buf.extend(chunk)
            except (serial.SerialException, OSError) as e:
                if self._error_callback:
                    self._error_callback(f"Serial read error: {e}")
                break

            # Try to extract complete packets from buffer
            while True:
                pkt = self._extract_packet(buf)
                if pkt is None:
                    break
                if self._packet_callback:
                    self._packet_callback(pkt)

            # Prevent buffer growing too large (keep last ~1MB max)
            if len(buf) > 1024 * 1024:
                buf = buf[-65536:]

    def _extract_packet(self, buf: bytearray) -> bytes | None:
        """Try to extract one complete, valid packet from buffer. Returns packet or None."""
        # Find header
        try:
            idx = buf.index(HEADER)
        except ValueError:
            buf.clear()
            return None

        if idx > 0:
            # Discard bytes before header
            del buf[:idx]

        # Need at least enough bytes to read length
        if len(buf) < 1 + 2:
            return None

        length = (buf[1] << 8) | buf[2]

        if length < OVERHEAD or length > 65536:
            # Invalid length, discard header and retry
            del buf[0]
            return None

        if len(buf) < length:
            return None

        # Extract packet
        packet = bytes(buf[:length])
        del buf[:length]
        return packet
