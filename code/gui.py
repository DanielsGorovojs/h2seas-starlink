import csv
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk
from ttkthemes import ThemedStyle
import matplotlib
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import paho.mqtt.client as mqtt
# Reuse the parsing and saving functions from mqtt_subscriber.py (same folder)
from mqtt_subscriber import json2tuple, save_point
import numpy as np

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
POLL_MS = 100  # how often tkinter lets paho check for new messages
MAX_POINTS = 30  # in "follow" mode, a plot window shows the newest this many points

TOPIC_KEY_FILE = "csv_key_mqtt_topic.csv"  # CSV column name -> MQTT topic
THEME = "equilux"  # any ttkthemes theme name, e.g. "arc", "breeze", "equilux"
PLOT_BACKGROUND = "#d0d0d0"  # inside of the plot axes: light grey, easier to read than the dark theme
PLOT_GRID = "#8c8c8c"        # grid lines: darker grey, visible on PLOT_BACKGROUND

# All open plot windows, one per topic:
#   topic -> {"window": ..., "ax": ..., "canvas": ..., "unit": ..., "follow": ..., "times": [...], "values": [...]}
plots = {}


def apply_theme(root, theme):
    """Apply a ttkthemes theme to the GUI and give matplotlib plots matching colours.

    Must be called once, right after creating root and before any window or plot
    is created, because the colours only apply to things created afterwards.

    Example:
        apply_theme(root, "equilux")  # dark grey: background #464646, text #a6a6a6
    """
    style = ThemedStyle(root)
    style.set_theme(theme)

    # Read the theme's own colours, so everything else can match it
    background = style.lookup("TFrame", "background")
    text = style.lookup("TLabel", "foreground")

    # Classic tk widgets (Toplevel windows, matplotlib's toolbar) ignore ttk themes.
    # option_add sets the default colours for every such widget created from now on
    # ("*" = any widget). The toolbar then also switches to its light icons by itself
    root.configure(background=background)
    root.option_add("*Background", background)
    root.option_add("*Foreground", text)

    # rcParams = matplotlib's global default settings, used by every new Figure
    matplotlib.rcParams.update({
        "figure.facecolor": background,  # area around the plot
        "axes.facecolor": PLOT_BACKGROUND,  # area inside the axes
        "axes.edgecolor": text,          # axes frame
        "axes.labelcolor": text,
        "axes.titlecolor": text,
        "xtick.color": text,
        "ytick.color": text,
        "grid.color": PLOT_GRID,
    })


def load_topics(path):
    """Read the topic key file and return a dict of MQTT topic -> unit.

    The file has no header; each row is: CSV column name, MQTT topic, unit.
    An empty unit means the quantity has no unit.

    Example:
        load_topics("csv_key_mqtt_topic.csv")
        -> {"h2seas/nose/bme688/pressure_hpa": "hPa", "h2seas/nose/ens160/aqi_uba": "", ...}
    """
    # encoding="utf-8": the file contains ° and µ; Windows would otherwise read it as cp1252
    with open(path, newline="", encoding="utf-8") as f:
        # csv.reader gives each row as a list of strings: ["BME688_Pressure_hPa", "h2seas/...", "hPa"]
        return {row[1]: row[2] for row in csv.reader(f)}


def format_axes(ax, topic, unit):
    """Set title, axis labels (with unit), grid and UTC time format on a plot.

    Called when a window opens and after every ax.clear(), because clear()
    also removes all of this formatting.

    Example:
        format_axes(ax, "h2seas/nose/bme688/temperature_c", "°C")
        -> title "h2seas/nose/bme688/temperature_c", y-axis "temperature_c [°C]",
           x-axis "time (UTC)" with HH:MM tick labels, dotted grid
    """
    ax.set_title(topic)
    quantity = topic.split("/")[-1]  # last part of the topic, e.g. "temperature_c"
    # Unitless quantities (empty unit) get no brackets
    ax.set_ylabel(f"{quantity} [{unit}]" if unit else quantity)
    ax.set_xlabel("time (UTC)")

    # Grid lines at every tick; dotted and faint so they don't hide the data
    ax.grid(True, linestyle=":", alpha=0.6)

    # Show x tick labels as clock time. This only works if the x values are datetime
    # objects (not Unix seconds); tz=timezone.utc makes it print UTC, not local time
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))


