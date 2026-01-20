# Copyright 2024-2025, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0

# REAL-TIME TRAINING DATA

CADENCE_AVERAGE = "cadence_average"
CADENCE_INSTANT = "cadence_instant"
DISTANCE_TOTAL = "distance_total"
ELEVATION_GAIN_NEGATIVE = "elevation_gain_negative"
ELEVATION_GAIN_POSITIVE = "elevation_gain_positive"
ENERGY_PER_HOUR = "energy_per_hour"
ENERGY_PER_MINUTE = "energy_per_minute"
ENERGY_TOTAL = "energy_total"
FORCE_ON_BELT = "force_on_belt"
HEART_RATE = "heart_rate"
INCLINATION = "inclination"
INDOOR_BIKE_SIMULATION = "indoor_bike_simulation"
METABOLIC_EQUIVALENT = "metabolic_equivalent"
MOVEMENT_DIRECTION = "movement_direction"
PACE_AVERAGE = "pace_average"
PACE_INSTANT = "pace_instant"
POWER_AVERAGE = "power_average"
POWER_INSTANT = "power_instant"
POWER_OUTPUT = "power_output"
RAMP_ANGLE = "ramp_angle"
RESISTANCE_LEVEL = "resistance_level"
SPEED_AVERAGE = "speed_average"
SPEED_INSTANT = "speed_instant"
SPLIT_TIME_AVERAGE = "split_time_average"
SPLIT_TIME_INSTANT = "split_time_instant"
STEP_COUNT = "step_count"
STEP_RATE_AVERAGE = "step_rate_average"
STEP_RATE_INSTANT = "step_rate_instant"
STRIDE_COUNT = "stride_count"
STROKE_COUNT = "stroke_count"
STROKE_RATE_AVERAGE = "stroke_rate_average"
STROKE_RATE_INSTANT = "stroke_rate_instant"
TIME_ELAPSED = "time_elapsed"
TIME_REMAINING = "time_remaining"
TRAINING_STATUS = "training_status"

# TARGET SETTINGS ATTRIBUTES

# WITH RANGES

# Optional

TARGET_SPEED = "target_speed"
TARGET_POWER = "target_power"
TARGET_HEART_RATE = "target_heart_rate"
TARGET_INCLINATION = "target_inclination"
TARGET_RESISTANCE = "target_resistance"

# WITHOUT RANGES

# Mandatory

RESET = "reset"
START = "start"
STOP = "stop"
PAUSE = "pause"

# Optional

BIKE_SIMULATION = "bike_simulation"
SPIN_DOWN = "spin_down"
TARGET_CADENCE = "target_cadence"
TARGET_DISTANCE = "target_distance"
TARGET_ENERGY = "target_energy"
TARGET_STEPS = "target_steps"
TARGET_STRIDES = "target_strides"
TARGET_TIME = "target_time"
TARGET_TIME_TWO_ZONES = "target_time_two_zones"
TARGET_TIME_TIME_THREE_ZONES = "target_time_three_zones"
TARGET_TIME_TIME_FIVE_ZONES = "target_time_five_zones"
WHEEL_CIRCUMFERENCE = "wheel_circumference"

# Bluetooth FTMS UUIDs

FTMS_UUID = "1826"
"""Fitness Machine Service"""

FEATURE_UUID = "2acc"
"""
`Requirement`: Mandatory.
`Property`: Read.
`Device Type`: Treadmill, walking pad, elliptical machine, rower, and smart bike.
`Description`: Describes the capabilities supported by the device.
"""

TREADMILL_DATA_UUID = "2acd"
"""
`Requirement`: Optional.
`Property`: Notify.
`Device Type`: Treadmill and walking pad only.
`Description`: Reports real-time workout data.
"""

CROSS_TRAINER_DATA_UUID = "2ace"
"""
`Requirement`: Optional.
`Property`: Notify.
`Device Type`: Elliptical machines only.
`Description`: Reports real-time workout data.
"""

ROWER_DATA_UUID = "2ad1"
"""
`Requirement`: Optional.
`Property`: Notify.
`Device Type`: Rower only.
`Description`: Reports real-time workout data.
"""

INDOOR_BIKE_DATA_UUID = "2ad2"
"""
`Requirement`: Optional.
`Property`: Notify.
`Device Type`: Smart bike only.
`Description`: Reports real-time workout data.
"""

TRAINING_STATUS_UUID = "2ad3"
"""
`Requirement`: Optional.
`Property`: Read/Notify.
`Device Type`: Treadmill, walking pad, elliptical machine, rower, and smart bike.
`Description`: Reports the device status data.
"""

SPEED_RANGE_UUID = "2ad4"
"""
`Requirement`: Mandatory if the `Speed Target Setting` feature is supported; otherwise Optional.
`Property`: Read.
`Device Type`: Treadmill, walking pad, and smart bike.
`Description`: Reports the supported speed range.
"""

INCLINATION_RANGE_UUID = "2ad5"
"""
`Requirement`: Mandatory if the `Inclination Target Setting` feature is supported; otherwise Optional.
`Property`: Read.
`Device Type`: Treadmill and walking pad.
`Description`: Reports the supported inclination range.
"""

RESISTANCE_LEVEL_RANGE_UUID = "2ad6"
"""
`Requirement`: Mandatory if the `Resistance Target Setting` feature is supported; otherwise Optional.
`Property`: Read.
`Device Type`: Elliptical machine.
`Description`: Reports the supported resistance level range.
"""

