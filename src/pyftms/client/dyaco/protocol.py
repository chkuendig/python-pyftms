# Copyright 2024-2025
# SPDX-License-Identifier: Apache-2.0

"""
Dyaco UART protocol parser.

This module parses the proprietary UART protocol used by Dyaco fitness equipment.
The protocol is reverse-engineered from the SOLE Fitness App (ideabussdk_sole SDK).

Protocol format:
    [0x5B] [LENGTH] [CMD] [DATA...] [0x5D]
    '['    1 byte   1+    variable   ']'

Data is transmitted as hex-encoded bytes.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .const import START_BYTE, END_BYTE


class Command(IntEnum):
    """Protocol command codes."""
    SET_MODE = 0x02
    GET_MODE = 0x03
    SET_WORKOUT_TIME = 0x04
    GET_WORKOUT_DATA = 0x06
    SET_USER_PROFILE = 0x07
    SET_PROGRAM_MODE = 0x08
    END_WORKOUT = 0x32
    DEVICE_INFO = 0xF0
    DEVICE_STATUS = 0xF1


class DeviceType(IntEnum):
    """Equipment type determined from model number."""
    TREADMILL = 0
    ELLIPTICAL = 1
    BIKE = 2


class WorkoutMode(IntEnum):
    """Workout/operating mode."""
    STOP = 0x01
    IDLE = 0x02
    RUNNING = 0x03
    PAUSE = 0x04
    COOLDOWN = 0x05
    SUMMARY = 0x06
    SLEEP = 0x07
    READY = 0x80  # BLE not linked to workout


@dataclass
class DyacoDeviceInfo:
    """Device information from DEVICE_INFO (0xF0) response."""
    model: int = 0
    device_type: DeviceType = DeviceType.TREADMILL
    unit: int = 0  # 0 = metric, 1 = imperial
    max_speed: int = 0  # tenths of km/h
    min_speed: int = 0
    max_incline: int = 0
    max_level: int = 0

    @property
    def is_metric(self) -> bool:
        return self.unit == 0


@dataclass
class DyacoWorkoutData:
    """Real-time workout data from GET_WORKOUT_DATA (0x06) response."""
    minutes: int = 0
    seconds: int = 0
    distance: float = 0.0  # km
    calories: float = 0.0
    heart_rate: int = 0
    speed: float = 0.0  # km/h
    incline: int = 0  # %
    rpm: int = 0
    level: int = 0
    watt: int = 0

    @property
    def time_elapsed(self) -> int:
        """Total elapsed time in seconds."""
        return self.minutes * 60 + self.seconds

    @property
    def distance_meters(self) -> int:
        """Distance in meters."""
        return int(self.distance * 1000)


class DyacoProtocolParser:
    """
    Parser for Dyaco UART protocol messages.

    Usage:
        parser = DyacoProtocolParser()
        messages = parser.feed(raw_bytes)
        for msg in messages:
            if isinstance(msg, DyacoWorkoutData):
                print(f"Speed: {msg.speed}")
    """

    def __init__(self) -> None:
        self.device_info: DyacoDeviceInfo | None = None
        self._buffer = ""

    def feed(self, data: bytes) -> list[Any]:
        """
        Feed raw BLE data into the parser.

        Args:
            data: Raw bytes received from BLE notification

        Returns:
            List of parsed messages (DyacoWorkoutData, DyacoDeviceInfo, dict)
        """
        # Convert bytes to hex string
        hex_str = data.hex().upper()
        self._buffer += hex_str
        messages = []

        while True:
            # Find start marker
            start_idx = self._buffer.find("5B")
            if start_idx == -1:
                self._buffer = ""
                break

            # Trim anything before start
            if start_idx > 0:
                self._buffer = self._buffer[start_idx:]

            # Need at least header: 5B + length(2) + cmd(2) + 5D = 8 chars
            if len(self._buffer) < 8:
                break

            # Parse length
            try:
                length = int(self._buffer[2:4], 16)
            except ValueError:
                self._buffer = self._buffer[2:]
                continue

            # Full message length: 5B(2) + len(2) + data(length*2) + 5D(2)
            msg_len = 2 + 2 + (length * 2) + 2

            if len(self._buffer) < msg_len:
                break  # Wait for more data

            # Check end marker
            if self._buffer[msg_len - 2:msg_len] != "5D":
                self._buffer = self._buffer[2:]
                continue

            # Extract and parse message
            msg = self._buffer[:msg_len]
            self._buffer = self._buffer[msg_len:]

            parsed = self._parse_message(msg)
            if parsed is not None:
                messages.append(parsed)

        return messages

    def _parse_message(self, msg: str) -> Any:
        """Parse a complete message."""
        inner = msg[2:-2]  # Remove 5B and 5D

        if len(inner) < 4:
            return None

        cmd = int(inner[2:4], 16)

        # Handle 00 XX prefix format
        if cmd == 0 and len(inner) >= 6:
            cmd = int(inner[4:6], 16)

        try:
            if cmd == Command.DEVICE_INFO:
                return self._parse_device_info(inner)
            elif cmd == Command.GET_WORKOUT_DATA:
                return self._parse_workout_data(inner)
            elif cmd == Command.GET_MODE:
                return self._parse_mode(inner)
            elif cmd == Command.END_WORKOUT:
                return self._parse_end_workout(inner)
            else:
                return {"cmd": cmd, "raw": inner}
        except Exception as e:
            return {"cmd": cmd, "error": str(e), "raw": inner}

    def _parse_device_info(self, data: str) -> DyacoDeviceInfo:
        """Parse DEVICE_INFO (0xF0) response."""
        info = DyacoDeviceInfo()

        info.model = int(data[4:6], 16)
        # data[6:8] = sales_version
        info.unit = int(data[8:10], 16)

        # Determine device type from model number
        model = info.model
        if 128 <= model < 192:
            info.device_type = DeviceType.TREADMILL
        elif model in (0, 1, 2, 14, 84, 85, 87, 88) or \
             (16 <= model < 22) or (37 <= model < 39) or (96 <= model < 98):
            info.device_type = DeviceType.ELLIPTICAL
        elif model == 39 or (3 <= model < 16) or (22 <= model < 32) or \
             (48 <= model < 64) or (83 <= model <= 86) or \
             (99 <= model <= 106) or (112 <= model <= 119):
            info.device_type = DeviceType.BIKE
        else:
            info.device_type = DeviceType.ELLIPTICAL  # default

        # Parse device-specific parameters
        if info.device_type == DeviceType.TREADMILL:
            if len(data) >= 18:
                info.max_speed = int(data[10:12], 16)
                info.min_speed = int(data[12:14], 16)
                info.max_incline = int(data[14:16], 16)
        else:  # Elliptical or Bike
            if len(data) >= 14:
                info.max_incline = int(data[10:12], 16)
                info.max_level = int(data[12:14], 16)

        self.device_info = info
        return info

    def _parse_workout_data(self, data: str) -> DyacoWorkoutData:
        """Parse GET_WORKOUT_DATA (0x06) response."""
        workout = DyacoWorkoutData()

        workout.minutes = int(data[4:6], 16)
        workout.seconds = int(data[6:8], 16)

        raw_distance = int(data[8:12], 16)
        raw_calories = int(data[12:16], 16)

        workout.distance = raw_distance / 100.0
        workout.heart_rate = int(data[16:18], 16)

        device_type = self.device_info.device_type if self.device_info else DeviceType.TREADMILL

        if device_type == DeviceType.TREADMILL:
            workout.calories = raw_calories / 1.0
            workout.speed = int(data[18:20], 16) / 10.0
            workout.incline = int(data[20:22], 16)
        else:  # Elliptical or Bike
            workout.calories = raw_calories / 10.0
            workout.rpm = int(data[18:20], 16)
            workout.speed = int(data[20:24], 16) / 100.0 if len(data) >= 24 else 0
            if len(data) >= 28:
                workout.watt = int(data[24:28], 16)

        return workout

    def _parse_mode(self, data: str) -> dict[str, Any]:
        """Parse GET_MODE (0x03) response."""
        mode_val = int(data[4:6], 16)
        try:
            mode = WorkoutMode(mode_val)
            mode_name = mode.name
        except ValueError:
            mode_name = f"UNKNOWN(0x{mode_val:02X})"
        return {
            "cmd": Command.GET_MODE,
            "mode": mode_val,
            "mode_name": mode_name,
        }

    def _parse_end_workout(self, data: str) -> dict[str, Any]:
        """Parse END_WORKOUT (0x32) response."""
        return {
            "cmd": Command.END_WORKOUT,
            "total_seconds": int(data[4:8], 16),
            "distance": int(data[8:12], 16) / 100.0,
            "calories": int(data[12:16], 16),
        }


def build_echo_mode_command(mode: int) -> bytes:
    """
    Build an echo command for WorkoutMode (passive monitoring technique).

    When the equipment sends a WorkoutMode (0x03) message, echoing it back
    unchanged keeps the data stream flowing WITHOUT taking control from the console.

    Args:
        mode: The mode value received from the equipment

    Returns:
        Command bytes to send back
    """
    payload = f"03{mode:02X}"
    length = len(payload) // 2
    frame = f"5B{length:02X}{payload}5D"
    return bytes.fromhex(frame)


def build_device_info_command() -> bytes:
    """
    Build a DEVICE_INFO (0xF0) request command.

    This command queries the equipment for its model number, device type,
    capabilities (max speed, max incline, etc.). The response helps parse
    workout data correctly (treadmill vs bike format differs).

    This is a read-only query and does NOT affect console control.

    Returns:
        Command bytes: [5B][01][F0][5D]
    """
    # DEVICE_INFO command: 0xF0, no payload
    return bytes.fromhex("5B01F05D")