def open_topic_window(root, topic, unit):
    """Open a new window with an empty plot for one topic and register it in plots.

    If the topic already has a window, that window is brought to the front instead.

    Example:
        open_topic_window(root, "h2seas/nose/bme688/temperature_c", "°C")
    """
    if topic in plots:
        plots[topic]["window"].lift()  # lift() = bring the window to the front
        return

    # Toplevel = an extra window that belongs to the same program as root
    window = tk.Toplevel(root)
    window.title(topic)

    # Figure is matplotlib's drawing area; we use it instead of pyplot,
    # because pyplot would open its own windows outside of tkinter
    # layout="constrained" makes room for titles and labels so they are not cut off
    figure = Figure(figsize=(6, 3), layout="constrained")
    ax = figure.add_subplot()
    format_axes(ax, topic, unit)

    # FigureCanvasTkAgg turns the figure into a tkinter widget we can place in the window
    canvas = FigureCanvasTkAgg(figure, master=window)

    # matplotlib's standard toolbar (home, pan, zoom, save). pack_toolbar=False lets us
    # place it ourselves: bottom widgets are packed first so they keep their space
    # when the window is made small
    toolbar = NavigationToolbar2Tk(canvas, window, pack_toolbar=False)
    toolbar.pack(side="bottom", fill="x")

    # BooleanVar = a tkinter variable the checkbox reads and writes by itself;
    # follow.get() returns True/False wherever we need to know its state
    follow = tk.BooleanVar(value=True)
    ttk.Checkbutton(window, text=f"Follow latest {MAX_POINTS} points", variable=follow).pack(side="bottom", anchor="w")

    # fill="both", expand=True: the plot takes all remaining space and grows with the window
    canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    # Remember everything on_message needs to add points and redraw this window
    plots[topic] = {"window": window, "ax": ax, "canvas": canvas, "unit": unit, "follow": follow,
                    "times": [], "values": []}

    # When the user clicks the window's X, call close_topic_window instead of
    # just destroying the window, so plots stays in sync with what is on screen
    window.protocol("WM_DELETE_WINDOW", lambda: close_topic_window(topic))


def close_topic_window(topic):
    """Close a topic's plot window and forget it, so on_message stops drawing to it.

    tkinter calls this when the user clicks the window's X button.

    Example:
        close_topic_window("h2seas/nose/bme688/temperature_c")
    """
    plots[topic]["window"].destroy()
    del plots[topic]

    pass


def on_message(client, userdata, message):
    """Save every received data point to CSV, and plot it if its topic's window is open.

    paho calls this from client.loop() (inside poll_mqtt) for every message.

    Example payload on "h2seas/nose/bme688/temperature_c":
        {"time": 1790575560.0, "value": 21.4}
    """

    data = json2tuple(message.payload.decode())
    save_point(message.topic, data[0], data[1])
    if message.topic not in plots:
        return

    plot = plots[message.topic]
    plot["times"].append(datetime.fromtimestamp(data[0], timezone.utc))
    plot["values"].append(data[1])

    redraw(message.topic)


def redraw(topic):
    """Redraw a topic's plot with all its points, then choose what part is visible.

    Follow ON:  show the newest MAX_POINTS points, y-range fitted to just those.
    Follow OFF: keep whatever view the user has panned/zoomed to.

    Example:
        redraw("h2seas/nose/bme688/temperature_c")
    """
    plot = plots[topic]
    ax = plot["ax"]
    following = plot["follow"].get()

    # clear() would also reset the view, so remember the user's view first
    if not following:
        x_view = ax.get_xlim()
        y_view = ax.get_ylim()

    # clear() wipes the axes (formatting too), then we draw the whole line again
    ax.clear()
    format_axes(ax, topic, plot["unit"])
    ax.plot(plot["times"], plot["values"], marker="o")

    if following:
        # [-MAX_POINTS:] = slice of the last MAX_POINTS items (or all, if there are fewer)
        visible_times = plot["times"][-MAX_POINTS:]
        visible_values = plot["values"][-MAX_POINTS:]
        ax.set_xlim(visible_times[0], visible_times[-1])

        max_val = max(visible_values)
        min_val = min(visible_values)
        margin = (max_val - min_val)*0.1
        if margin == 0:
            margin = abs(np.mean(max_val))*0.05

        if margin == 0:
            margin = 0.05
        ax.set_ylim(min_val - margin, max_val + margin)

    else:
        ax.set_xlim(x_view)
        ax.set_ylim(y_view)

    # draw_idle() asks tkinter to repaint the canvas at its next free moment
    plot["canvas"].draw_idle()


def poll_mqtt(root, client):
    """Let paho handle waiting MQTT traffic, then schedule itself again.

    This is how tkinter and paho share one thread: tkinter's mainloop owns the
    program, and every POLL_MS milliseconds it calls this function, which gives
    paho a short moment to receive messages (and call client.on_message for each).

    Example:
        poll_mqtt(root, client)  # call once before root.mainloop(); it keeps itself going
    """
    client.loop(timeout=0)
    root.after(POLL_MS, poll_mqtt, root, client)


