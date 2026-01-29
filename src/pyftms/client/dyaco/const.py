# Copyright 2024-2025
# SPDX-License-Identifier: Apache-2.0

"""
Constants for Dyaco equipment UART protocol.

Dyaco International (Taiwan) manufactures fitness equipment sold under multiple brands:
- SOLE Fitness (F63, F65, F80, F85 treadmills; E25, E35, E55, E95 ellipticals; B94, R92 bikes)
- Spirit Fitness (XT series treadmills; XE, XBR, XBU series)
- XTERRA Fitness (TRX series)
- Fuel Fitness

All equipment shares the same BLE firmware and uses ISSC/Microchip "Transparent UART"
for the proprietary protocol (in addition to standard FTMS).

DEVICE IDENTIFICATION (how the SOLE Fitness app does it):
---------------------------------------------------------
The official SOLE Fitness app identifies compatible devices in two steps:

1. SCANNING: Match BLE device names against known prefixes:
   - SOLE: F63, F65, F80, F85, E25, E35, E55, E95, B94, R92, LCB, LCR, S77, TT8...
   - Spirit: CT800, CT850, XT185, XT285, XT385, CE800, XE195, XBR25...
   - XTERRA: TRX1000, TRX2500, TRX3500...
   - Fuel: various models

2. AFTER CONNECTION: Check for the UART service UUID to confirm proprietary protocol
   support, then send 0xF0 command to get detailed model info (brand, type, capabilities).

OUR APPROACH:
-------------
We skip the device name matching and simply check for the UART service UUID after
connecting to any FTMS device. This is simpler and works for unknown model names,
but is technically different from the app's method.

The service UUID prefix "49535343" is ASCII for "ISSC" - the vendor ID for ISSC
Technologies (now Microchip), a Taiwanese BLE chip manufacturer. This is NOT a
standard Bluetooth SIG profile - it's a proprietary serial-over-BLE implementation.
"""

# =============================================================================
# UART Service UUIDs (ISSC/Microchip Transparent UART)
# =============================================================================
# UUID prefix "49535343" = ASCII "ISSC" (ISSC Technologies vendor ID)
# This identifies the BLE chip manufacturer, not the fitness equipment brand.
# All Dyaco brands (SOLE, Spirit, XTERRA, Fuel) use ISSC chips with this service.

UART_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
UART_WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
UART_NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

# Secondary service (fallback for older equipment)
UART_SECONDARY_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
UART_SECONDARY_WRITE_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
UART_SECONDARY_NOTIFY_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

# Protocol framing
START_BYTE = 0x5B  # '['
END_BYTE = 0x5D    # ']'

# =============================================================================
# Device Name Prefixes (for scanning/identification)
# =============================================================================
# The SOLE Fitness app matches these BLE device name prefixes during scanning.
# We use this as a secondary check alongside the UART service UUID.

DYACO_DEVICE_PREFIXES = (
    # SOLE Fitness
    "SOLE", "Sole",
    "F63", "F65", "F80", "F85", "S77", "TT8",  # Treadmills
    "E25", "E35", "E55", "E95", "E95S", "E96S", "E98",  # Ellipticals
    "B94", "R92", "LCB", "LCR", "SC200", "SC300",  # Bikes
    # Spirit Fitness
    "SPIRIT", "Spirit",
    "CT800", "CT850",  # Commercial treadmills
    "XT185", "XT285", "XT385", "XT485", "XT685",  # Home treadmills
    "CE800", "CE850", "CS800",  # Commercial ellipticals
    "XE195", "XE295", "XE395", "XE895", "XG400",  # Home ellipticals
    "CR800", "CU800", "CRS800S",  # Commercial bikes
    "XBR25", "XBR55", "XBU55",  # Home bikes
    # XTERRA Fitness
    "XTERRA", "Xterra",
    "TRX1000", "TRX2500", "TRX3500", "TRX4500", "TRX7.5",
    "XT7.8", "XT96", "XT98", "XT800", "XT900",
    "SB4500",  # Bikes
    # Fuel Fitness
    "FUEL", "Fuel",
)
