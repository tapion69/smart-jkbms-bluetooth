"""Stable English Home Assistant MQTT names and section ordering.

MQTT Discovery supports only native HA entity categories:
  - diagnostic -> information/status group
  - no category -> measured sensors
  - config -> editable settings
Numeric name prefixes are stable *labels*, not parts of entity IDs.
Do not derive names from BLE device-provided names or localized labels.
"""
from __future__ import annotations

# Position 01 to 09: information about the BMS.
INFO_NAMES = {
    "battery_type": "02 Battery Type",
    "software_version": "03 Software Version",
    "hardware_version": "04 Hardware Version",
    "serial_number": "05 Serial Number",
    "device_name": "06 BMS Name",
    "manufacturing_date": "07 Manufacturing Date",
    "alarm_text": "09 BMS Alarm List",
    "device_model": "10 BMS Model",
}
# The physical state of a BMS switch is not the same thing as the
# command/settings switch exposed separately in HA Configuration.
INFO_BINARY_NAMES = {
    "alarm_active": "08 BMS Alarm Active",
    "charging_mos": "11 Charge MOS Active",
    "discharging_mos": "12 Discharge MOS Active",
    "precharge": "13 Precharge Active",
    "heating": "14 Heating Active",
    "charger_connected": "15 Charger Connected",
    "dry1_contact": "16 DRY1 Contact",
    "dry2_contact": "17 DRY2 Contact",
    "emergency_active": "18 Emergency Active",
    "balancing_active": "19 Balancing Active",
    "pcl_module_active": "20 PCL Module Active",
}
# Display all primary electrical values before each cell's paired readings.
MAIN_NAMES = {
    "soc_pct": "01 SOC",
    "voltage_v": "02 Total Voltage",
    "power_w": "03 Total Power",
    "current_a": "04 Total Current",
    "charge_power_w": "05 Charge Power",
    "discharge_power_w": "06 Discharge Power",
    "cell_avg_v": "07 Average Cell Voltage",
    "cell_delta_v": "08 Cell Voltage Delta",
    "cell_min_v": "09 Min Cell Voltage",
    "cell_min_number": "10 Min Cell Number",
    "cell_max_v": "11 Max Cell Voltage",
    "cell_max_number": "12 Max Cell Number",
    "balance_current_a": "13 Balance Current",
    "temp1_c": "14 Temperature Sensor 1",
    "temp2_c": "15 Temperature Sensor 2",
    "mos_temp_c": "16 MOS Temperature",
    "temp3_c": "17 Temperature Sensor 3",
    "temp4_c": "18 Temperature Sensor 4",
    "temp5_c": "19 Temperature Sensor 5",
    # Cell voltage/resistance pairs use the stable '20 Cell XX' prefix.
    "cycles": "80 Cycle Count",
    "soh_pct": "81 SOH",
    "capacity_remaining_ah": "82 Remaining Capacity",
    "total_cycle_capacity_ah": "83 Total Cycled Capacity",
    "total_runtime_formatted": "84 Total Runtime",
    "balance_state": "85 Balancing State",
    "charge_status": "86 Charge Status",
    "power_on_count": "87 Power-On Count",
    "heating_current_a": "88 Heating Current",
    "charge_status_time_s": "89 Charge Status Duration",
    "smart_sleep_countdown_s": "90 Smart Sleep Countdown",
    "emergency_time_countdown_s": "91 Emergency Countdown",
    "detail_log_count": "92 Detail Log Count",
    "rcv_time_h": "93 RCV Time",
    "rfv_time_h": "94 RFV Time",
    "discharge_ocp_release_s": "95 Discharge OCP Recovery",
    "discharge_short_release_s": "96 Discharge Short Recovery",
    "charge_ocp_release_s": "97 Charge OCP Recovery",
    "charge_short_release_s": "98 Charge Short Recovery",
    "undervoltage_release_s": "99 Undervoltage Recovery",
    "overvoltage_release_s": "100 Overvoltage Recovery",
}
# These verified configuration-switch states are also published read-only
# within Info. The editable entities remain in HA Configuration.
CONFIG_STATUS_NAMES = {
    "charging_enabled": "30 Charging Switch Enabled",
    "discharging_enabled": "31 Discharging Switch Enabled",
    "balancer_enabled": "32 Balance Switch Enabled",
    "heating_enabled": "33 Heating Switch Enabled",
    "disable_temperature_sensors": "34 Temperature Monitoring Disabled",
    "display_always_on": "35 Display Always On",
    "smart_sleep_enabled": "36 Smart Sleep Enabled",
    "disable_pcl_module": "37 PCL Module Disabled",
    "timed_stored_data": "38 Timed Data Storage Enabled",
    "charging_float_mode": "39 Charging Float Mode Enabled",
}
# Any remaining information sensor has an English fixed fallback.  The
# exposed parameter labels are defined in the explicit JK02 register catalog.
def sensor_name(key: str, fallback: str) -> str:
    return INFO_NAMES.get(key) or MAIN_NAMES.get(key) or "110 " + fallback

def binary_name(key: str, fallback: str) -> str:
    return INFO_BINARY_NAMES.get(key, "50 " + fallback)

def cell_voltage_name(number: int) -> str:
    return f"20 Cell {number:02d} - 1 Voltage"

def cell_resistance_name(number: int) -> str:
    return f"20 Cell {number:02d} - 2 Resistance"
