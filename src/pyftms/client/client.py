# Copyright 2024-2025, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0
#
# PATCHED: Added data-only fallback for devices without FTMS Feature characteristic
#
# References:
# - GitHub PR: https://github.com/dudanov/python-pyftms/pull/49
#   "Support FTMS devices without service_data (data-only fallback + detect type after connect)"
#   by @mhamzahkhan - addresses devices that advertise FTMS UUID but omit service_data
#
# - Sole treadmills (F65, F80, F63, TT8) don't expose FTMS Feature characteristic
#   but do send Treadmill Data (0x2ACD) notifications
#
# - Protocol details from:
#   - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift
#     src/devices/solef80treadmill/solef80treadmill.cpp
#   - treadonme: https://github.com/swedishborgie/treadonme
#     Go library for Sole BLE treadmills

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from functools import cached_property
from types import MappingProxyType
from typing import Any, Callable, ClassVar

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import close_stale_connections, establish_connection

from ..models import (
    ControlCode,
    ControlModel,
    IndoorBikeSimulationParameters,
    RealtimeData,
    ResultCode,
    SpinDownControlCode,
    StopPauseCode,
)
from . import const as c
from .backends import DataUpdater, FtmsCallback, MachineController, UpdateEvent
from .manager import PropertiesManager
from .properties import (
    DeviceInfo,
    MachineFeatures,
    MachineSettings,
    MachineType,
    SettingRange,
    read_device_info,
    read_features,
)
from .properties.device_info import DIS_UUID

_LOGGER = logging.getLogger(__name__)

type DisconnectCallback = Callable[[FitnessMachine], None]


