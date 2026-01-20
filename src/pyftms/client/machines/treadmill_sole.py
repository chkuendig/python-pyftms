# Copyright 2024-2025, Sergey Dudanov & Christian Kündig
# SPDX-License-Identifier: Apache-2.0
#
# Sole/Spirit Treadmill Support
#
# Sole treadmills (F65, F80, F63, TT8) advertise FTMS UUID but use a proprietary
# protocol for control. They don't expose FTMS Feature characteristic and ignore
# standard FTMS Control Point commands.
#
# References:
# - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift
#   src/devices/solef80treadmill/solef80treadmill.cpp
# - treadonme: https://github.com/swedishborgie/treadonme
#   Go library for Sole BLE treadmills
#
# Tested on: Sole F65 (Model ID 145)

from __future__ import annotations

import asyncio
import logging
from enum import IntEnum
from typing import ClassVar

from ...models import RealtimeData, ResultCode, TreadmillData
from ..backends import UpdateEvent
from .. import const as c
from ..client import FitnessMachine
from ..properties import MachineType

_LOGGER = logging.getLogger(__name__)


class SoleWorkoutMode(IntEnum):
    """Sole treadmill workout mode states."""
    IDLE = 0x01      # On start screen, ready
    START = 0x02     # Starting up
    RUNNING = 0x04   # Workout active, belt moving
    PAUSE = 0x06     # Paused
    DONE = 0x07      # Workout finished
    DEMO = 0x80      # Demo/screensaver mode


class SoleErrorCode(IntEnum):
    """Known Sole treadmill error codes."""
    NONE = 0x00
    # Add more as discovered from ErrorCode (0x10) messages
    UNKNOWN = 0xFF


# Known Sole treadmill name prefixes
SOLE_TREADMILL_NAMES = ("F63", "F65", "F80", "F85", "F89", "S77", "TT8", "ST90", "TRX7.5")


def is_sole_treadmill(device_name: str | None) -> bool:
    """Check if device name matches a known Sole treadmill."""
    if not device_name:
        return False
    name_upper = device_name.upper()
    return any(name_upper.startswith(prefix) for prefix in SOLE_TREADMILL_NAMES)


