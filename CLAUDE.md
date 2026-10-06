# H2Seas-Starlink

Scientific prototype: sensor data (e-nose, vibration, audio) is sent as NMEA 0183
sentences over TCP (emulating an NMEA-to-Ethernet converter) and forwarded to MQTT. "ship" branch is for ship end (emulating and sensing sensor data), "roc" branch will be for shore end (receive, store and vizualize sensor data).

## Style
- Main point: prioritize learning over functional code. Never create more than one function at a time! Do not make major assumptions about the architecture. Explain new topics when they appear. You are an assistant, not an engineer!
- In some critical places, leave a To-Do section for the user to complete, prioratize parts that are important for the algorithm / mathematics or the foundational principles.
- If you notice errors in the human-written code, highlight it and explain why it is wrong and how to fix it, don't just fix it yourself in the background
- Clarity over robustness: no reconnect logic, retries or edge-case handling unless asked.
- Every function gets a short docstring explaining what it does (with an example if useful).
- Keep scripts small and readable; avoid threads, and extra options unless needed.

## Environment
- Windows, PowerShell. Run Python with `py` (Python 3.14), NOT `python`
  (`python` is the MSYS2 interpreter without pip or paho-mqtt).
- Run scripts from the `code/` folder; they use relative paths.

## Project files (code/)
- `csv_key_mqtt_topic.csv`: CSV column -> MQTT topic reference.
- NMEA format: `$PH2S,<sensor_id>,<hhmmss.ss>,<ddmmyy>,<values...>*<checksum>`