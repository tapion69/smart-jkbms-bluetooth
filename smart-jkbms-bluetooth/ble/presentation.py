"""Stable English Home Assistant MQTT names and section ordering.

MQTT Discovery supports only native HA entity categories:
  - diagnostic -> information/status group
  - no category -> measured sensors
  - config -> editable settings
Natural English labels do not include numeric ordering prefixes. HA controls native ordering.
Do not derive names from BLE device-provided names or localized labels.
"""
from __future__ import annotations

# Fixed unnumbered labels for information about the BMS.
INFO_NAMES = {
    "battery_type": "Battery Type",
    "software_version": "Software Version",
    "hardware_version": "Hardware Version",
    "serial_number": "Serial Number",
    "device_name": "BMS Name",
    "manufacturing_date": "Manufacturing Date",
    "alarm_text": "BMS Alarm List",
    "device_model": "BMS Model",
}
# The physical state of a BMS switch is not the same thing as the
# command/settings switch exposed separately in HA Configuration.
INFO_BINARY_NAMES = {
    "alarm_active": "BMS Alarm Active",
    "charging_mos": "Charge MOS Active",
    "discharging_mos": "Discharge MOS Active",
    "precharge": "Precharge Active",
    "heating": "Heating Active",
    "charger_connected": "Charger Connected",
    "dry1_contact": "DRY1 Contact",
    "dry2_contact": "DRY2 Contact",
    "emergency_active": "Emergency Active",
    "balancing_active": "Balancing Active",
    "pcl_module_active": "PCL Module Active",
}
# Fixed unnumbered labels for electrical measurements.
MAIN_NAMES = {
    "soc_pct": "SOC",
    "voltage_v": "Total Voltage",
    "power_w": "Total Power",
    "current_a": "Total Current",
    "charge_power_w": "Charge Power",
    "discharge_power_w": "Discharge Power",
    "cell_avg_v": "Average Cell Voltage",
    "cell_delta_v": "Cell Voltage Delta",
    "cell_min_v": "Min Cell Voltage",
    "cell_min_number": "Min Cell Voltage - Cell Number",
    "cell_max_v": "Max Cell Voltage",
    "cell_max_number": "Max Cell Voltage - Cell Number",
    "balance_current_a": "Balance Current",
    "temp1_c": "Temperature Sensor 1",
    "temp2_c": "Temperature Sensor 2",
    "mos_temp_c": "MOS Temperature",
    "temp3_c": "Temperature Sensor 3",
    "temp4_c": "Temperature Sensor 4",
    "temp5_c": "Temperature Sensor 5",
    # Pair voltage with resistance under the same cell prefix, without sort numbers.
    "cycles": "Cycle Count",
    "soh_pct": "SOH",
    "capacity_remaining_ah": "Remaining Capacity",
    "total_cycle_capacity_ah": "Total Cycled Capacity",
    "total_runtime_formatted": "Total Runtime",
    "balance_state": "Balancing State",
    "charge_status": "Charge Status",
    "power_on_count": "Power-On Count",
    "heating_current_a": "Heating Current",
    "charge_status_time_s": "Charge Status Duration",
    "smart_sleep_countdown_s": "Smart Sleep Countdown",
    "emergency_time_countdown_s": "Emergency Countdown",
    "detail_log_count": "Detail Log Count",
    "rcv_time_h": "RCV Time",
    "rfv_time_h": "RFV Time",
    "discharge_ocp_release_s": "Discharge OCP Recovery",
    "discharge_short_release_s": "Discharge Short Recovery",
    "charge_ocp_release_s": "Charge OCP Recovery",
    "charge_short_release_s": "Charge Short Recovery",
    "undervoltage_release_s": "Undervoltage Recovery",
    "overvoltage_release_s": "Overvoltage Recovery",
}
# These verified configuration-switch states are also published read-only
# within Info. The editable entities remain in HA Configuration.
CONFIG_STATUS_NAMES = {
    "charging_enabled": "Charging Switch Enabled",
    "discharging_enabled": "Discharging Switch Enabled",
    "balancer_enabled": "Balance Switch Enabled",
    "heating_enabled": "Heating Switch Enabled",
    "disable_temperature_sensors": "Temperature Monitoring Disabled",
    "display_always_on": "Display Always On",
    "smart_sleep_enabled": "Smart Sleep Enabled",
    "disable_pcl_module": "PCL Module Disabled",
    "timed_stored_data": "Timed Data Storage Enabled",
    "charging_float_mode": "Charging Float Mode Enabled",
}
# Any remaining information sensor has an English fixed fallback.  The
# exposed parameter labels are defined in the explicit JK02 register catalog.
def sensor_name(key: str, fallback: str) -> str:
    return INFO_NAMES.get(key) or MAIN_NAMES.get(key) or fallback

def binary_name(key: str, fallback: str) -> str:
    return INFO_BINARY_NAMES.get(key, fallback)

def cell_voltage_name(number: int) -> str:
    return f"Cell {number:02d} Voltage"

def cell_resistance_name(number: int) -> str:
    return f"Cell {number:02d} Voltage - Resistance"