class TreadmillSole(FitnessMachine):
    """
    Sole/Spirit Treadmill.
    
    Subclass of FitnessMachine that handles Sole's proprietary BLE protocol.
    
    Key differences from standard FTMS:
    1. No absolute speed/incline targets - only incremental (up/down buttons)
    2. Must ACK incoming messages (especially HeartRateType 0x09)
    3. Uses proprietary service UUID for control instead of FTMS Control Point
    4. WorkoutData (0x06) provides real-time sensor data
    """

    _machine_type: ClassVar[MachineType] = MachineType.TREADMILL
    _data_model: ClassVar[type[RealtimeData]] = TreadmillData
    _data_uuid: ClassVar[str] = c.TREADMILL_DATA_UUID

    # Sole Proprietary UUIDs
    SOLE_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
    SOLE_WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
    SOLE_NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

    # Sole F1 command codes
    F1_START = 0x01
    F1_SPEED_UP = 0x02
    F1_SPEED_DOWN = 0x03
    F1_INCLINE_UP = 0x04
    F1_INCLINE_DOWN = 0x05
    F1_STOP = 0x06

    # Sole message types that require ACK
    _ACK_MSG_TYPES = {
        0x06,  # WorkoutData - CRITICAL for sensor updates!
        0x09,  # HeartRateType - CRITICAL or commands are ignored!
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15,
        0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
        0x32, 0x40,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sole-specific state tracking
        self._sole_workout_mode: SoleWorkoutMode = SoleWorkoutMode.IDLE
        self._sole_error_code: int = 0

    @property
    def sole_workout_mode(self) -> SoleWorkoutMode:
        """Current Sole workout mode."""
        return self._sole_workout_mode

    @property
    def sole_error_code(self) -> int:
        """Current Sole error code (0 = no error)."""
        return self._sole_error_code

    @property
    def training_status(self) -> str | None:
        """
        Map Sole workout mode to FTMS training status string.
        
        This allows the existing HA sensor to display the treadmill state.
        """
        mode_to_status = {
            SoleWorkoutMode.IDLE: "idle",
            SoleWorkoutMode.START: "warming_up",
            SoleWorkoutMode.RUNNING: "running",
            SoleWorkoutMode.PAUSE: "paused",
            SoleWorkoutMode.DONE: "post_workout",
            SoleWorkoutMode.DEMO: "idle",  # Demo mode shows as idle
        }
        return mode_to_status.get(self._sole_workout_mode, "unknown")

    @property
    def _has_sole_service(self) -> bool:
        """Check if Sole proprietary service is available."""
        try:
            if not self._cli.is_connected:
                return False
            return self._cli.services.get_service(self.SOLE_SERVICE_UUID) is not None
        except AttributeError:
            return False

    @property
    def supported_settings(self) -> tuple[str, ...]:
        """Supported settings - adds Sole incremental controls."""
        settings = list(super().supported_settings)
        
        # Add Sole-specific incremental controls
        if self._has_sole_service:
            settings.extend([c.SPEED_UP, c.SPEED_DOWN, c.INCLINE_UP, c.INCLINE_DOWN])
        
        return tuple(settings)

    async def _connect(self) -> None:
        """Connect and subscribe to Sole notifications."""
        # Temporarily add Sole service UUID to the services filter
        from ..properties.device_info import DIS_UUID
        from bleak import BleakClient
        from bleak_retry_connector import close_stale_connections, establish_connection
        from ..properties import read_device_info, read_features, MachineFeatures, MachineSettings, SettingRange
        from types import MappingProxyType

        if not self._need_connect or self.is_connected:
            return

        await close_stale_connections(self._device)

        _LOGGER.debug("TreadmillSole: Establishing connection...")

        # Include Sole service UUID in services filter
        services_filter = [c.FTMS_UUID, DIS_UUID, self.SOLE_SERVICE_UUID]

        self._cli = await establish_connection(
            client_class=BleakClient,
            device=self._device,
            name=self.name,
            disconnected_callback=self._on_disconnect,
            services=services_filter,
        )

        _LOGGER.debug("TreadmillSole: Connection success.")

        # Read device info
        if not hasattr(self, "_device_info"):
            self._device_info = await read_device_info(self._cli)

        # Try to read FTMS features (may fail for Sole)
        if not hasattr(self, "_m_features"):
            try:
                (
                    self._m_features,
                    self._m_settings,
                    self._settings_ranges,
                ) = await read_features(self._cli, self._machine_type)
            except Exception as e:
                _LOGGER.debug(
                    "TreadmillSole: Feature characteristic not found; proceeding in data-only mode. Error: %s", e
                )
                self._m_features = MachineFeatures(0)
                self._m_settings = MachineSettings(0)
                self._settings_ranges = MappingProxyType({})

        # Subscribe to standard FTMS notifications
        await self._controller.subscribe(self._cli)
        await self._updater.subscribe(self._cli, self._data_uuid)

        # Subscribe to Sole proprietary notifications
        await self._subscribe_sole_notifications()

    async def _subscribe_sole_notifications(self) -> None:
        """Subscribe to Sole proprietary notifications."""
        if not self._has_sole_service:
            _LOGGER.debug("Sole service not found, skipping notification subscription")
            return

        try:
            sole_service = self._cli.services.get_service(self.SOLE_SERVICE_UUID)
            notify_char = sole_service.get_characteristic(self.SOLE_NOTIFY_UUID)
            if notify_char:
                await self._cli.start_notify(notify_char, self._on_sole_notify)
                _LOGGER.info("TreadmillSole: Subscribed to Sole notifications")

                # Send GetDeviceInfo to initiate communication
                await self._write_sole_command(bytes([0x5b, 0x01, 0xf0, 0x5d]), "get_device_info")
            else:
                _LOGGER.warning("Sole notify characteristic not found")
        except Exception as e:
            _LOGGER.error(f"Failed to subscribe to Sole notifications: {e}")

    def _on_sole_notify(self, char, data: bytes) -> None:
        """Handle incoming Sole protocol messages."""
        if len(data) < 3:
            return

        # Validate framing
        if data[0] != 0x5B or data[-1] != 0x5D:
            _LOGGER.debug(f"Invalid Sole frame: {data.hex()}")
            return

        msg_type = data[2]
        _LOGGER.debug(f"Sole notify: type=0x{msg_type:02x}, data={data.hex()}")

        # Handle specific message types
        if msg_type == 0xF0:  # DeviceInfo response
            self._handle_sole_device_info(data)
        elif msg_type == 0x03:  # WorkoutMode
            self._handle_sole_workout_mode(data)
            # Echo WorkoutMode messages back (protocol requirement)
            asyncio.create_task(self._write_sole_command(data, "echo_workout_mode"))
        elif msg_type == 0x06:  # WorkoutData
            self._handle_sole_workout_data(data)
        elif msg_type == 0x10:  # ErrorCode
            self._handle_sole_error_code(data)

        # Send ACK for message types that require it
        if msg_type in self._ACK_MSG_TYPES:
            asyncio.create_task(self._send_sole_ack(msg_type))

    def _handle_sole_device_info(self, data: bytes) -> None:
        """Parse Sole DeviceInfo response (0xF0)."""
        if len(data) < 10:
            return

        model_id = data[3]
        max_speed_raw = data[6]
        min_speed_raw = data[7]
        max_incline_raw = data[8]
        units = data[5]

        is_metric = (units & 0x01) == 0x01

        if is_metric:
            max_speed = max_speed_raw
            min_speed = min_speed_raw
        else:
            max_speed = max_speed_raw * 1.60934
            min_speed = min_speed_raw * 1.60934

        _LOGGER.info(
            f"Sole DeviceInfo: Model={model_id}, Speed={min_speed}-{max_speed}km/h, "
            f"MaxIncline={max_incline_raw}%, Units={'metric' if is_metric else 'imperial'}"
        )

    def _handle_sole_workout_mode(self, data: bytes) -> None:
        """Parse Sole WorkoutMode message (0x03) and update training status."""
        if len(data) >= 4:
            mode_byte = data[3]
            old_mode = self._sole_workout_mode
            
            # Map byte to enum
            try:
                self._sole_workout_mode = SoleWorkoutMode(mode_byte)
            except ValueError:
                _LOGGER.debug(f"Unknown Sole workout mode: 0x{mode_byte:02x}")
                return
            
            mode_names = {
                SoleWorkoutMode.IDLE: "Idle",
                SoleWorkoutMode.START: "Start",
                SoleWorkoutMode.RUNNING: "Running",
                SoleWorkoutMode.PAUSE: "Pause",
                SoleWorkoutMode.DONE: "Done",
                SoleWorkoutMode.DEMO: "Demo",
            }
            _LOGGER.debug(f"Sole WorkoutMode: {mode_names.get(self._sole_workout_mode, f'0x{mode_byte:02x}')}")
            
            # Emit training_status update if mode changed
            if old_mode != self._sole_workout_mode:
                _LOGGER.info(f"Sole mode changed: {mode_names.get(old_mode, '?')} -> {mode_names.get(self._sole_workout_mode, '?')}")
                self._on_event(UpdateEvent("update", {c.TRAINING_STATUS: self.training_status}))

    def _handle_sole_error_code(self, data: bytes) -> None:
        """Parse Sole ErrorCode message (0x10)."""
        if len(data) >= 4:
            error_code = data[3]
            old_error = self._sole_error_code
            self._sole_error_code = error_code
            
            if error_code != 0:
                _LOGGER.warning(f"Sole treadmill error code: 0x{error_code:02x}")
            elif old_error != 0:
                _LOGGER.info("Sole treadmill error cleared")
            
            # Emit error code update (HA can create a sensor for this)
            self._on_event(UpdateEvent("update", {c.SOLE_ERROR_CODE: error_code}))

    def _handle_sole_workout_data(self, data: bytes) -> None:
        """
        Parse Sole WorkoutData (0x06) and emit sensor updates.

        Format (observed from F65):
        [5B] [len] [06] [elapsed_lo] [elapsed_hi] [dist_lo] [dist_hi]
        [speed*10] [incline*2] [cal_lo] [cal_hi] [heart_rate] ... [5D]
        """
        if len(data) < 12:
            _LOGGER.debug(f"WorkoutData too short: {len(data)} bytes")
            return

        try:
            elapsed_time = (data[4] << 8) | data[3]
            distance_raw = ((data[6] << 8) | data[5])
            speed = data[7] / 10.0
            incline = data[8] / 2.0
            calories = (data[10] << 8) | data[9]
            heart_rate = data[11] if len(data) > 11 else 0

            distance = distance_raw / 100.0

            _LOGGER.debug(
                f"Sole WorkoutData: speed={speed}km/h, incline={incline}%, "
                f"elapsed={elapsed_time}s, dist={distance}km, cal={calories}, hr={heart_rate}"
            )

            update_data = {
                c.SPEED_INSTANT: speed,
                c.INCLINATION: incline,
                c.TIME_ELAPSED: elapsed_time,
                c.DISTANCE_TOTAL: int(distance * 1000),
                c.ENERGY_TOTAL: calories,
            }

            if heart_rate > 0:
                update_data[c.HEART_RATE] = heart_rate

            self._on_event(UpdateEvent("update", update_data))

        except (IndexError, ValueError) as e:
            _LOGGER.warning(f"Failed to parse Sole WorkoutData: {e}")

    async def _send_sole_ack(self, msg_type: int) -> None:
        """Send ACK for Sole message type."""
        ack = bytes([0x5B, 0x04, 0x00, msg_type, 0x4F, 0x4B, 0x5D])
        await self._write_sole_command(ack, f"ack_0x{msg_type:02x}")

    async def _write_sole_command(self, cmd: bytes, description: str = "") -> ResultCode:
        """Write a command to the Sole proprietary characteristic."""
        if not self.is_connected:
            if self._need_connect:
                await self._connect()
            else:
                return ResultCode.FAILED

        if not self._has_sole_service:
            _LOGGER.debug(f"Sole service not available for command: {description}")
            return ResultCode.NOT_SUPPORTED

        try:
            sole_service = self._cli.services.get_service(self.SOLE_SERVICE_UUID)
            char = sole_service.get_characteristic(self.SOLE_WRITE_UUID)
            if char is None:
                _LOGGER.warning("Sole write characteristic not found")
                return ResultCode.NOT_SUPPORTED

            _LOGGER.debug(f"Sole >> {description}: {cmd.hex()}")
            await self._cli.write_gatt_char(char, cmd, response=False)
            return ResultCode.SUCCESS
        except Exception as e:
            _LOGGER.error(f"Sole command failed ({description}): {e}")
            return ResultCode.FAILED

    # Override control methods to use Sole protocol

    async def reset(self) -> ResultCode:
        """Reset - uses Sole stop command."""
        if self._has_sole_service:
            return await self._sole_stop()
        return await super().reset()

    async def start_resume(self) -> ResultCode:
        """Start or resume using Sole protocol."""
        if self._has_sole_service:
            return await self._sole_start()
        return await super().start_resume()

    async def stop(self) -> ResultCode:
        """Stop using Sole protocol."""
        if self._has_sole_service:
            return await self._sole_stop()
        return await super().stop()

    async def pause(self) -> ResultCode:
        """Pause using Sole protocol."""
        if self._has_sole_service:
            return await self._sole_stop()
        return await super().pause()

    async def _sole_start(self) -> ResultCode:
        """
        Start/Resume treadmill using Sole proprietary protocol.

        This handles both scenarios:
        - From PAUSE: F1 Start command resumes
        - From IDLE: SetWorkoutMode sequence starts fresh
        """
        _LOGGER.info("TreadmillSole: Starting/Resuming workout...")

        # First try F1 Start (works for resuming from pause)
        for _ in range(3):
            await self._write_sole_command(
                bytes([0x5b, 0x02, 0xf1, self.F1_START, 0x5d]), "f1_start"
            )
            await asyncio.sleep(0.1)

        # Then try SetWorkoutMode = Running (works for starting fresh)
        for _ in range(3):
            await self._write_sole_command(
                bytes([0x5b, 0x02, 0x03, 0x04, 0x5d]), "set_mode_running"
            )
            await asyncio.sleep(0.1)

        _LOGGER.info("TreadmillSole: Start/resume commands sent")
        return ResultCode.SUCCESS

    async def _sole_stop(self) -> ResultCode:
        """Stop/Pause treadmill using Sole proprietary protocol."""
        _LOGGER.info("TreadmillSole: Stopping workout...")
        for _ in range(3):
            await self._write_sole_command(
                bytes([0x5b, 0x02, 0xf1, self.F1_STOP, 0x5d]), "f1_stop"
            )
        return ResultCode.SUCCESS

    # Sole incremental control methods

    async def speed_up(self) -> ResultCode:
        """Increment speed by one step."""
        return await self._write_sole_command(
            bytes([0x5b, 0x02, 0xf1, self.F1_SPEED_UP, 0x5d]), "speed_up"
        )

    async def speed_down(self) -> ResultCode:
        """Decrement speed by one step."""
        return await self._write_sole_command(
            bytes([0x5b, 0x02, 0xf1, self.F1_SPEED_DOWN, 0x5d]), "speed_down"
        )

    async def incline_up(self) -> ResultCode:
        """Increment incline by one step."""
        return await self._write_sole_command(
            bytes([0x5b, 0x02, 0xf1, self.F1_INCLINE_UP, 0x5d]), "incline_up"
        )

    async def incline_down(self) -> ResultCode:
        """Decrement incline by one step."""
        return await self._write_sole_command(
            bytes([0x5b, 0x02, 0xf1, self.F1_INCLINE_DOWN, 0x5d]), "incline_down"
        )
