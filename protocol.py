"""Protocol packet encoding/decoding per the specification.

Packet format:
  Header(0x59) | DataLength(uint16) | Command(uint16) | Data(uint8...) | Checksum(uint16)

All multi-byte values are big-endian.
Checksum is the uint16 sum from Header through last Data byte.
"""

import struct

HEADER = 0x59

# Commands
CMD_FILE_DOWNLOAD_REQUEST = 9
CMD_FILE_DOWNLOAD_DATA = 10
CMD_FILE_DOWNLOAD_RESULT = 11

# Result codes
RESULT_TRUE = 0x01
RESULT_FALSE = 0x00

# Fixed sizes
HEADER_SIZE = 1
LENGTH_SIZE = 2
CMD_SIZE = 2
CHECKSUM_SIZE = 2
OVERHEAD = HEADER_SIZE + LENGTH_SIZE + CMD_SIZE + CHECKSUM_SIZE  # 7 bytes


def _checksum(data: bytes) -> int:
    """Calculate uint16 checksum (sum of all bytes, truncated to 16 bits)."""
    return sum(data) & 0xFFFF


def build_packet(command: int, payload: bytes = b'') -> bytes:
    """Build a complete packet with header, length, command, data, and checksum."""
    data = struct.pack('>H', command) + payload
    length = OVERHEAD + len(payload)
    header_and_len_and_data = struct.pack('>BH', HEADER, length) + data
    csum = _checksum(header_and_len_and_data)
    return header_and_len_and_data + struct.pack('>H', csum)


def parse_packet_header(data: bytes) -> tuple[int, int, int]:
    """Parse header, length, command from packet data. Returns (length, command, payload_offset)."""
    if len(data) < OVERHEAD:
        raise ValueError(f"Packet too short: {len(data)} bytes, need at least {OVERHEAD}")
    header = data[0]
    if header != HEADER:
        raise ValueError(f"Invalid header: 0x{header:02X}, expected 0x{HEADER:02X}")
    length = struct.unpack('>H', data[1:3])[0]
    command = struct.unpack('>H', data[3:5])[0]
    return length, command


def verify_packet(data: bytes) -> bool:
    """Verify the checksum of a complete packet. Returns True if valid."""
    if len(data) < OVERHEAD:
        return False
    declared_length = struct.unpack('>H', data[1:3])[0]
    if len(data) != declared_length:
        return False
    payload_len = declared_length - OVERHEAD
    check_data = data[:5 + payload_len]  # header + length + command + data
    expected_csum = _checksum(check_data)
    actual_csum = struct.unpack('>H', data[5 + payload_len:5 + payload_len + 2])[0]
    return expected_csum == actual_csum


# ── Command 9: File Download Request ──────────────────────────────────────

def build_download_request(file_size: int, file_crc32: int, filename: str) -> bytes:
    """Build Command 9 downlink packet (PC -> Device)."""
    filename_bytes = filename.encode('ascii')
    payload = struct.pack('>II', file_size, file_crc32) + filename_bytes
    return build_packet(CMD_FILE_DOWNLOAD_REQUEST, payload)


def parse_download_response(data: bytes) -> bool:
    """Parse Command 9 uplink (Device -> PC). Returns True if device accepts."""
    length, command = parse_packet_header(data)
    if command != CMD_FILE_DOWNLOAD_REQUEST:
        raise ValueError(f"Unexpected command: {command}")
    payload_len = length - OVERHEAD
    result = data[5]  # first byte after command
    return result == RESULT_TRUE


# ── Command 10: File Download Data ────────────────────────────────────────

def build_data_packet(seq: int, data_chunk: bytes) -> bytes:
    """Build Command 10 downlink (PC -> Device) - a chunk of file data."""
    payload = struct.pack('>IH', seq, len(data_chunk)) + data_chunk
    return build_packet(CMD_FILE_DOWNLOAD_DATA, payload)


def parse_data_request(data: bytes) -> tuple[int, int]:
    """Parse Command 10 uplink (Device -> PC). Returns (packet_size, seq_number)."""
    length, command = parse_packet_header(data)
    if command != CMD_FILE_DOWNLOAD_DATA:
        raise ValueError(f"Unexpected command: {command}")
    payload_len = length - OVERHEAD
    payload = data[5:5 + payload_len]
    packet_size, seq = struct.unpack('>HI', payload)
    return packet_size, seq


# ── Command 11: File Download Result ──────────────────────────────────────

def parse_download_result(data: bytes) -> bool:
    """Parse Command 11 uplink (Device -> PC). Returns True if success."""
    length, command = parse_packet_header(data)
    if command != CMD_FILE_DOWNLOAD_RESULT:
        raise ValueError(f"Unexpected command: {command}")
    result = data[5]
    return result == RESULT_TRUE
