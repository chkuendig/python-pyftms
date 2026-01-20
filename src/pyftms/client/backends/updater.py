# Copyright 2024, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0
#
# PATCHED: Handle truncated/malformed data gracefully for non-compliant FTMS devices
# ==================================================================================
#
# ISSUE: Sole treadmills (F65, F80, F63, etc.) send truncated FTMS Treadmill Data
# that doesn't fully comply with the FTMS spec. The standard deserializer throws
# EOFError when it runs out of bytes before parsing all expected fields.
#
# FTMS TREADMILL DATA FORMAT (from Bluetooth FTMS spec, characteristic 0x2ACD):
#   - Bytes 0-1: Flags (16-bit little-endian)
#   - If bit 0 of flags is NOT set: bytes 2-3 contain Instantaneous Speed (uint16, 0.01 km/h resolution)
#   - Additional fields follow based on flag bits (avg speed, distance, incline, etc.)
#
# SOURCES/REFERENCES:
#   - qdomyos-zwift: src/solef80treadmill.cpp (characteristicChanged method)
#     Shows speed extraction: Speed = (uint16)(value[2] | value[3]<<8) * 0.01
#     https://github.com/cagnulein/qdomyos-zwift
#
#   - treadonme: Go library for Sole BLE treadmills
#     WorkoutData message parsing shows same byte layout
#     https://github.com/AJGherber/treadonme
#
#   - Bluetooth FTMS Specification (Fitness Machine Service)
#     Section 4.9: Treadmill Data characteristic (0x2ACD)
#
# PATCH BEHAVIOR:
#   When deserialization fails, we attempt to manually extract instantaneous speed
#   from bytes 2-3 (after the 2-byte flags field). This provides basic functionality
#   even when the device sends incomplete data packets.
#
import logging
from typing import Any, cast

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from ...models import RealtimeData
from ...serializer import ModelSerializer, get_serializer
from .event import FtmsCallback, UpdateEvent, UpdateEventData

_LOGGER = logging.getLogger(__name__)


class DataUpdater:
    _serializer: ModelSerializer[RealtimeData]

    def __init__(self, model: type[RealtimeData], callback: FtmsCallback) -> None:
        self._cb = callback
        self._serializer = get_serializer(model)
        self._prev: dict[str, Any] = {}
        self._result: dict[str, Any] = {}

    def reset(self) -> None:
        """Resetting state. Call while disconnection event."""
        self._prev.clear()
        self._result.clear()

    async def subscribe(self, cli: BleakClient, uuid: str) -> None:
        """Subscribe for notification."""
        self.reset()
        await cli.start_notify(uuid, self._on_notify)

    def _on_notify(self, c: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("Received notify: %s", data.hex(" ").upper())
        
        # PATCH: Catch deserialization errors for non-compliant FTMS devices
        try:
            data_ = self._serializer.deserialize(data)._asdict()
        except (EOFError, AssertionError, ValueError) as e:
            _LOGGER.debug(
                "Failed to deserialize FTMS data (device may not be fully compliant): %s. "
                "Raw data: %s",
                e,
                data.hex(" ").upper()
            )
            # Try to extract at least speed from truncated data
            # Standard FTMS treadmill data: flags (2 bytes) + speed (2 bytes)
            if len(data) >= 4:
                try:
                    flags = int.from_bytes(data[0:2], "little")
                    # Check if speed is present (bit 0 NOT set means instant speed present)
                    if not (flags & 1):
                        speed_raw = int.from_bytes(data[2:4], "little")
                        speed = speed_raw * 0.01  # Convert to km/h
                        data_ = {"speed_instant": speed}
                        _LOGGER.debug("Extracted speed from truncated data: %.2f km/h", speed)
                    else:
                        return
                except Exception:
                    return
            else:
                return
        
        _LOGGER.debug("Received notify dict: %s", data_)
        self._result |= data_

        # If `More Data` bit is set - we must wait for other messages.
        if data[0] & 1:
            _LOGGER.debug("'More Data' bit is set. Waiting for next data.")
            return

        # My device sends a lot of null packets during wakeup and sleep mode.
        # So I just filter null packets.
        if any(self._result.values()):
            update = self._result.items() ^ self._prev.items()

            if update := {k: self._result[k] for k, _ in update}:
                _LOGGER.debug("Update data: %s", update)
                update = cast(UpdateEventData, update)  # unsafe casting
                update = UpdateEvent(event_id="update", event_data=update)
                self._cb(update)
                self._prev = self._result.copy()

        self._result.clear()
