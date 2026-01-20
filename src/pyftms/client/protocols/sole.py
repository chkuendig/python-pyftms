# Copyright 2025, Christian Kündig
# SPDX-License-Identifier: Apache-2.0
#
# Sole/Spirit Treadmill Proprietary Protocol
#
# References:
# - treadonme: https://github.com/swedishborgie/treadonme
# - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift
#   src/devices/solef80treadmill/solef80treadmill.cpp
#
# Tested on: Sole F65 (Model ID 145)
#
# Protocol Summary:
# - Uses proprietary BLE service (not FTMS Control Point)
# - Messages framed with 0x5B start, 0x5D end
# - CRITICAL: Must ACK HeartRateType (0x09) messages or commands are ignored!
# - Speed/Incline control via F1 commands (incremental up/down only)
# - Startup requires full sequence: UserProfile → Program → Target → SetWorkoutMode

import asyncio
import logging
from typing import Callable, Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from ...models import ResultCode
from ..backends.event import UpdateEvent
from .base import MachineProtocol, ProtocolCapabilities

_LOGGER = logging.getLogger(__name__)


class SoleProtocol(MachineProtocol):
    """
    Sole/Spirit treadmill proprietary protocol.
    
    Supports: F63, F65, F80, F85, F89, S77, TT8, ST90, TRX7.5
    
    Key differences from standard FTMS:
    1. No absolute speed/incline targets - only incremental (up/down)
    2. Must ACK incoming messages (especially HeartRateType 0x09)
    3. Full startup sequence required to start from Idle
    """
    
    # Sole Proprietary UUIDs
    SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
    WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
    NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
    
    # Message Types
    MSG_DEVICE_INFO = 0x00
    MSG_SET_WORKOUT_MODE = 0x02
    MSG_WORKOUT_MODE = 0x03
    MSG_WORKOUT_TARGET = 0x04
    MSG_WORKOUT_DATA = 0x06
    MSG_USER_PROFILE = 0x07
    MSG_PROGRAM = 0x08
    MSG_HEART_RATE_TYPE = 0x09
    MSG_F1_COMMAND = 0xF1
    
    # F1 Command Codes
    F1_START = 0x01
    F1_SPEED_UP = 0x02
    F1_SPEED_DOWN = 0x03
    F1_INCLINE_UP = 0x04
    F1_INCLINE_DOWN = 0x05
    F1_STOP = 0x06
    
    # Workout Modes
    MODE_IDLE = 0x01
    MODE_START = 0x02
    MODE_RUNNING = 0x04
    MODE_PAUSE = 0x06
    MODE_DONE = 0x07
    
    # Message types that require ACK
    ACK_MESSAGE_TYPES = {
        0x06,  # WorkoutData
        0x09,  # HeartRateType - CRITICAL!
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15,  # Various
        0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
        0x32,
        0x40,
    }
    
    def __init__(
        self,
        callback: Callable[[Any], None] | None = None,
        model_id: int = 145,  # F65 default
    ) -> None:
        super().__init__(callback)
        
        # Device configuration
        self._model_id = model_id
        self._max_speed = 20.0  # km/h (model-specific)
        self._max_incline = 15.0  # % (model-specific)
        self._is_metric = True
        
        # Current state
        self._mode = self.MODE_IDLE
        self._speed = 0.0
        self._incline = 0.0
        self._elapsed_time = 0
        self._distance = 0.0
        self._calories = 0
        self._heart_rate = 0
        
        # Connection state
        self._connected = False
        self._ack_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
    
    @property
    def capabilities(self) -> ProtocolCapabilities:
        return ProtocolCapabilities(
            # No absolute targets - Sole only supports incremental!
            supports_target_speed=False,
            supports_target_incline=False,
            
            # Incremental control via F1 commands
            supports_speed_up_down=True,
            supports_incline_up_down=True,
            
            # Workout control
            supports_start_stop=True,
            supports_pause_resume=True,
            
            # Ranges (Sole F65 defaults)
            speed_range=(0.8, self._max_speed),  # km/h
            incline_range=(0.0, self._max_incline),  # %
            speed_step=0.1,  # 0.1 km/h per press
            incline_step=1.0,  # 1% per press
        )
    
    @property
    def current_speed(self) -> float:
        """Current speed in km/h."""
        return self._speed
    
    @property
    def current_incline(self) -> float:
        """Current incline in percent."""
        return self._incline
    
    @property
    def current_mode(self) -> int:
        """Current workout mode."""
        return self._mode
    
    @property
    def is_running(self) -> bool:
        """Is the treadmill belt moving?"""
        return self._mode in (self.MODE_START, self.MODE_RUNNING)
    
    async def connect(self, client: BleakClient) -> None:
        """Initialize connection and subscribe to notifications."""
        self._client = client
        
        # Subscribe to Sole notify characteristic
        await client.start_notify(self.NOTIFY_UUID, self._on_notification)
        
        # Send GetDeviceInfo to initiate communication
        await self._send_get_device_info()
        
        self._connected = True
        _LOGGER.info("Sole protocol connected")
    
    async def disconnect(self) -> None:
        """Clean up on disconnect."""
        self._connected = False
        if self._ack_task and not self._ack_task.done():
            self._ack_task.cancel()
        await super().disconnect()
    
    # --- Workout Control ---
    
    async def start(self) -> ResultCode:
        """Start workout."""
        if self._mode == self.MODE_IDLE:
            # Full startup sequence from Idle
            return await self._start_from_idle()
        else:
            # F1 Start during active workout (resume from pause)
            await self._send_f1_command(self.F1_START)
            return ResultCode.SUCCESS
    
    async def stop(self) -> ResultCode:
        """Stop workout (transitions to Pause mode)."""
        await self._send_f1_command(self.F1_STOP)
        return ResultCode.SUCCESS
    
    async def pause(self) -> ResultCode:
        """Pause workout."""
        # Sole uses F1_STOP for pause
        return await self.stop()
    
    async def resume(self) -> ResultCode:
        """Resume workout from pause."""
        return await self.start()
    
    async def reset(self) -> ResultCode:
        """
        Reset to Idle state.
        
        Note: This sends SetWorkoutMode=DONE to transition back to Idle.
        """
        await self._write(bytes([0x5B, 0x02, 0x02, self.MODE_DONE, 0x5D]))
        return ResultCode.SUCCESS
    
    # --- Incremental Control ---
    
    async def speed_up(self) -> ResultCode:
        """Increase speed by one step (~0.1 km/h)."""
        if not self.is_running:
            _LOGGER.warning("Cannot change speed - treadmill not running")
            return ResultCode.OPERATION_FAILED
        await self._send_f1_command(self.F1_SPEED_UP)
        return ResultCode.SUCCESS
    
    async def speed_down(self) -> ResultCode:
        """Decrease speed by one step (~0.1 km/h)."""
        if not self.is_running:
            _LOGGER.warning("Cannot change speed - treadmill not running")
            return ResultCode.OPERATION_FAILED
        await self._send_f1_command(self.F1_SPEED_DOWN)
        return ResultCode.SUCCESS
    
    async def incline_up(self) -> ResultCode:
        """Increase incline by one step (1%)."""
        if not self.is_running:
            _LOGGER.warning("Cannot change incline - treadmill not running")
            return ResultCode.OPERATION_FAILED
        await self._send_f1_command(self.F1_INCLINE_UP)
        return ResultCode.SUCCESS
    
    async def incline_down(self) -> ResultCode:
        """Decrease incline by one step (1%)."""
        if not self.is_running:
            _LOGGER.warning("Cannot change incline - treadmill not running")
            return ResultCode.OPERATION_FAILED
        await self._send_f1_command(self.F1_INCLINE_DOWN)
        return ResultCode.SUCCESS
    
    # --- Internal Protocol Handling ---
    
    def _on_notification(self, char: BleakGATTCharacteristic, data: bytes) -> None:
        """Handle incoming Sole protocol messages."""
        if len(data) < 3:
            return
        
        # Validate framing
        if data[0] != 0x5B or data[-1] != 0x5D:
            _LOGGER.debug(f"Invalid frame: {data.hex()}")
            return
        
        msg_type = data[2]
        payload = data[3:-1] if len(data) > 4 else b""
        
        # Handle specific message types
        if msg_type == self.MSG_DEVICE_INFO:
            self._handle_device_info(data)
        elif msg_type == self.MSG_WORKOUT_MODE:
            self._handle_workout_mode(data)
        elif msg_type == self.MSG_WORKOUT_DATA:
            self._handle_workout_data(data)
        elif msg_type == self.MSG_HEART_RATE_TYPE:
            # CRITICAL: Must ACK these or commands are ignored!
            asyncio.create_task(self._send_ack(msg_type))
        elif msg_type in self.ACK_MESSAGE_TYPES:
            asyncio.create_task(self._send_ack(msg_type))
        
        # Echo WorkoutMode messages back
        if msg_type == self.MSG_WORKOUT_MODE:
            asyncio.create_task(self._write(data))
    
    def _handle_device_info(self, data: bytes) -> None:
        """Parse DeviceInfo response."""
        if len(data) < 10:
            return
        
        # Parse model info
        self._model_id = data[5]
        max_speed_raw = data[6]
        max_incline_raw = data[7]
        units = data[8]
        
        # Convert based on units
        self._is_metric = (units & 0x01) == 0x01
        
        if self._is_metric:
            self._max_speed = max_speed_raw * 0.1  # km/h
        else:
            self._max_speed = max_speed_raw * 0.1 * 1.60934  # mph -> km/h
        
        self._max_incline = max_incline_raw * 0.5  # 0.5% increments
        
        _LOGGER.info(
            f"Sole DeviceInfo: Model={self._model_id}, "
            f"MaxSpeed={self._max_speed:.1f}km/h, MaxIncline={self._max_incline:.1f}%"
        )
    
    def _handle_workout_mode(self, data: bytes) -> None:
        """Parse WorkoutMode message."""
        if len(data) >= 4:
            old_mode = self._mode
            self._mode = data[3]
            
            if old_mode != self._mode:
                _LOGGER.debug(f"Mode changed: {old_mode:#x} -> {self._mode:#x}")
    
    def _handle_workout_data(self, data: bytes) -> None:
        """Parse WorkoutData message and emit update event."""
        if len(data) < 10:
            return
        
        # Parse workout data
        # Format: [5B] [len] [06] [elapsed_lo] [elapsed_hi] [distance_lo] [distance_hi]
        #         [speed*10] [incline*2] [calories_lo] [calories_hi] [heart_rate] ... [5D]
        
        try:
            elapsed = (data[4] << 8) | data[3]
            distance = ((data[6] << 8) | data[5]) / 100.0  # in km
            speed = data[7] / 10.0  # in km/h
            incline = data[8] / 2.0  # in %
            calories = (data[10] << 8) | data[9]
            heart_rate = data[11] if len(data) > 11 else 0
            
            # Update state
            self._elapsed_time = elapsed
            self._distance = distance
            self._speed = speed
            self._incline = incline
            self._calories = calories
            self._heart_rate = heart_rate
            
            # Emit update event for FTMS compatibility layer
            update_data = {
                "speed_instant": speed,
                "inclination": incline,
                "distance_total": int(distance * 1000),  # Convert to meters
                "time_elapsed": elapsed,
                "energy_total": calories,
                "heart_rate": heart_rate,
            }
            self._emit_event(UpdateEvent("update", update_data))
            
            # ACK the WorkoutData
            asyncio.create_task(self._send_ack(self.MSG_WORKOUT_DATA))
            
        except (IndexError, ValueError) as e:
            _LOGGER.warning(f"Failed to parse WorkoutData: {e}")
    
    async def _start_from_idle(self) -> ResultCode:
        """
        Full startup sequence to begin workout from Idle state.
        
        Sequence:
        1. UserProfile (0x07)
        2. Program=Manual (0x08)
        3. WorkoutTarget (0x04)
        4. SetWorkoutMode=START (0x02)
        """
        _LOGGER.info("Starting workout from Idle (full sequence)")
        
        try:
            # 1. UserProfile: Gender=Male(1), Age=30, unused, 0x9B, 0x48
            await self._write(bytes([0x5B, 0x06, 0x07, 0x01, 0x1E, 0x00, 0x9B, 0x48, 0x5D]))
            await asyncio.sleep(0.3)
            
            # 2. Program: Manual (0x10), segment=1
            await self._write(bytes([0x5B, 0x03, 0x08, 0x10, 0x01, 0x5D]))
            await asyncio.sleep(0.3)
            
            # 3. WorkoutTarget: No target (zeros)
            await self._write(bytes([0x5B, 0x05, 0x04, 0x00, 0x00, 0x00, 0x00, 0x5D]))
            await asyncio.sleep(0.3)
            
            # 4. SetWorkoutMode: START (0x02)
            await self._write(bytes([0x5B, 0x02, 0x02, 0x02, 0x5D]))
            
            return ResultCode.SUCCESS
            
        except Exception as e:
            _LOGGER.error(f"Failed to start workout: {e}")
            return ResultCode.OPERATION_FAILED
    
    async def _send_get_device_info(self) -> None:
        """Send GetDeviceInfo command."""
        await self._write(bytes([0x5B, 0x01, 0xF0, 0x5D]))
    
    async def _send_f1_command(self, cmd: int) -> None:
        """Send F1 command (Start/Stop/Speed/Incline control)."""
        await self._write(bytes([0x5B, 0x02, 0xF1, cmd, 0x5D]))
    
    async def _send_ack(self, msg_type: int) -> None:
        """
        Send ACK for message type.
        
        Format: [5B] [04] [00] [msg_type] [4F='O'] [4B='K'] [5D]
        """
        ack = bytes([0x5B, 0x04, 0x00, msg_type, 0x4F, 0x4B, 0x5D])
        await self._write(ack)
    
    async def _write(self, data: bytes) -> None:
        """Write data to Sole characteristic with lock."""
        if not self._client:
            _LOGGER.warning("Cannot write - not connected")
            return
        
        async with self._write_lock:
            try:
                await self._client.write_gatt_char(
                    self.WRITE_UUID, data, response=False
                )
                _LOGGER.debug(f">> {data.hex()}")
            except Exception as e:
                _LOGGER.error(f"Write failed: {e}")
