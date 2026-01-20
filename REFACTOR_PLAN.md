# pyftms Refactor Plan: Adding Custom Protocol Support

## Current Architecture

```
pyftms/
├── client/
│   ├── client.py          # FitnessMachine base class
│   ├── machines/          # Machine type implementations
│   │   ├── treadmill.py   # Treadmill (standard FTMS)
│   │   ├── indoor_bike.py
│   │   └── ...
│   ├── backends/          # Protocol handlers
│   │   ├── controller.py  # FTMS Control Point writes
│   │   └── updater.py     # FTMS Data parsing
│   └── properties/        # Feature/Settings reading
└── models/                # Data models
```

## Problem

Sole treadmills (F65, F80, F63, etc.) advertise FTMS UUID 0x1826 but:
1. **Don't expose FTMS Features (0x2ACC)** - We worked around this
2. **Don't support FTMS Control Point (0x2AD9)** - Can't use standard speed/incline commands
3. **Use proprietary protocol** - Sole Service UUID with custom framed messages

## How qdomyos-zwift Handles This

1. **Device Detection**: Giant switch based on device name/services
2. **Per-device Classes**: `solef80treadmill`, `ftmstreadmill`, etc.
3. **Common API**: All expose `forceSpeed()`, `forceIncline()` - different implementations
4. **Virtual Device**: Re-exposes as standard FTMS to apps

## Proposed pyftms Architecture

### Option A: Protocol Backends (Recommended)

Add protocol-specific backends that implement a common interface:

```
pyftms/
├── client/
│   ├── protocols/                    # NEW: Protocol implementations
│   │   ├── __init__.py
│   │   ├── base.py                   # Protocol interface
│   │   ├── ftms.py                   # Standard FTMS
│   │   └── sole.py                   # Sole proprietary
│   ├── machines/
│   │   ├── treadmill.py              # Generic Treadmill
│   │   └── sole_treadmill.py         # NEW: Sole-specific (optional)
│   └── factory.py                    # NEW: Device detection
```

### Protocol Interface (`protocols/base.py`)

```python
from abc import ABC, abstractmethod
from typing import Protocol

class MachineProtocol(ABC):
    """Protocol interface for machine control."""
    
    @abstractmethod
    async def connect(self, client: BleakClient) -> None:
        """Subscribe to notifications and initialize."""
        pass
    
    @abstractmethod
    async def start(self) -> ResultCode:
        """Start workout."""
        pass
    
    @abstractmethod
    async def stop(self) -> ResultCode:
        """Stop workout."""
        pass
    
    @abstractmethod
    async def set_speed(self, speed_kmh: float) -> ResultCode:
        """Set target speed."""
        pass
    
    @abstractmethod
    async def set_incline(self, incline_percent: float) -> ResultCode:
        """Set target incline."""
        pass
    
    # Incremental control (for devices that don't support absolute targets)
    async def speed_up(self) -> ResultCode:
        """Increase speed by one step."""
        raise NotImplementedError("Device doesn't support incremental control")
    
    async def speed_down(self) -> ResultCode:
        """Decrease speed by one step."""
        raise NotImplementedError("Device doesn't support incremental control")
    
    async def incline_up(self) -> ResultCode:
        """Increase incline by one step."""
        raise NotImplementedError("Device doesn't support incremental control")
    
    async def incline_down(self) -> ResultCode:
        """Decrease incline by one step."""
        raise NotImplementedError("Device doesn't support incremental control")
```

### Sole Protocol Implementation (`protocols/sole.py`)

