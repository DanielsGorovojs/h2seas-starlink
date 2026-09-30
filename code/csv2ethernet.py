# How to run:
# python csv2ethernet.py --port 10110 --speed 60 --loop
#
# Emulates an NMEA-to-Ethernet converter: every CSV row is split into one
# proprietary NMEA 0183 sentence per sensor and sent to a TCP client.
#
# Sentence format:
#   $PH2S,<sensor_id>,<hhmmss.ss>,<ddmmyy>,<v1>,<v2>,...*<checksum>\r\n

import argparse
import csv
import socket
import time
from datetime import datetime

BME688_COLS = [
    "BME688_Pressure_hPa", "BME688_Humidity_RH_pct", "BME688_Temperature_C",
    "BME688_VOC_ppm", "BME688_VSC_ppb", "BME688_CO_ppm", "BME688_H2_ppm",
]
ENS160_COLS = [
    "ENS160_TVOC_ppb", "ENS160_EtOH_ppm", "ENS160_H2_ppm", "ENS160_Acetone_ppm",
    "ENS160_Toluene_ppm", "ENS160_eCO2_ppm", "ENS160_AQI_UBA",
]
MICS4514_COLS = [
    "MiCS4514_CO_ppm", "MiCS4514_NO2_ppm", "MiCS4514_EtOH_ppm",
    "MiCS4514_H2_ppm", "MiCS4514_NH3_ppm", "MiCS4514_CH4_ppm",
]
SP30_COLS = ["SP30_PM10_ugm3", "SP30_PM2_5_ugm3"]

ADXL_SUB = ["RMSx_g", "RMSy_g", "RMSz_g", "RMSvec_g", "VDV_ms1_75", "Peak_g", "CF"]
MIC_SUB = ["Audio_RMS_A_norm", "Audio_dB_A_rel", "Audio_Peak_A", "Audio_CF_A"]

# One NMEA sentence is sent per sensor for every CSV row: (sensor_id, CSV columns)
SENSORS = [
    ("BME688", BME688_COLS),
    ("ENS160", ENS160_COLS),
    ("MICS4514", MICS4514_COLS),
    ("SP30", SP30_COLS),
]
SENSORS += [(f"ADXL355Z_{i}", [f"ADXL355Z_{i}_{s}" for s in ADXL_SUB]) for i in (1, 2, 3)]
SENSORS += [(f"ICS43434_{i}", [f"ICS43434_{i}_{s}" for s in MIC_SUB]) for i in (1, 2, 3)]

# Proprietary NMEA sentences start with "P" + a 3-letter manufacturer code
NMEA_PREFIX = "PH2S"


def parse_timestamp(value):
    """Parse a CSV timestamp like "2026-09-28T06:00:00.000Z" into a datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_sentence(sensor_id, ts, values):
    """Build one NMEA sentence from a sensor id, a timestamp and its values.

    Example:
        build_sentence("SP30", <06:06:00 28.09.2026>, ["14.937", "10.207"])
        -> "$PH2S,SP30,060600.00,280926,14.937,10.207*70\\r\\n"
    """
    # NMEA time is hhmmss.ss and date is ddmmyy
    time_field = ts.strftime("%H%M%S.") + f"{ts.microsecond // 10000:02d}"
    date_field = ts.strftime("%d%m%y")
    body = ",".join([NMEA_PREFIX, sensor_id, time_field, date_field] + values)

    # NMEA checksum: XOR of all characters in the body, written as 2 hex digits
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}\r\n"


def row_to_sentences(row):
    """Split one CSV row (dict of column -> value) into one NMEA sentence per sensor."""
    ts = parse_timestamp(row["Timestamp_Device_UTC"])
    return [build_sentence(sensor_id, ts, [row[c] for c in cols])
            for sensor_id, cols in SENSORS]


def csv_to_ethernet(csv_file, port, speed=1.0, loop=False):
    """Act as the converter: wait for a TCP client, then stream the CSV to it.

    Rows are sent with the same time spacing as in the CSV, sped up by
    `speed` (e.g. 60 -> 2 minutes between rows become 2 seconds).
    """
    with open(csv_file, newline="") as f:
        rows = list(csv.DictReader(f))

    # A real converter is a TCP server; the receiving script connects to it
    server = socket.create_server(("0.0.0.0", port))
    print(f"Waiting for a client on port {port}...")
    conn, addr = server.accept()
    print(f"Client connected: {addr[0]}")

    with server, conn:
        while True:
            prev_ts = None
            for row in rows:
                # Wait as long as the gap between this row and the previous one.
                # If a row is out of order (negative gap), send it immediately.
                ts = parse_timestamp(row["Timestamp_Device_UTC"])
                if prev_ts is not None:
                    time.sleep(max(0, (ts - prev_ts).total_seconds() / speed))
                prev_ts = ts

                for sentence in row_to_sentences(row):
                    conn.sendall(sentence.encode("ascii"))

            if not loop:
                break


def main():
    parser = argparse.ArgumentParser(description="Replay sensor CSV as NMEA 0183 sentences over TCP")
    parser.add_argument("--csv", default="sensor_suite_sample_data.csv", help="input CSV file")
    parser.add_argument("--port", type=int, default=10110, help="TCP port (10110 is the standard NMEA port)")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier vs. CSV timestamps")
    parser.add_argument("--loop", action="store_true", help="restart from the top when the CSV ends")
    args = parser.parse_args()

    csv_to_ethernet(args.csv, args.port, args.speed, args.loop)


if __name__ == "__main__":
    main()