class FitnessMachine(ABC, PropertiesManager):
    """
    Base FTMS client.

    Supports `async with ...` context manager.
    """

    _machine_type: ClassVar[MachineType]
    """Machine type."""

    _data_model: ClassVar[type[RealtimeData]]
    """Model of real-time training data."""

    _data_uuid: ClassVar[str]
    """Notify UUID of real-time training data."""

    _cli: BleakClient

    _updater: DataUpdater

    _device: BLEDevice
    _need_connect: bool

    # Static device info

    _device_info: DeviceInfo
    _m_features: MachineFeatures
    _m_settings: MachineSettings
    _settings_ranges: MappingProxyType[str, SettingRange]

    def __init__(
        self,
        ble_device: BLEDevice,
        adv_data: AdvertisementData | None = None,
        *,
        timeout: float = 2.0,
        on_ftms_event: FtmsCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
        kwargs: Any = None,
    ) -> None:
        super().__init__(on_ftms_event)

        self._need_connect = False
        self._timeout = timeout
        self._disconnect_cb = on_disconnect

        self.set_ble_device_and_advertisement_data(ble_device, adv_data)

        # Updaters
        self._updater = DataUpdater(self._data_model, self._on_event)
        self._controller = MachineController(self._on_event)

        # Auto-detect FTMS variant by device name
        self._ftms_variant = c.FTMS_VARIANT_GENERIC
        device_name = (ble_device.name or "").upper()
        for prefix in c.SOLE_TREADMILL_NAMES:
            if device_name.startswith(prefix):
                self._ftms_variant = c.FTMS_VARIANT_SOLE
                _LOGGER.info(f"Auto-detected Sole treadmill: {ble_device.name}, using variant '{c.FTMS_VARIANT_SOLE}'")
                break

    @classmethod
    def _get_supported_properties(
        cls, features: MachineFeatures = MachineFeatures(~0)
    ) -> list[str]:
        return cls._data_model._get_features(features)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    # BLE SPECIFIC PROPERTIES

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, adv_data: AdvertisementData | None
    ):
        self._device = ble_device

        if adv_data:
            self._properties["rssi"] = adv_data.rssi

            if self._cb:
                self._cb(UpdateEvent("update", {"rssi": adv_data.rssi}))

    @property
    def need_connect(self) -> bool:
        """Connection state latch. `True` if connection is needed."""
        return self._need_connect

    @need_connect.setter
    def need_connect(self, value: bool) -> None:
        """Connection state latch. `True` if connection is needed."""
        self._need_connect = value

    @property
    def rssi(self) -> int | None:
        """RSSI."""
        return self.get_property("rssi")

    @property
    def name(self) -> str:
        """Device name or BLE address"""

        return self._device.name or self._device.address

    def set_disconnect_callback(self, cb: DisconnectCallback):
        """Set disconnect callback."""
        self._disconnect_cb = cb

    async def connect(self) -> None:
        """
        Opens a connection to the device. Reads necessary static information:
        * Device Information (manufacturer, model, serial number, hardware and software versions);
        * Supported features;
        * Supported settings;
        * Ranges of parameters settings.
        """

        self._need_connect = True

        await self._connect()

    async def disconnect(self) -> None:
        """Disconnects from device."""

        self._need_connect = False

        if self.is_connected:
            await self._cli.disconnect()

    @property
    def address(self) -> str:
        """Bluetooth address."""

        return self._device.address

    @property
    def is_connected(self) -> bool:
        """Current connection status."""
        try:
            return self._cli.is_connected
        except AttributeError:
            return False

    # COMMON BASE PROPERTIES

    @property
    def device_info(self) -> DeviceInfo:
        """Device Information."""
        return self._device_info

    @property
    def machine_type(self) -> MachineType:
        """Machine type."""
        return self._machine_type

    @cached_property
    def supported_properties(self) -> tuple[str, ...]:
        """
        Properties that supported by this machine.
        Based on **Machine Features** report.

        *May contain both meaningless properties and may not contain
        some properties that are supported by the machine.*
        
        For Sole treadmills (and other devices that do not properly report
        their features), returns all available properties for the machine type.
        """
        # For Sole variant, features are not properly advertised, so return all available
        if self.ftms_variant == c.FTMS_VARIANT_SOLE:
            return self.available_properties
        
        x = self._get_supported_properties(self._m_features)
        if self.training_status is not None:
            x.append(c.TRAINING_STATUS)
        return tuple(x)

    @cached_property
    def available_properties(self) -> tuple[str, ...]:
        """All properties that *MAY BE* supported by this machine type."""
        x = self._get_supported_properties()
        x.append(c.TRAINING_STATUS)
        return tuple(x)

    @property
    def supported_settings(self) -> tuple[str, ...]:
        """Supported settings."""
        # PATCH: Handle case where _m_settings was never initialized (data-only mode)
        if not hasattr(self, "_m_settings"):
            settings = []
        else:
            settings = list(ControlModel._get_features(self._m_settings))
        
        # Add variant-specific controls only if Sole proprietary service is present
        if self.ftms_variant == c.FTMS_VARIANT_SOLE and self._has_sole_service:
            settings.extend([c.SPEED_UP, c.SPEED_DOWN, c.INCLINE_UP, c.INCLINE_DOWN])
        
        return tuple(settings)

    @property
    def supported_ranges(self) -> MappingProxyType[str, SettingRange]:
        """Ranges of supported settings."""
        # PATCH: Handle case where _settings_ranges was never initialized (data-only mode)
        if not hasattr(self, "_settings_ranges"):
            return MappingProxyType({})
        return self._settings_ranges

    @property
    def _has_sole_service(self) -> bool:
        """Check if Sole proprietary service is available."""
        try:
            if not self._cli.is_connected:
                return False
            return self._cli.services.get_service(c.SOLE_SERVICE_UUID) is not None
        except AttributeError:
            return False

    def _on_disconnect(self, cli: BleakClient) -> None:
        _LOGGER.debug("Client disconnected. Reset updaters states.")

        try:
            del self._cli
        except AttributeError:
            pass  # Already deleted or never set
        self._updater.reset()
        self._controller.reset()

        if self._disconnect_cb:
            self._disconnect_cb(self)

    async def _connect(self) -> None:
        if not self._need_connect or self.is_connected:
            return

        await close_stale_connections(self._device)

        _LOGGER.debug("Initialization. Trying to establish connection.")

        # Include Sole service UUID if this is a Sole device
        services_filter = [c.FTMS_UUID, DIS_UUID]
        if self.ftms_variant == c.FTMS_VARIANT_SOLE:
            services_filter.append(c.SOLE_SERVICE_UUID)

        self._cli = await establish_connection(
            client_class=BleakClient,
            device=self._device,
            name=self.name,
            disconnected_callback=self._on_disconnect,
            services=services_filter,
        )

        _LOGGER.debug("Connection success.")

        # Reading necessary static fitness machine information

        if not hasattr(self, "_device_info"):
            self._device_info = await read_device_info(self._cli)

        if not hasattr(self, "_features"):
            # PATCH: Wrap in try-except for data-only fallback
            # Some devices expose real-time data but omit FTMS Feature characteristic
            try:
                (
                    self._m_features,
                    self._m_settings,
                    self._settings_ranges,
                ) = await read_features(self._cli, self._machine_type)
            except Exception as e:
                _LOGGER.debug(
                    "Feature characteristic not found or failed to read; proceeding in data-only mode. Error: %s", e
                )
                self._m_features = MachineFeatures(0)
                self._m_settings = MachineSettings(0)
                self._settings_ranges = MappingProxyType({})

        await self._controller.subscribe(self._cli)
        await self._updater.subscribe(self._cli, self._data_uuid)

        # Subscribe to Sole proprietary notifications if available
        if self.ftms_variant == c.FTMS_VARIANT_SOLE:
            await self._subscribe_sole_notifications()

    # SOLE NOTIFICATION HANDLING
    
    # Sole message types that require ACK
    _SOLE_ACK_MSG_TYPES = {
        0x06,  # WorkoutData - CRITICAL for sensor updates!
        0x09,  # HeartRateType - CRITICAL or commands are ignored!
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15,
        0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
        0x32, 0x40,
    }

    async def _subscribe_sole_notifications(self) -> None:
        """Subscribe to Sole proprietary notifications."""
        if not self._has_sole_service:
            _LOGGER.debug("Sole service not found, skipping notification subscription")
            return
        
        try:
            sole_service = self._cli.services.get_service(c.SOLE_SERVICE_UUID)
            notify_char = sole_service.get_characteristic(c.SOLE_NOTIFY_UUID)
            if notify_char:
                await self._cli.start_notify(notify_char, self._on_sole_notify)
                _LOGGER.info("Subscribed to Sole notifications")
                
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
        
        # Send ACK for message types that require it
        if msg_type in self._SOLE_ACK_MSG_TYPES:
            asyncio.create_task(self._send_sole_ack(msg_type))

    def _handle_sole_device_info(self, data: bytes) -> None:
        """Parse Sole DeviceInfo response (0xF0)."""
        if len(data) < 10:
            return
        
        # Format: [5B] [len] [F0] [model_id] [version] [units] [max_speed] [min_speed] [max_incline] [user_seg] [5D]
        model_id = data[3]
        max_speed_raw = data[6]
        min_speed_raw = data[7]
        max_incline_raw = data[8]
        units = data[5]
        
        is_metric = (units & 0x01) == 0x01
        
        if is_metric:
            max_speed = max_speed_raw  # km/h
            min_speed = min_speed_raw  # km/h
        else:
            max_speed = max_speed_raw * 1.60934  # mph -> km/h
            min_speed = min_speed_raw * 1.60934
        
        _LOGGER.info(
            f"Sole DeviceInfo: Model={model_id}, Speed={min_speed}-{max_speed}km/h, "
            f"MaxIncline={max_incline_raw}%, Units={'metric' if is_metric else 'imperial'}"
        )

    def _handle_sole_workout_mode(self, data: bytes) -> None:
        """Parse Sole WorkoutMode message (0x03)."""
        if len(data) >= 4:
            mode = data[3]
            mode_names = {0x01: "Idle", 0x02: "Start", 0x04: "Running", 0x06: "Pause", 0x07: "Done"}
            _LOGGER.debug(f"Sole WorkoutMode: {mode_names.get(mode, f'0x{mode:02x}')}")

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
            # Parse fields (all little-endian)
            elapsed_time = (data[4] << 8) | data[3]  # seconds
            distance_raw = ((data[6] << 8) | data[5])  # in 0.01 km units
            speed = data[7] / 10.0  # km/h (stored as speed * 10)
            incline = data[8] / 2.0  # % (stored as incline * 2)
            calories = (data[10] << 8) | data[9]  # kcal
            heart_rate = data[11] if len(data) > 11 else 0  # bpm
            
            distance = distance_raw / 100.0  # Convert to km
            
            _LOGGER.debug(
                f"Sole WorkoutData: speed={speed}km/h, incline={incline}%, "
                f"elapsed={elapsed_time}s, dist={distance}km, cal={calories}, hr={heart_rate}"
            )
            
            # Emit update event with all sensor data
            update_data = {
                c.SPEED_INSTANT: speed,
                c.INCLINATION: incline,
                c.TIME_ELAPSED: elapsed_time,
                c.DISTANCE_TOTAL: int(distance * 1000),  # Convert to meters
                c.ENERGY_TOTAL: calories,
            }
            
            # Only include heart rate if non-zero
            if heart_rate > 0:
                update_data[c.HEART_RATE] = heart_rate
            
            # Emit the update event
            self._on_event(UpdateEvent("update", update_data))
            
        except (IndexError, ValueError) as e:
            _LOGGER.warning(f"Failed to parse Sole WorkoutData: {e}")

    async def _send_sole_ack(self, msg_type: int) -> None:
        """
        Send ACK for Sole message type.
        
        Format: [5B] [04] [00] [msg_type] [4F='O'] [4B='K'] [5D]
        """
        ack = bytes([0x5B, 0x04, 0x00, msg_type, 0x4F, 0x4B, 0x5D])
        await self._write_sole_command(ack, f"ack_0x{msg_type:02x}")

    # COMMANDS

    async def _write_command(self, code: ControlCode | None = None, *args, **kwargs):
        if self._need_connect:
            await self._connect()
            return await self._controller.write_command(
                self._cli, code, timeout=self._timeout, **kwargs
            )

        return ResultCode.FAILED

    async def reset(self) -> ResultCode:
        """Initiates the procedure to reset the controllable settings of a fitness machine."""
        # Sole devices use proprietary protocol
        if self._has_sole_service:
            return await self.sole_stop()  # Reset via stop for Sole
        return await self._write_command(ControlCode.RESET)

    async def start_resume(self) -> ResultCode:
        """Initiate the procedure to start or resume a training session."""
        # Sole devices use proprietary protocol
        if self._has_sole_service:
            return await self.sole_start()
        return await self._write_command(ControlCode.START_RESUME)

    async def stop(self) -> ResultCode:
        """Initiate the procedure to stop a training session."""
        # Sole devices use proprietary protocol
        if self._has_sole_service:
            return await self.sole_stop()
        return await self._write_command(stop_pause=StopPauseCode.STOP)

    async def pause(self) -> ResultCode:
        """Initiate the procedure to pause a training session."""
        # Sole devices use proprietary protocol (stop == pause)
        if self._has_sole_service:
            return await self.sole_stop()
        return await self._write_command(stop_pause=StopPauseCode.PAUSE)

    async def set_setting(self, setting_id: str, *args: Any) -> ResultCode:
        """
        Generic method of settings by ID.

        **Methods for setting specific parameters.**
        """

        if setting_id not in self.supported_settings:
            return ResultCode.NOT_SUPPORTED

        if not args:
            raise ValueError("No data to pass.")

        if len(args) == 1:
            args = args[0]

        return await self._write_command(code=None, **{setting_id: args})

    async def set_target_speed(self, value: float) -> ResultCode:
        """
        Sets target speed.

        Units: `km/h`.
        """
        return await self.set_setting(c.TARGET_SPEED, value)

    async def set_target_inclination(self, value: float) -> ResultCode:
        """
        Sets target inclination.

        Units: `%`.
        """
        return await self.set_setting(c.TARGET_INCLINATION, value)

    async def set_target_resistance(self, value: float) -> ResultCode:
        """
        Sets target resistance level.

        Units: `unitless`.
        """
        return await self.set_setting(c.TARGET_RESISTANCE, value)

    async def set_target_power(self, value: int) -> ResultCode:
        """
        Sets target power.

        Units: `Watt`.
        """
        return await self.set_setting(c.TARGET_POWER, value)

    async def set_target_heart_rate(self, value: int) -> ResultCode:
        """
        Sets target heart rate.

        Units: `bpm`.
        """
        return await self.set_setting(c.TARGET_HEART_RATE, value)

    async def set_target_expended_energy(self, value: int) -> ResultCode:
        """
        Sets targeted expended energy.

        Units: `Calorie`.
        """
        return await self.set_setting(c.TARGET_EXPENDED_ENERGY, value)

    async def set_target_steps(self, value: int) -> ResultCode:
        """
        Sets targeted number of steps.

        Units: `step`.
        """
        return await self.set_setting(c.TARGET_STEPS, value)

    async def set_target_strides(self, value: int) -> ResultCode:
        """
        Sets targeted number of strides.

        Units: `stride`.
        """
        return await self.set_setting(c.TARGET_STRIDES, value)

    async def set_target_distance(self, value: int) -> ResultCode:
        """
        Sets targeted distance.

        Units: `metre`.
        """
        return await self.set_setting(c.TARGET_DISTANCE, value)

    async def set_target_time(self, value: int) -> ResultCode:
        """
        Sets targeted training time.

        Units: `second`.
        """
        return await self.set_setting(c.TARGET_TIME, value)

    async def set_target_time_two_zones(self, fat_burn: int, fitness: int) -> ResultCode:
        """
        Sets targeted time in two Heart Rate Zones.

        Units: `second`.
        """
        return await self.set_setting(c.TARGET_TIME_TWO_HR_ZONES, fat_burn, fitness)

    async def set_target_time_three_zones(
        self, light: int, moderate: int, hard: int
    ) -> ResultCode:
        """
        Sets targeted time in three Heart Rate Zones.

        Units: `second`.
        """
        return await self.set_setting(c.TARGET_TIME_THREE_HR_ZONES, light, moderate, hard)

    async def set_target_time_five_zones(
        self, very_light: int, light: int, moderate: int, hard: int, maximum: int
    ) -> ResultCode:
        """
        Sets targeted time in five Heart Rate Zones.

        Units: `second`.
        """
        return await self.set_setting(
            c.TARGET_TIME_FIVE_HR_ZONES, very_light, light, moderate, hard, maximum
        )

    async def set_wheel_circumference(self, value: float) -> ResultCode:
        """
        Sets wheel circumference.

        Units: `mm`.
        """
        return await self.set_setting(c.WHEEL_CIRCUMFERENCE, value)

    async def set_indoor_bike_simulation(
        self,
        wind: float = 0.0,
        grade: float = 0.0,
        crr: float = 0.0,
        cw: float = 0.0,
    ) -> ResultCode:
        """
        Sets simulation parameters for `Indoor Bike`.

        * `wind` - current wind speed, units: `m/s`.
        * `grade` - current road grade, units: `%`.
        * `crr` - coefficient of rolling resistance.
        * `cw` - wind resistance coefficient, units: `kg/m`.
        """
        return await self.set_setting(
            c.INDOOR_BIKE_SIMULATION,
            IndoorBikeSimulationParameters(wind, grade, crr, cw),
        )

    async def spin_down_start(self) -> ResultCode:
        """Initiate the spin down procedure."""
        return await self._write_command(spin_down=SpinDownControlCode.START)

    async def spin_down_ignore(self) -> ResultCode:
        """Indicates the fitness machine to ignore the current spin down procedure."""
        return await self._write_command(spin_down=SpinDownControlCode.IGNORE)

    # SOLE TREADMILL PROPRIETARY COMMANDS
    # These methods send commands via the Sole proprietary BLE service
    # instead of the standard FTMS Control Point.
    
    _ftms_variant: str = c.FTMS_VARIANT_GENERIC
    """FTMS protocol variant for manufacturer-specific handling."""
    
    def set_ftms_variant(self, variant: str) -> None:
        """
        Set the FTMS protocol variant for manufacturer-specific handling.
        
        Supported variants:
        - "generic": Standard FTMS protocol (default)
        - "sole": Sole/Spirit treadmills with proprietary incremental controls
        """
        self._ftms_variant = variant
        _LOGGER.debug(f"FTMS variant set to '{variant}'")
    
    @property
    def ftms_variant(self) -> str:
        """Current FTMS protocol variant."""
        return getattr(self, '_ftms_variant', c.FTMS_VARIANT_GENERIC)
    
    @property
    def sole_mode(self) -> bool:
        """Whether Sole proprietary protocol is enabled. (Deprecated: use ftms_variant)"""
        return self.ftms_variant == c.FTMS_VARIANT_SOLE
    
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
            sole_service = self._cli.services.get_service(c.SOLE_SERVICE_UUID)
            char = sole_service.get_characteristic(c.SOLE_WRITE_UUID)
            if char is None:
                _LOGGER.warning("Sole write characteristic not found")
                return ResultCode.NOT_SUPPORTED
            
            _LOGGER.debug(f"Sole >> {description}: {cmd.hex()}")
            await self._cli.write_gatt_char(char, cmd, response=False)
            return ResultCode.SUCCESS
        except Exception as e:
            _LOGGER.error(f"Sole command failed ({description}): {e}")
            return ResultCode.FAILED
    
    async def sole_start(self) -> ResultCode:
        """
        Start/Resume treadmill using Sole proprietary protocol.
        
        This handles both scenarios:
        - From PAUSE: F1 Start command resumes
        - From IDLE: SetWorkoutMode sequence starts fresh
        """
        _LOGGER.info("Starting/Resuming Sole workout...")
        
        # First try F1 Start (works for resuming from pause)
        for _ in range(3):
            await self._write_sole_command(c.SOLE_CMD_START, "f1_start")
            await asyncio.sleep(0.1)
        
        # Then try SetWorkoutMode = Running (works for starting fresh)
        # qdomyos sends this 3 times
        for _ in range(3):
            await self._write_sole_command(c.SOLE_CMD_SET_MODE_RUNNING, "set_mode_running")
            await asyncio.sleep(0.1)
        
        _LOGGER.info("Sole start/resume commands sent")
        return ResultCode.SUCCESS
    
    async def sole_stop(self) -> ResultCode:
        """Stop/Pause treadmill using Sole proprietary protocol."""
        _LOGGER.info("Stopping Sole workout...")
        # Send F1 Stop (pause)
        for _ in range(3):
            await self._write_sole_command(c.SOLE_CMD_STOP, "f1_stop")
        return ResultCode.SUCCESS
    
    async def speed_up(self) -> ResultCode:
        """Increment speed by one step (Sole proprietary)."""
        return await self._write_sole_command(c.SOLE_CMD_SPEED_UP, "speed_up")
    
    async def speed_down(self) -> ResultCode:
        """Decrement speed by one step (Sole proprietary)."""
        return await self._write_sole_command(c.SOLE_CMD_SPEED_DOWN, "speed_down")
    
    async def incline_up(self) -> ResultCode:
        """Increment incline by one step (Sole proprietary)."""
        return await self._write_sole_command(c.SOLE_CMD_INCLINE_UP, "incline_up")
    
    async def incline_down(self) -> ResultCode:
        """Decrement incline by one step (Sole proprietary)."""
        return await self._write_sole_command(c.SOLE_CMD_INCLINE_DOWN, "incline_down")
