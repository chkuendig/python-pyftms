# Copyright 2024-2025
# SPDX-License-Identifier: Apache-2.0

"""
Dyaco equipment support module.

This module provides support for Dyaco-manufactured fitness equipment using
their proprietary UART-over-BLE protocol. Dyaco manufactures equipment sold
under multiple brands: SOLE, Spirit, XTERRA, and Fuel.

Device detection follows the same two-step approach as the official SOLE Fitness app:
1. Device name prefix matching - check BLE device names against DYACO_DEVICE_PREFIXES
2. UART service UUID check - verify the ISSC Transparent UART service is present
   (UUID prefix "49535343" = ASCII "ISSC" - identifies ISSC/Microchip BLE chips)

Both conditions must be met to enable UART monitoring. This provides extended data
(incline, distance, calories) that Dyaco's FTMS implementation omits.
"""

from .const import UART_SERVICE_UUID, DYACO_DEVICE_PREFIXES
from .uart_updater import DyacoUartUpdater

__all__ = [
    "UART_SERVICE_UUID",
    "DYACO_DEVICE_PREFIXES",
    "DyacoUartUpdater",
]
