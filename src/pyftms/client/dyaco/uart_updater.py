# Copyright 2024-2025
# SPDX-License-Identifier: Apache-2.0

"""
UART updater for Dyaco equipment.

This module handles UART notifications from Dyaco equipment and converts them
to pyftms UpdateEvents. It uses passive monitoring (echo technique) to avoid
locking out the equipment's console.
"""

import logging
from typing import Any, cast

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService

from ..backends.event import FtmsCallback, UpdateEvent, UpdateEventData
from .const import (
    UART_SERVICE_UUID,
    UART_NOTIFY_CHAR_UUID,
    UART_WRITE_CHAR_UUID,
    UART_SECONDARY_SERVICE_UUID,
    UART_SECONDARY_NOTIFY_CHAR_UUID,
    UART_SECONDARY_WRITE_CHAR_UUID,
)
from .protocol import (
    Command,
    DyacoProtocolParser,
    DyacoWorkoutData,
    DyacoDeviceInfo,
    DeviceType,
    build_echo_mode_command,
    build_device_info_command,
)

_LOGGER = logging.getLogger(__name__)


class DyacoUartUpdater:
    """
    UART data updater for Dyaco equipment.

    Uses passive monitoring via the "echo technique":
    - Subscribes to UART notifications
    - Echoes WorkoutMode (0x03) messages back to keep data flowing
    - Does NOT send SET_MODE, so console retains control

    The updater emits pyftms UpdateEvents through the provided callback,
    making it compatible with the existing event system.
    """

    def __init__(self, callback: FtmsCallback) -> None:
        """
        Initialize the UART updater.

        Args:
            callback: pyftms event callback for emitting UpdateEvents
        """
        self._cb = callback
        self._parser = DyacoProtocolParser()
        self._prev: dict[str, Any] = {}
        self._cli: BleakClient | None = None
        self._write_char: str | None = None
        self._notify_char: str | None = None
        self._echo_count = 0

    def reset(self) -> None:
        """Reset state on disconnection."""
        self._prev.clear()
        self._cli = None
        self._write_char = None
        self._notify_char = None
        self._echo_count = 0

    @property
    def device_info(self) -> DyacoDeviceInfo | None:
        """Device info from UART protocol (if received)."""
        return self._parser.device_info

    @staticmethod
    def find_uart_service(cli: BleakClient) -> BleakGATTService | None:
        """
        Find UART service in discovered BLE services.

        The presence of the ISSC Transparent UART service (UUID prefix "49535343")
        indicates Dyaco equipment. This service UUID is vendor-specific to ISSC
        Technologies (now Microchip) BLE chips used by all Dyaco brands.

        Args:
            cli: Connected BleakClient

        Returns:
            UART service if found, None otherwise
        """
        for service in cli.services:
            service_uuid = str(service.uuid).lower()
            if service_uuid == UART_SERVICE_UUID.lower():
                return service
            if service_uuid == UART_SECONDARY_SERVICE_UUID.lower():
                return service
        return None

    async def subscribe(self, cli: BleakClient) -> None:
        """
        Subscribe to UART notifications for Dyaco equipment.

        This method should only be called after confirming this is Dyaco equipment
        (via device name prefix AND UART service UUID check in client.py).

        The ISSC Transparent UART service (UUID prefix "49535343" = ASCII "ISSC")
        is vendor-specific to ISSC Technologies (now Microchip) BLE chips used by
        all Dyaco brands (SOLE, Spirit, XTERRA, Fuel).

        Args:
            cli: Connected BleakClient (must be confirmed Dyaco equipment)

        Raises:
            RuntimeError: If UART service is not found (should not happen if
                          detection in client.py is working correctly)
        """
        self.reset()
        self._cli = cli

        # Find UART service - should always exist since client.py already verified it
        service = self.find_uart_service(cli)
        if not service:
            raise RuntimeError(
                "Dyaco UART service not found. This indicates a bug in device detection - "
                "subscribe() should only be called for confirmed Dyaco equipment."
            )

        service_uuid = str(service.uuid).lower()
        _LOGGER.info("Found Dyaco UART service: %s", service.uuid)

        # Determine which characteristics to use based on service
        if service_uuid == UART_SERVICE_UUID.lower():
            notify_uuid = UART_NOTIFY_CHAR_UUID
            write_uuid = UART_WRITE_CHAR_UUID
        else:
            notify_uuid = UART_SECONDARY_NOTIFY_CHAR_UUID
            write_uuid = UART_SECONDARY_WRITE_CHAR_UUID

        # Find characteristics
        for char in service.characteristics:
            char_uuid = str(char.uuid).lower()
            if char_uuid == notify_uuid.lower():
                self._notify_char = str(char.uuid)
            elif char_uuid == write_uuid.lower():
                self._write_char = str(char.uuid)

        if not self._notify_char:
            raise RuntimeError(
                "Dyaco UART notify characteristic not found in service. "
                "This may indicate incompatible firmware."
            )

        # Subscribe to notifications
        await cli.start_notify(self._notify_char, self._on_notify)
        _LOGGER.info("Subscribed to Dyaco UART notifications")

        # Request device info (0xF0) to get model details
        # This helps parse workout data correctly (treadmill vs bike format differs)
        if self._write_char:
            await self._request_device_info()

    async def _request_device_info(self) -> None:
        """
        Request device info via 0xF0 command.

        This queries the equipment for model number, device type, and capabilities
        (max speed, max incline, etc.). The response is handled in _on_notify.
        """
        try:
            if self._cli and self._cli.is_connected and self._write_char:
                cmd = build_device_info_command()
                await self._cli.write_gatt_char(self._write_char, cmd, response=False)
                _LOGGER.debug("Requested device info (0xF0)")
        except Exception as e:
            _LOGGER.debug("Failed to request device info: %s", e)

    def _on_notify(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle incoming UART notification."""
        raw = bytes(data)
        _LOGGER.debug("Dyaco UART RX: %s", raw.hex(" ").upper())

        messages = self._parser.feed(raw)

        for msg in messages:
            if isinstance(msg, dict) and msg.get("cmd") == Command.GET_MODE:
                # WorkoutMode message - echo it back for passive monitoring
                self._handle_mode(msg.get("mode", 0))

            elif isinstance(msg, DyacoDeviceInfo):
                _LOGGER.info(
                    "Dyaco device: type=%s, model=%d, max_speed=%d, max_incline=%d",
                    msg.device_type.name,
                    msg.model,
                    msg.max_speed,
                    msg.max_incline,
                )

            elif isinstance(msg, DyacoWorkoutData):
                self._handle_workout_data(msg)

    def _handle_mode(self, mode: int) -> None:
        """Echo WorkoutMode back for passive monitoring."""
        if self._cli and self._cli.is_connected and self._write_char:
            try:
                cmd = build_echo_mode_command(mode)
                # Use create_task to avoid blocking the notification handler
                import asyncio
                asyncio.create_task(self._echo_mode(cmd))
            except Exception as e:
                _LOGGER.debug("Failed to create echo task: %s", e)

    async def _echo_mode(self, cmd: bytes) -> None:
        """Send echo command asynchronously."""
        try:
            if self._cli and self._cli.is_connected and self._write_char:
                await self._cli.write_gatt_char(self._write_char, cmd, response=False)
                self._echo_count += 1
                _LOGGER.debug("Echoed mode (count: %d)", self._echo_count)
        except Exception as e:
            _LOGGER.debug("Failed to echo mode: %s", e)

    def _handle_workout_data(self, data: DyacoWorkoutData) -> None:
        """Convert UART workout data to pyftms UpdateEvent."""
        device_type = self._parser.device_info.device_type if self._parser.device_info else DeviceType.TREADMILL

        # Map Dyaco data to pyftms UpdateEventData fields
        update: dict[str, Any] = {}

        # Time
        if data.time_elapsed > 0:
            update["time_elapsed"] = data.time_elapsed

        # Speed (always in km/h)
        if data.speed > 0:
            update["speed_instant"] = data.speed

        # Distance (pyftms uses meters)
        if data.distance > 0:
            update["distance_total"] = data.distance_meters

        # Calories
        if data.calories > 0:
            update["energy_total"] = int(data.calories)

        # Heart rate
        if data.heart_rate > 0:
            update["heart_rate"] = data.heart_rate

        # Device-specific fields
        if device_type == DeviceType.TREADMILL:
            # Inclination (%)
            if data.incline >= 0:
                update["inclination"] = float(data.incline)
        else:
            # Bikes and ellipticals
            if data.rpm > 0:
                update["cadence_instant"] = float(data.rpm)
            if data.level > 0:
                update["resistance_level"] = data.level
            if data.watt > 0:
                update["power_instant"] = data.watt

        # Only emit event if we have actual changes
        if not update:
            return

        # Filter to only changed values
        changed = {k: v for k, v in update.items() if self._prev.get(k) != v}
        if not changed:
            return

        self._prev.update(changed)

        _LOGGER.debug("Dyaco update: %s", changed)

        event_data = cast(UpdateEventData, changed)
        event = UpdateEvent(event_id="update", event_data=event_data)
        self._cb(event)
