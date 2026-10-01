import argparse
import csv
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import json


def on_message(client, userdata, message):
    """Print every MQTT message the broker delivers to us.

    paho calls this function automatically for each received message.

    Example output:
        h2seas/nose/sp30/pm10_ugm3 {"time": 1790575560.0, "value": 14.937}
    """
    # The payload arrives as raw bytes; decode() turns it into text
    print(message.topic, message.payload.decode())

def json2tuple(json_topic):
    decoder = json.decoder.JSONDecoder(parse_float=float)

    data = decoder.decode(json_topic)

    return (data["time"],data["value"])


def save_point(topic, unix_time, value):
    """Append one data point as a CSV row to the file of the day it was measured.

    The file name comes from the measurement time (UTC), so points from
    different days end up in different files.

    Example:
        save_point("h2seas/nose/sp30/pm10_ugm3", 1790575560.0, 14.937)
        -> appends "h2seas/nose/sp30/pm10_ugm3,1790575560.0,14.937"
           to data_2026-09-28.csv
    """
    day = datetime.fromtimestamp(unix_time, timezone.utc).strftime("%Y-%m-%d")

    # "a" = append: creates the file if missing, otherwise adds to the end.
    # newline="" stops Windows from adding an extra empty line after each row.
    with open(f"data_{day}.csv", "a", newline="") as f:
        csv.writer(f).writerow([topic, unix_time, value])


def main():
    """Connect to the MQTT broker, subscribe to all h2seas topics and print messages.

    Runs until Ctrl+C.

    Example:
        py mqtt_subscriber.py --mqtt-host 127.0.0.1
    """
    parser = argparse.ArgumentParser(description="Print all h2seas MQTT messages")
    parser.add_argument("--mqtt-host", default="127.0.0.1", help="MQTT broker address")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(args.mqtt_host, args.mqtt_port)

    # "#" is the multi-level wildcard: every topic below h2seas/
    client.subscribe("h2seas/#", qos=1)

    # loop_forever() blocks here and runs paho's network loop in this thread:
    # it receives messages and calls on_message for each of them
    client.loop_forever()


if __name__ == "__main__":
    main()