def build_topic_tree(tree, topics):
    """Fill a Treeview with topics, one branch per topic level (like folders).

    Every node's id is its full path, so a leaf's id is exactly its MQTT topic.

    Example:
        build_topic_tree(tree, ["h2seas/nose/bme688/temperature_c", "h2seas/nose/bme688/pressure_hpa"])
        -> h2seas
             nose
               bme688
                 temperature_c   (id "h2seas/nose/bme688/temperature_c")
                 pressure_hpa    (id "h2seas/nose/bme688/pressure_hpa")
    """
    # TODO (you): for every topic, make sure each level of its path exists in the tree.
    # For "h2seas/nose/bme688/temperature_c" the nodes to ensure are:
    #     id "h2seas"                            parent ""   (= tree top level)
    #     id "h2seas/nose"                       parent "h2seas"
    #     id "h2seas/nose/bme688"                parent "h2seas/nose"
    #     id "h2seas/nose/bme688/temperature_c"  parent "h2seas/nose/bme688"
    # Useful pieces:
    #     parts = topic.split("/")       -> ["h2seas", "nose", "bme688", "temperature_c"]
    #     "/".join(parts[:2])            -> "h2seas/nose"   (first 2 parts glued back)
    #     "/".join(parts[:0])            -> ""              (the top level)
    #     for i in range(len(parts)):    -> i = 0, 1, 2, 3
    #     tree.exists(node_id)           -> True if that node was already inserted
    #     tree.insert(parent_id, "end", iid=node_id, text=parts[i])
    #                                    -> adds a node under parent_id, shown as text
    # Think: why do we need tree.exists before inserting?
    for topic in topics:
        parts = topic.split("/")

        for i in range(len(parts)):
            node_id = "/".join(parts[:i+1])
            if not tree.exists(node_id):
                parent_id = "/".join(parts[:i])
                tree.insert(parent_id, "end", iid=node_id, text = parts[i])

    pass


def open_selected_topic(root, tree, topics):
    """Open a plot window for the topic selected in the tree, if it is a leaf.

    Branches (like "h2seas/nose/bme688") are not topics, so they are ignored;
    a double-click on them still expands/collapses them as usual.

    Example:
        open_selected_topic(root, tree, topics)  # selected "h2seas/nose/bme688/temperature_c"
        -> opens the temperature_c window
    """
    # focus() = id of the selected node; leaf ids are full topics, see build_topic_tree
    node_id = tree.focus()
    if node_id in topics:
        open_topic_window(root, node_id, topics[node_id])


def main():
    """Open the main window with the topic tree and an "Open" button.

    Clicking "Open" opens a plot window for the selected topic.

    Example:
        py gui.py
    """
    # Tk() creates the main (root) window; there is only one per program
    root = tk.Tk()
    root.title("H2Seas topics")
    apply_theme(root, THEME)

    topics = load_topics(TOPIC_KEY_FILE)

    # Treeview = expandable tree, like folders in a file explorer.
    # show="tree" hides the column header row; height = visible rows before scrolling
    tree = ttk.Treeview(root, show="tree", height=20)
    # list(topics) gives the dict's keys, i.e. just the topic names
    build_topic_tree(tree, list(topics))

    # Scrollbar linked both ways: the bar moves the tree, the tree updates the bar
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)

    # grid() places widgets in rows and columns of a table.
    # sticky="nsew" stretches a widget to all 4 sides (north, south, east, west) of its cell
    tree.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
    scrollbar.grid(row=0, column=1, sticky="ns", pady=5)
    # weight=1: when the main window is resized, row 0 / column 0 (the tree) get the extra space
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)

    # bind(event, function): call function whenever that event happens on the widget.
    # "<Double-1>" = double-click with mouse button 1 (left). tkinter passes an event
    # object (click position etc.); we don't need it, so the lambda just accepts and ignores it
    tree.bind("<Double-1>", lambda event: open_selected_topic(root, tree, topics))

    # command= is the function tkinter calls on click; the button does the same as a double-click
    open_button = ttk.Button(root, text="Open", command=lambda: open_selected_topic(root, tree, topics))
    open_button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 5))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    client.subscribe("h2seas/#", qos=1)

    # Start the polling "chain" once; poll_mqtt re-schedules itself from then on
    poll_mqtt(root, client)

    # mainloop() blocks here: it waits for clicks and redraws the window until it is closed
    root.mainloop()


if __name__ == "__main__":
    main()
