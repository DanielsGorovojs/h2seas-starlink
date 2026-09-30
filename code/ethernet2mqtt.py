import argparse
from datetime import datetime, timezone
import json
import paho.mqtt.client as mqtt
import sys
import socket


def nmea_time2unix(hhmmss, ddmmyy):
    """Convert NMEA time and date fields (UTC) into Unix seconds.

    The NMEA time has 1/100 s resolution, so the result is rounded
    to 2 decimals.

    Example:
        nmea_time2unix("060600.00", "280926") -> 1790575560.0
    """
    # %f reads the fraction after the dot ("50" -> 0.50 s)
    dt = datetime.strptime(ddmmyy + hhmmss, "%d%m%y%H%M%S.%f")

    # NMEA times are always UTC; without this, Python would assume local time
    dt = dt.replace(tzinfo=timezone.utc)
    return round(dt.timestamp(), 2)


def nmea2mqtt(nmea_sentence, topic_dict):
    """Convert one NMEA sentence into a list of (MQTT topic, JSON payload) pairs.

    Example:
        $PH2S,SP30,060600.00,280926,14.937,10.207*70
        -> [("h2seas/nose/sp30/pm10_ugm3", '{"time": 1790575560.0, "value": 14.937}'),
            ("h2seas/nose/sp30/pm2_5_ugm3", '{"time": 1790575560.0, "value": 10.207}')]

    topic_dict is the content of nmea_topics.json. It tells which sensor
    the sentence belongs to and which topic each value position maps to.
    """
    # "$<body>*<checksum>" -> body and checksum
    body, checksum = nmea_sentence.strip()[1:].split("*")

    # NMEA checksum: XOR of all characters in the body, written as 2 hex digits
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    if f"{cs:02X}" != checksum:
        raise ValueError(f"Checksum mismatch: {nmea_sentence!r}")

    # Fields: talker, sensor id, time, date, value1, value2, ...
    fields = body.split(",")
    sensor = topic_dict["sensors"][fields[1]]
    values = fields[1 + len(topic_dict["header_fields"]):]
    unix_time = nmea_time2unix(fields[2], fields[3])

    # The n-th value in the sentence goes to the n-th topic in the JSON,
    # json.dumps() turns the dict into a text payload for MQTT
    return [(f"{sensor['topic']}/{v['topic']}",
             json.dumps({"time": unix_time, "value": float(value)}))
            for v, value in zip(sensor["values"], values)]


def read_nmea_sentences(host, port):
    """Connect to the NMEA-to-Ethernet converter and yield sentences one by one.

    The converter is a TCP server that sends a continuous text stream,
    one NMEA sentence per line (terminated by \\r\\n).
    """
    sock = socket.create_connection((host, port))
    print(f"Connected to converter at {host}:{port}", file=sys.stderr)

    # makefile() lets us read the TCP stream line by line like a text file
    with sock, sock.makefile("r", encoding="ascii", newline="\n") as stream:
        for line in stream:
            yield line.strip()


def on_connect(client, userdata, flags, reason_code, properties):

    print(f"MQTT connect: {reason_code}", file=sys.stderr)

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):

    print(f"MQTT disconnect: {reason_code}", file=sys.stderr)

def on_publish(client, userdata, mid, reason_code, properties):

    print(f"MQTT published: mid={mid} {reason_code}", file=sys.stderr)



def connect_mqtt(host, port):
    """Connect to the MQTT broker and return a client ready for publishing.

    Example:
        client = connect_mqtt("127.0.0.1", 1883)
        client.publish("h2seas/nose/sp30/pm10_ugm3", "14.937")
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    # Register the callbacks before connecting, so paho can call them
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish
    client.connect(host, port)

    # loop_start() runs paho's network loop in the background: it sends
    # queued messages and answers the broker's keep-alive pings for us
    client.loop_start()
    return client


def main():
    parser = argparse.ArgumentParser(description="Receive NMEA sentences from the converter over TCP")
    parser.add_argument("--host", default="127.0.0.1", help="converter IP address")
    parser.add_argument("--port", type=int, default=10110, help="converter TCP port")
    parser.add_argument("--topics", default="nmea_topics.json", help="NMEA-to-topic mapping")
    parser.add_argument("--mqtt-host", default="127.0.0.1", help="MQTT broker address")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    with open(args.topics) as f:
        topic_dict = json.load(f)

    client = connect_mqtt(args.mqtt_host, args.mqtt_port)

    # Read sentences until the converter closes the connection (or Ctrl+C)
    for sentence in read_nmea_sentences(args.host, args.port):
        for topic, value in nmea2mqtt(sentence, topic_dict):
            client.publish(topic, value, qos=1)
            print(topic, value)


if __name__ == "__main__":
    main()
