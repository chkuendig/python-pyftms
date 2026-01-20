# Copyright 2025, Christian Kündig
# SPDX-License-Identifier: Apache-2.0
#
# Protocol backends for pyftms
# Allows supporting both standard FTMS and custom protocols (Sole, etc.)

from .base import MachineProtocol, ProtocolCapabilities
from .sole import SoleProtocol

__all__ = [
    "MachineProtocol",
    "ProtocolCapabilities",
    "SoleProtocol",
]
