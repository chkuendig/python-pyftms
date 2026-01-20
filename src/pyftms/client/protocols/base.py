# Copyright 2025, Christian Kündig
# SPDX-License-Identifier: Apache-2.0
#
# Base protocol interface for custom fitness machine protocols

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Any

from bleak import BleakClient

from ...models import ResultCode


@dataclass
class ProtocolCapabilities:
    """Describes what a protocol backend supports."""
    
    # Target setting support (absolute values)
    supports_target_speed: bool = False
    supports_target_incline: bool = False
    supports_target_power: bool = False
    supports_target_resistance: bool = False
    supports_target_heart_rate: bool = False
    
    # Incremental control support (up/down buttons)
    supports_speed_up_down: bool = False
    supports_incline_up_down: bool = False
    supports_resistance_up_down: bool = False
    
    # Workout control
    supports_start_stop: bool = True
    supports_pause_resume: bool = False
    
    # Value ranges (if known)
    speed_range: tuple[float, float] | None = None  # (min, max) km/h
    incline_range: tuple[float, float] | None = None  # (min, max) %
    speed_step: float = 0.1  # km/h per button press
    incline_step: float = 1.0  # % per button press


class MachineProtocol(ABC):
    """
    Abstract base class for machine control protocols.
    
    This allows supporting both standard FTMS (via FTMS Control Point)
    and custom protocols (Sole, Horizon, etc.) with the same interface.
    """
    
    def __init__(self, callback: Callable[[Any], None] | None = None) -> None:
        self._callback = callback
        self._client: BleakClient | None = None
    
    @property
    @abstractmethod
    def capabilities(self) -> ProtocolCapabilities:
        """Return protocol capabilities."""
        pass
    
    @abstractmethod
    async def connect(self, client: BleakClient) -> None:
        """
        Initialize connection and subscribe to notifications.
        
        Called after BLE connection is established.
        """
        pass
    
    async def disconnect(self) -> None:
        """Clean up on disconnect."""
        self._client = None
    
    # --- Workout Control ---
    
    @abstractmethod
    async def start(self) -> ResultCode:
        """Start workout."""
        pass
    
    @abstractmethod
    async def stop(self) -> ResultCode:
        """Stop workout."""
        pass
    
    async def pause(self) -> ResultCode:
        """Pause workout (if supported)."""
        return ResultCode.NOT_SUPPORTED
    
    async def resume(self) -> ResultCode:
        """Resume workout (if supported)."""
        return ResultCode.NOT_SUPPORTED
    
    async def reset(self) -> ResultCode:
        """Reset machine state."""
        return ResultCode.NOT_SUPPORTED
    
    # --- Target Setting (Absolute Values) ---
    
    async def set_target_speed(self, speed_kmh: float) -> ResultCode:
        """Set target speed in km/h."""
        return ResultCode.NOT_SUPPORTED
    
    async def set_target_incline(self, incline_percent: float) -> ResultCode:
        """Set target incline in percent."""
        return ResultCode.NOT_SUPPORTED
    
    async def set_target_power(self, power_watts: int) -> ResultCode:
        """Set target power in watts."""
        return ResultCode.NOT_SUPPORTED
    
    async def set_target_resistance(self, resistance: int) -> ResultCode:
        """Set target resistance level."""
        return ResultCode.NOT_SUPPORTED
    
    async def set_target_heart_rate(self, heart_rate: int) -> ResultCode:
        """Set target heart rate in bpm."""
        return ResultCode.NOT_SUPPORTED
    
    # --- Incremental Control (Button-style) ---
    
    async def speed_up(self) -> ResultCode:
        """Increase speed by one step."""
        return ResultCode.NOT_SUPPORTED
    
    async def speed_down(self) -> ResultCode:
        """Decrease speed by one step."""
        return ResultCode.NOT_SUPPORTED
    
    async def incline_up(self) -> ResultCode:
        """Increase incline by one step."""
        return ResultCode.NOT_SUPPORTED
    
    async def incline_down(self) -> ResultCode:
        """Decrease incline by one step."""
        return ResultCode.NOT_SUPPORTED
    
    async def resistance_up(self) -> ResultCode:
        """Increase resistance by one step."""
        return ResultCode.NOT_SUPPORTED
    
    async def resistance_down(self) -> ResultCode:
        """Decrease resistance by one step."""
        return ResultCode.NOT_SUPPORTED
    
    # --- Helper for subclasses ---
    
    def _emit_event(self, event: Any) -> None:
        """Emit event to callback if registered."""
        if self._callback:
            self._callback(event)