HEART_RATE_RANGE_UUID = "2ad7"
"""
`Requirement`: Mandatory if the `Heart Rate Target Setting` feature is supported; otherwise Optional.
`Property`: Read.
`Device Type`: Treadmill, walking pad, elliptical machine, rower, and smart bike.
`Description`: Reports supported heart rate range.
"""

POWER_RANGE_UUID = "2ad8"
"""
`Requirement`: Mandatory if the `Power Target Setting` feature is supported; otherwise Optional.
`Property`: Read.
`Device Type`: Elliptical machine, rower, and smart bike.
`Description`: Reports the supported power range.
"""

CONTROL_POINT_UUID = "2ad9"
"""
`Requirement`: Optional.
`Property`: Write/Indicate.
`Device Type`: Optional support for treadmills and walking pads, and mandatory for elliptical machines, rowers, and smart bikes.
`Description`: Controls the status (paused or resumed) of fitness machine.
"""

STATUS_UUID = "2ada"
"""
`Requirement`: Mandatory if the `Fitness Machine Control Point` is supported; otherwise Optional.
`Property`: Notify.
`Device Type`: Treadmill, walking pad, elliptical machine, rower, and smart bike.
`Description`: Reports workout status changes of the fitness machine.
"""

# Sole Treadmill Proprietary Protocol
# References:
# - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift
#   src/devices/solef80treadmill/solef80treadmill.cpp
# - treadonme: https://github.com/swedishborgie/treadonme

SOLE_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
"""Sole Proprietary Service UUID"""

SOLE_WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
"""Sole Write Characteristic UUID"""

SOLE_NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
"""Sole Notify Characteristic UUID"""

# Sole control commands (framed with 0x5b start, 0x5d end)
# F1 commands for direct control
SOLE_CMD_SPEED_UP = bytes([0x5b, 0x02, 0xf1, 0x02, 0x5d])
SOLE_CMD_SPEED_DOWN = bytes([0x5b, 0x02, 0xf1, 0x03, 0x5d])
SOLE_CMD_INCLINE_UP = bytes([0x5b, 0x02, 0xf1, 0x04, 0x5d])
SOLE_CMD_INCLINE_DOWN = bytes([0x5b, 0x02, 0xf1, 0x05, 0x5d])
SOLE_CMD_START = bytes([0x5b, 0x02, 0xf1, 0x01, 0x5d])  # F1 Start
SOLE_CMD_STOP = bytes([0x5b, 0x02, 0xf1, 0x06, 0x5d])   # F1 Stop
# SetWorkoutMode commands - qdomyos uses 0x03 as message type with mode in payload
SOLE_CMD_SET_MODE_RUNNING = bytes([0x5b, 0x02, 0x03, 0x04, 0x5d])  # WorkoutMode = Running (0x04)
SOLE_CMD_SET_MODE_PAUSE = bytes([0x5b, 0x02, 0x03, 0x06, 0x5d])    # WorkoutMode = Pause (0x06)
SOLE_CMD_SET_MODE_DONE = bytes([0x5b, 0x02, 0x03, 0x07, 0x5d])     # WorkoutMode = Done (0x07)
SOLE_CMD_SET_MODE_IDLE = bytes([0x5b, 0x02, 0x03, 0x01, 0x5d])     # WorkoutMode = Idle (0x01)

# Sole startup sequence messages (for initializing on connection)
SOLE_CMD_GET_INFO = bytes([0x5b, 0x01, 0xf0, 0x5d])  # GetDeviceInfo
SOLE_CMD_ACK_0x10 = bytes([0x5b, 0x04, 0x00, 0x10, 0x4f, 0x4b, 0x5d])  # ACK for 0x10
SOLE_CMD_ACK_0x09 = bytes([0x5b, 0x04, 0x00, 0x09, 0x4f, 0x4b, 0x5d])  # ACK for HeartRateType
SOLE_CMD_USER_PROFILE = bytes([0x5b, 0x06, 0x07, 0x01, 0x23, 0x00, 0x9b, 0xaa, 0x5d])  # UserProfile from qdomyos F65
SOLE_CMD_PROGRAM_MANUAL = bytes([0x5b, 0x03, 0x08, 0x10, 0x01, 0x5d])  # Manual program
SOLE_CMD_WORKOUT_TARGET = bytes([0x5b, 0x05, 0x04, 0x00, 0x00, 0x00, 0x00, 0x5d])  # No target
SOLE_CMD_MAX_INCLINE = bytes([0x5b, 0x02, 0x22, 0x09, 0x5d])  # Max incline = 9
SOLE_CMD_SET_MODE_START = bytes([0x5b, 0x02, 0x02, 0x02, 0x5d])  # SetWorkoutMode(0x02) = Start(0x02)

# Button key constants for Sole incremental controls
SPEED_UP = "speed_up"
SPEED_DOWN = "speed_down"
INCLINE_UP = "incline_up"
INCLINE_DOWN = "incline_down"

# FTMS Variant identifiers (for manufacturer-specific protocols)
FTMS_VARIANT_GENERIC = "generic"   # Standard FTMS protocol
FTMS_VARIANT_SOLE = "sole"         # Sole/Spirit treadmills (proprietary incremental controls)
# Future variants: "horizon", "nordictrack", etc.

# Known Sole treadmill name prefixes
SOLE_TREADMILL_NAMES = ("F63", "F65", "F80", "F85", "F89", "S77", "TT8", "ST90", "TRX7.5")