```python
class SoleProtocol(MachineProtocol):
    """Sole/Spirit proprietary treadmill protocol."""
    
    SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
    WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
    NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
    
    def __init__(self, callback: FtmsCallback) -> None:
        self._callback = callback
        self._current_speed = 0.0
        self._current_incline = 0.0
        self._mode = 0x01  # Idle
    
    async def connect(self, client: BleakClient) -> None:
        """Initialize connection and start ACK loop."""
        self._client = client
        
        # Subscribe to Sole notify characteristic
        await client.start_notify(self.NOTIFY_UUID, self._on_notification)
        
        # Send GetDeviceInfo
        await self._write(bytes([0x5B, 0x01, 0xF0, 0x5D]))
    
    def _on_notification(self, char, data: bytes) -> None:
        """Handle Sole protocol messages."""
        if len(data) < 3 or data[0] != 0x5B or data[-1] != 0x5D:
            return
        
        msg_type = data[2]
        
        # ACK HeartRateType (0x09) - CRITICAL!
        if msg_type == 0x09:
            asyncio.create_task(self._send_ack(0x09))
        
        # WorkoutData (0x06)
        elif msg_type == 0x06 and len(data) >= 10:
            self._parse_workout_data(data)
        
        # WorkoutMode (0x03) - Echo back
        elif msg_type == 0x03:
            asyncio.create_task(self._write(data))
    
    async def start(self) -> ResultCode:
        """Start workout using full startup sequence."""
        if self._mode == 0x01:  # From Idle
            # UserProfile
            await self._write(bytes([0x5B, 0x06, 0x07, 0x01, 0x1E, 0x00, 0x9B, 0x48, 0x5D]))
            await asyncio.sleep(0.3)
            
            # Program=Manual
            await self._write(bytes([0x5B, 0x03, 0x08, 0x10, 0x01, 0x5D]))
            await asyncio.sleep(0.3)
            
            # WorkoutTarget
            await self._write(bytes([0x5B, 0x05, 0x04, 0x00, 0x00, 0x00, 0x00, 0x5D]))
            await asyncio.sleep(0.3)
            
            # SetWorkoutMode=START
            await self._write(bytes([0x5B, 0x02, 0x02, 0x02, 0x5D]))
        else:
            # F1 Start during workout
            await self._write(bytes([0x5B, 0x02, 0xF1, 0x01, 0x5D]))
        
        return ResultCode.SUCCESS
    
    async def stop(self) -> ResultCode:
        """Stop workout."""
        await self._write(bytes([0x5B, 0x02, 0xF1, 0x06, 0x5D]))
        return ResultCode.SUCCESS
    
    async def set_speed(self, speed_kmh: float) -> ResultCode:
        """Sole doesn't support absolute speed - use incremental."""
        raise NotImplementedError("Use speed_up/speed_down")
    
    async def speed_up(self) -> ResultCode:
        await self._write(bytes([0x5B, 0x02, 0xF1, 0x02, 0x5D]))
        return ResultCode.SUCCESS
    
    async def speed_down(self) -> ResultCode:
        await self._write(bytes([0x5B, 0x02, 0xF1, 0x03, 0x5D]))
        return ResultCode.SUCCESS
    
    async def incline_up(self) -> ResultCode:
        await self._write(bytes([0x5B, 0x02, 0xF1, 0x04, 0x5D]))
        return ResultCode.SUCCESS
    
    async def incline_down(self) -> ResultCode:
        await self._write(bytes([0x5B, 0x02, 0xF1, 0x05, 0x5D]))
        return ResultCode.SUCCESS
    
    async def _send_ack(self, msg_type: int) -> None:
        """Send ACK for message type."""
        ack = bytes([0x5B, 0x04, 0x00, msg_type, 0x4F, 0x4B, 0x5D])
        await self._write(ack)
    
    async def _write(self, data: bytes) -> None:
        """Write to Sole characteristic."""
        await self._client.write_gatt_char(self.WRITE_UUID, data, response=False)
```

### Device Factory (`factory.py`)

```python
from .machines import Treadmill, IndoorBike, Rower, CrossTrainer
from .protocols import FtmsProtocol, SoleProtocol

# Device name prefixes for Sole treadmills
SOLE_PREFIXES = ("F63", "F65", "F80", "F85", "F89", "S77", "TT8", "ST90", "TRX7.5")

def detect_machine(device: BLEDevice, adv: AdvertisementData) -> FitnessMachine | None:
    """Detect machine type and protocol from advertisement."""
    name = (device.name or "").upper()
    
    # Check for Sole treadmill (has FTMS but needs custom protocol)
    for prefix in SOLE_PREFIXES:
        if name.startswith(prefix):
            return Treadmill(
                device, adv,
                protocol=SoleProtocol(),
                supports_incremental=True,
            )
    
    # Standard FTMS detection
    if has_ftms_service(adv):
        machine_type = get_machine_type_from_adv(adv)
        return create_ftms_machine(device, adv, machine_type)
    
    return None
```

## Home Assistant Integration Changes

Add button entities for incremental control:

```python
# ftms/button.py
from homeassistant.components.button import ButtonEntity

class SpeedUpButton(ButtonEntity):
    """Button to increase treadmill speed."""
    
    async def async_press(self) -> None:
        await self._machine.speed_up()

class SpeedDownButton(ButtonEntity):
    """Button to decrease treadmill speed."""
    
    async def async_press(self) -> None:
        await self._machine.speed_down()

# Similar for InclineUpButton, InclineDownButton
```

Expose buttons only when `supports_incremental=True`.

## Migration Path

1. **Phase 1**: Add SoleProtocol as alternate backend (current work)
2. **Phase 2**: Refactor to protocol interface pattern
3. **Phase 3**: Add more custom protocols (Horizon, NordicTrack, etc.)

## Key Differences from qdomyos

| Aspect | qdomyos | pyftms (proposed) |
|--------|---------|-------------------|
| Language | C++/Qt | Python/asyncio |
| Detection | 4000+ line switch | Simple prefix matching |
| Classes | 70+ device classes | Protocol backends |
| Scope | All fitness devices | FTMS-compatible + Sole |
| Virtual Device | Re-exposes as FTMS | Not needed (HA handles) |

## Why This Approach

1. **Minimal disruption**: Keep existing FTMS code, add new protocol layer
2. **Clean abstraction**: Protocol interface hides implementation details
3. **Extensible**: Easy to add more custom protocols
4. **HA integration**: Button entities fit well with incremental control
