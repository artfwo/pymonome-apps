#! /usr/bin/env python3
#
# python port of meadowphysics by tehn
# https://monome.org/docs/meadowphysics/
#

import os
import subprocess
import platform
import asyncio
import random
import json
import pathlib

from enum import IntEnum

import monome
import aalink
import rtmidi

from rich.segment import Segment
from rich.style import Style

from textual.app import App
from textual.containers import Grid, ScrollableContainer, Vertical, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Switch, Label, Select, Markdown


HELP_TEXT = """
meadowphysics
=============

https://monome.org/docs/meadowphysics/

keyboard shortcuts:

```
r   - reset counters
s   - start/stop
^q  - quit
```
"""

COUNTERS = 8

L3 = 15
L2 = 9
L1 = 5
L0 = 3

SCALES = {
    "major":                [0, 2, 4, 5, 7, 9, 11, 12],
    "minor":                [0, 2, 3, 5, 7, 8, 10, 12],
    "pentatonic-major":     [0, 2, 4, 7, 9, 12, 14, 16],
    "pentatonic-minor":     [0, 3, 5, 7, 10, 12, 15, 17],
    "mixolydian":           [0, 2, 4, 5, 7, 9, 10, 12],
    "dorian":               [0, 2, 3, 5, 7, 9, 10, 12],
    "phrygian":             [0, 1, 3, 5, 7, 8, 10, 12],
    "lydian":               [0, 2, 4, 6, 7, 9, 11, 12],
    "locrian":              [0, 1, 3, 5, 6, 8, 10, 12],
    "whole":                [0, 2, 4, 6, 8, 10, 12, 14],
    "chromatic":            [0, 1, 2, 3, 4, 5, 6, 7, 8],
}

GLYPHS = [
    [0,   0,   0,   0,   0,   0,   0,   0],  # o
    [0,   24,  24,  126, 126, 24,  24,  0],  # +
    [0,   0,   0,   126, 126, 0,   0,   0],  # -
    [0,   96,  96,  126, 126, 96,  96,  0],  # >
    [0,   6,   6,   126, 126, 6,   6,   0],  # <
    [0,   102, 102, 24,  24,  102, 102, 0],  # * rnd
    [0,   120, 120, 102, 102, 30,  30,  0],  # <> up/down
    [0,   126, 126, 102, 102, 126, 126, 0],  # [] return
]


def midi_note_name(note):
    note_name = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"][note % 12]

    if len(note_name) < 2:
        note_name += "-"

    note_name += str(note // 12 - 1)
    return note_name


class Rule(IntEnum):
    NONE = 0
    INC = 1
    DEC = 2
    MAX = 3
    MIN = 4
    RAND = 5
    POLE = 6
    STOP = 7


class Event(IntEnum):
    NONE = 0
    TRIGGER = 1
    TOGGLE = 2


class Mode(IntEnum):
    MAIN = 0
    EDIT = 1
    RULE = 2


class State(IntEnum):
    STOPPED = 0
    READY = 1
    RUNNING = 2


class MidiOut:
    def __init__(self):
        self.midi_out = rtmidi.MidiOut(name="meadowphysics")
        # TODO: rtmidi stops sending events unless this line is here
        # self.midi_out.open_port(0)

        self.scale = "major"
        self.root = 60
        self.velocity = 101
        self.channel = 1

        self.notes = set()

    def pipe(self, output):
        new_notes = set()

        for i in range(COUNTERS):
            event = output[i]

            if event != Event.NONE:
                new_note = (self.channel, self.root + SCALES[self.scale][i])
                new_notes.add(new_note)

        note_offs = self.notes.difference(new_notes)
        note_ons = new_notes.difference(self.notes)

        self.notes = new_notes

        for channel, note in note_ons:
            self.note_on(channel, note, self.velocity)

        for channel, note in note_offs:
            self.note_off(channel, note)

    def note_on(self, channel, note, velocity):
        if self.midi_out.is_port_open():
            self.midi_out.send_message([0x90 | channel - 1, note, velocity])

    def note_off(self, channel, note):
        if self.midi_out.is_port_open():
            self.midi_out.send_message([0x80 | channel - 1, note, 0])

    def open(self, port):
        self.close()
        self.midi_out.open_port(port)

    def close(self):
        for channel, note in self.notes:
            self.note_off(channel, note)
        self.midi_out.close_port()


class Counter:
    def __init__(self, index):
        self.index = index
        self.value = 7
        self.start_value = 7
        self.range_min = 7
        self.range_max = 7
        self.speed = 0
        self.ticks = 0

        self.events = [Event.NONE for i in range(COUNTERS)]
        self.events[index] = Event.TRIGGER
        self.sync = [False for i in range(COUNTERS)]
        self.sync[index] = True

        self.rule_dest = index
        self.rule = Rule.INC

        self.state = State.STOPPED

    def start(self, delayed=False):
        self.value = self.start_value
        self.state = State.READY if delayed else State.RUNNING

    def stop(self):
        self.value = self.start_value
        self.state = State.STOPPED

    def decrement(self):
        if self.ticks == 0:
            self.value -= 1
            self.ticks = self.speed
        else:
            self.ticks -= 1

    def apply_rule(self, rule):
        if rule == Rule.INC:
            self.start_value += 1
            if self.start_value > self.range_max:
                self.start_value = self.range_min

        elif rule == Rule.DEC:
            self.start_value -= 1
            if self.start_value < self.range_min:
                self.start_value = self.range_max

        elif rule == Rule.MAX:
            self.start_value = self.range_max

        elif rule == Rule.MIN:
            self.start_value = self.range_min

        elif rule == Rule.RAND:
            self.start_value = random.randint(self.range_min, self.range_max)

        elif rule == Rule.POLE:
            distance_to_min = self.start_value - self.range_min
            distance_to_max = self.range_max - self.start_value
            self.start_value = self.range_min if distance_to_min > distance_to_max else self.range_max

        elif rule == Rule.STOP:
            self.stop()


class Meadowphysics:
    def __init__(self, clock, midi):
        self.clock = clock
        self.midi = midi

        self.clock_div = 16

        self.counters = [Counter(i) for i in range(COUNTERS)]
        self.counters[0].state = State.READY
        self.output = [Event.NONE for i in range(COUNTERS)]

        self.play_task = None
        self.updated = monome.Event()

    async def play(self):
        try:
            while True:
                await self.clock.sync(1 / self.clock_div)
                self.step()
        except asyncio.CancelledError:
            pass

    def start(self):
        self.play_task = asyncio.create_task(self.play())

    def stop(self):
        if self.play_task and not self.play_task.done():
            self.play_task.cancel()

        # TODO: send note_offs here?
        self.reset_counters()

    def step(self):
        for i in range(COUNTERS):
            if self.output[i] == Event.TRIGGER:
                self.output[i] = Event.NONE

        for i in range(COUNTERS):
            counter = self.counters[i]

            if counter.state == State.READY:
                counter.start()

            elif counter.state == State.RUNNING:
                counter.decrement()

                if counter.value == -1:
                    counter.stop()

                    rule_dest_counter = self.counters[counter.rule_dest]
                    rule_dest_counter.apply_rule(counter.rule)

                    for j in range(COUNTERS):
                        if counter.events[j] == Event.TRIGGER:
                            self.output[j] = Event.TRIGGER
                        elif counter.events[j] == Event.TOGGLE:
                            if self.output[j] != Event.TOGGLE:
                                self.output[j] = Event.TOGGLE
                            else:
                                self.output[j] = Event.NONE

                        if counter.sync[j]:
                            self.counters[j].start()

        self.midi.pipe(self.output)
        self.updated.dispatch()

    def start_counter(self, index):
        counter = self.counters[index]
        counter.start(delayed=True)

    def stop_counter(self, index):
        counter = self.counters[index]
        counter.stop()

        for i in range(COUNTERS):
            if counter.events[i] == Event.TOGGLE and self.output[i] == Event.TOGGLE:
                self.output[i] = Event.NONE

    def reset_counters(self):
        for counter in self.counters:
            counter.start_value = counter.range_min

            if counter.state == State.RUNNING:
                counter.start(delayed=True)

        self.updated.dispatch()


class GridInterface(monome.GridApp):
    def __init__(self, mp):
        super().__init__()
        self.mp = mp
        self.mp.updated.add_handler(self.on_mp_update)

        self.mode = Mode.MAIN
        self.edit_mode_counter = self.mp.counters[0]
        self.main_mode_key_count = [0 for i in range(COUNTERS)]

        self.buffer = monome.GridBuffer(16, COUNTERS)

    def on_mp_update(self):
        self.render()

    def on_grid_ready(self):
        self.render()

    def on_grid_key(self, x, y, s):
        if y >= COUNTERS:
            return

        if self.mode == Mode.MAIN:
            if s > 0:
                if x == 0:
                    self.mode = Mode.EDIT
                    self.edit_mode_counter = self.mp.counters[y]

                    for i in range(COUNTERS):
                        self.main_mode_key_count[i] = 0
                else:
                    if self.main_mode_key_count[y] == 0:
                        self.mp.counters[y].start_value = x
                        self.mp.counters[y].range_min = x
                        self.mp.counters[y].range_max = x
                        self.mp.counters[y].start(delayed=True)
                    elif self.main_mode_key_count[y] == 1:
                        if x < self.mp.counters[y].start_value:
                            self.mp.counters[y].range_min = x
                        if x > self.mp.counters[y].start_value:
                            self.mp.counters[y].range_max = x

                    self.main_mode_key_count[y] += 1
            else:
                if x > 0:
                    self.main_mode_key_count[y] -= 1
                    self.main_mode_key_count[y] = max(0, self.main_mode_key_count[y])

        elif self.mode == Mode.EDIT:
            if s > 0:
                if x == 1:
                    if self.edit_mode_counter == self.mp.counters[y]:
                        self.mode = Mode.RULE
                elif x == 2:
                    if self.mp.counters[y].state == State.RUNNING:
                        self.mp.stop_counter(y)
                    else:
                        self.mp.start_counter(y)
                elif x == 3:
                    self.edit_mode_counter.sync[y] = not self.edit_mode_counter.sync[y]
                elif x == 5:
                    self.edit_mode_counter.events[y] = Event.TOGGLE if self.edit_mode_counter.events[y] != Event.TOGGLE else Event.NONE
                elif x == 6:
                    self.edit_mode_counter.events[y] = Event.TRIGGER if self.edit_mode_counter.events[y] != Event.TRIGGER else Event.NONE
                elif x > 7:
                    self.mp.counters[y].speed = x - 8
                    self.mp.counters[y].ticks = self.mp.counters[y].speed
            else:
                if x == 0 and self.edit_mode_counter == self.mp.counters[y]:
                    self.mode = Mode.MAIN

        elif self.mode == Mode.RULE:
            if s > 0:
                if x > 6:
                    self.edit_mode_counter.rule = y
                elif x > 4:
                    self.edit_mode_counter.rule_dest = y
            else:
                if x == 1 and self.edit_mode_counter == self.mp.counters[y]:
                    self.mode = Mode.EDIT
                elif x == 0 and self.edit_mode_counter == self.mp.counters[y]:
                    self.mode = Mode.MAIN

        self.render()

    def render(self):
        if not self.grid.connected:
            return

        self.buffer.led_all(0)

        if self.mode == Mode.MAIN:
            for i in range(COUNTERS):
                counter = self.mp.counters[i]

                for j in range(counter.range_min, counter.range_max + 1):
                    self.buffer.led_level_set(j, i, L1)

                self.buffer.led_level_set(counter.start_value, i, L2)

                if counter.state == State.RUNNING:
                    self.buffer.led_level_set(counter.value, i, L3)

        elif self.mode == Mode.EDIT:
            for i in range(COUNTERS):
                counter = self.mp.counters[i]

                if counter.state == State.RUNNING:
                    self.buffer.led_level_set(counter.value, i, L1)
                    self.buffer.led_level_set(2, i, L0)

                self.buffer.led_level_set(3, i, L2 if self.edit_mode_counter.sync[i] else L1)

                event = self.edit_mode_counter.events[i]

                self.buffer.led_level_set(5, i, L2 if event == Event.TOGGLE else L1)
                self.buffer.led_level_set(6, i, L2 if event == Event.TRIGGER else L1)

                self.buffer.led_level_set(8 + counter.speed, i, L2)

            self.buffer.led_level_set(0, self.edit_mode_counter.index, L2)

        elif self.mode == Mode.RULE:
            for i in range(COUNTERS):
                counter = self.mp.counters[i]

                if counter.state == State.RUNNING:
                    self.buffer.led_level_set(counter.value, i, L1)

            for j in range(8, 16):
                self.buffer.led_level_set(j, self.edit_mode_counter.rule, L1)

            for i in range(8):
                glyph_row = GLYPHS[self.edit_mode_counter.rule][i]

                for j in range(8):
                    if glyph_row & (1 << j) != 0:
                        self.buffer.led_level_set(8 + j, i, L3)

            self.buffer.led_level_set(5, self.edit_mode_counter.rule_dest, L3)
            self.buffer.led_level_set(6, self.edit_mode_counter.rule_dest, L3)

            self.buffer.led_level_set(0, self.edit_mode_counter.index, L2)
            self.buffer.led_level_set(1, self.edit_mode_counter.index, L2)

        self.buffer.render(self.grid)

    def disconnect(self):
        if self.grid.connected:
            self.grid.led_all(0)
            self.grid.disconnect()


class SpinButton(Widget):
    value = reactive(0)
    can_focus = True

    DEFAULT_CSS = """
        SpinButton {
            layout: horizontal;
            min-height: 1;
            height: 1;
        }

        SpinButton:focus {
            tint: $primary 30%;
        }

        SpinButton:hover {
            tint: $accent 30%;
        }
    """

    class Changed(Message):
        def __init__(self, spin_button, value):
            self.spin_button = spin_button
            self.value = value
            super().__init__()

    def __init__(self, value=1, min_value=0, max_value=10, format=lambda v: "{}".format(v), **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.min_value = min_value
        self.max_value = max_value
        self.format = format

        self.label_width = max(len(format(v)) for v in range(min_value, max_value + 1))
        self.grabbed = False
        self.offset_y = -1
        self.styles.min_width = self.label_width + 4

    def set_value(self, new_value, post_message=True):
        self.value = self._clamp(round(new_value), self.min_value, self.max_value)

        if post_message:
            self.post_message(self.Changed(self, self.value))

    def render(self):
        label = self.format(self.value).ljust(self.size.width - 4)
        return "< {} >".format(label)

    def on_key(self, event):
        key = event.key

        if key == "left":
            self.set_value(self.value - 1)
        elif key == "right":
            self.set_value(self.value + 1)
        elif key == "up":
            self.set_value(self.value + 5)
        elif key == "down":
            self.set_value(self.value - 5)

    def on_click(self, event):
        if event.x == self.size.width - 1:
            self.set_value(self.value + 1)
        elif event.x == 0:
            self.set_value(self.value - 1)

    def on_mouse_down(self, event):
        self.capture_mouse()
        self.grabbed = True
        self.offset_y = event.y

    def on_mouse_up(self, event):
        self.release_mouse()
        self.grabbed = False

    def on_mouse_move(self, event):
        if self.grabbed:
            self.set_value(self.value + self.offset_y - event.y)
            self.offset_y = event.y

    def on_mouse_scroll_up(self, *args):
        self.set_value(self.value + 1)

    def on_mouse_scroll_down(self, *args):
        self.set_value(self.value - 1)

    def _clamp(self, value, min_value, max_value):
        return max(min_value, min(max_value, value))


class OptionsPanel(Widget):
    DEFAULT_CSS = """
        OptionsPanel {
            layout: grid;
            grid-size: 2;
            grid-rows: 1;
            grid-columns: 8 1fr;
            grid-gutter: 1;
        }

        OptionsPanel > SpinButton {
            width: 7;
        }

        OptionsPanel > Switch {
            height: 1;
            border: none;
            width: 4;
            padding: 0;
        }

        OptionsPanel > Switch:focus {
            height: 1;
            border: none;
            tint: $accent 30%;
        }

        OptionsPanel > Switch:hover {
            height: 1;
            border: none;
        }

        OptionsPanel > Button {
            background: $primary;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
            column-span: 2;
        }

        OptionsPanel > Button:hover {
            background: $primary-darken-2;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
        }

        OptionsPanel > Button.-active {
            background: $primary-darken-2;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
        }
    """


class Plotter(Widget):
    DEFAULT_CSS = """
        Plotter {
            min-height: 10;
            max-height: 10;
            height: 10;
            padding: 1 2;
        }
    """

    def __init__(self, mp, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.mp = mp
        self.mp.updated.add_handler(self.update_log)

        self.__log = [list() for i in range(COUNTERS)]

    def update_log(self):
        for i in range(COUNTERS):
            self.__log[i].append(self.mp.output[i])

            if len(self.__log[i]) > self.size.width:
                del self.__log[i][:len(self.__log[i]) - self.size.width]

        self.refresh()

    def render_line(self, y):
        if y >= COUNTERS:
            return Strip.blank(self.size.width)

        data = self.__log[y]
        segments = []

        style_nodata = Style.parse("blue")
        style_green = Style.parse("bright_green")
        style_white = Style.parse("bright_white")

        for i in range(len(data)):
            if data[i] == Event.TRIGGER or data[i] == Event.TOGGLE:
                if i == len(data) - 1:
                    segments.append(Segment("■", style_white))
                else:
                    segments.append(Segment("■", style_green))
            else:
                segments.append(Segment("▪", style_nodata))

        if len(segments) < self.size.width:
            segments.append(Segment("-" * (self.size.width - len(segments)), style_nodata))

        strip = Strip(segments)
        return strip


class HelpScreen(ModalScreen):
    CSS = """
        HelpScreen {
            align: center middle;
        }

        HelpScreen > Vertical {
            width: 66;
            height: 20;
            border: double lightgreen;
        }

        HelpScreen > Vertical > ScrollableContainer {
            margin: 1 0;
            width: 62;
        }

        HelpScreen > Vertical > Horizontal {
            height: 3;
            width: 64;
            align: center middle;
        }

        Button {
            margin: 1 2;
            width: 1fr;
            align: right middle;
        }

        Button {
            background: $primary;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
        }

        Button:hover {
            background: $primary-darken-2;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
        }

        Button.-active {
            background: $primary-darken-2;
            border: none;
            min-width: 10;
            width: 10;
            height: 1;
        }
    """

    def compose(self):
        with Vertical():
            yield ScrollableContainer(Markdown(HELP_TEXT.strip()))
            with Horizontal():
                yield Button("close", id="close")

    def on_mount(self):
        self.query_one("#close").focus()

    def on_button_pressed(self, event):
        if event.button.id == "close":
            self.app.pop_screen()

    def on_markdown_link_clicked(self, event):
        if platform.system() == "Windows":
            os.startfile(event.href)
        elif platform.system() == "Darwin":
            subprocess.call(("open", event.href))
        else:
            subprocess.call(("xdg-open", event.href))


class MeadowphysicsApp(App):
    TITLE = "meadowphysics"

    BINDINGS = [
        ("s", "start_stop", "start/stop"),
        ("r", "reset", "reset"),
        ("ctrl+o", "recall", "recall"),
        ("ctrl+s", "store", "store"),
        ("ctrl+q", "quit", "quit"),
    ]

    CSS = """
        Screen {
            align: center middle;
        }

        SelectCurrent {
            border: none;
            height: 1;
            # min-width: 15;
            padding: 0 1;
        }

        Select:focus > SelectCurrent,
        Select:focus > SelectCurrent > Static,
        Select.-expanded > SelectCurrent,
        Select.-expanded > SelectCurrent > Static {
            tint: $accent 30%;
        }

        SelectOverlay {
            min-width: 28;
        }

        #layout {
            grid-size: 3;
            grid-gutter: 1;
            grid-rows: auto;
            keyline: thin lightgreen;

            max-height: 24;
            max-width: 80;
        }

        #layout > OptionsPanel {
            padding: 1 2;
        }

        #plotter {
            column-span: 3;
        }
    """

    def __init__(self, mp, gi, link, midi):
        super().__init__()
        self.mp = mp
        self.gi = gi
        self.link = link
        self.midi = midi

        self.grids = []
        self.midi_ports = []

    def compose(self):
        with Grid(id="layout"):
            with OptionsPanel():
                yield Label("grid")
                yield Select([], prompt="none", id="grid-select")
                yield Label("midi")
                yield Select([], prompt="none", id="midi-select")
                yield Label("channel")
                yield SpinButton(value=self.midi.channel, min_value=1, max_value=16, id="channel")
                yield Label("bpm")
                yield SpinButton(value=int(self.link.tempo), min_value=20, max_value=999, id="bpm")
                yield Label("link")
                yield Switch(value=self.mp.clock.enabled, id="link")
            with OptionsPanel():
                yield Label("div")
                yield SpinButton(value=self.mp.clock_div, min_value=1, max_value=64, id="div")
                yield Label("root")
                yield SpinButton(value=self.midi.root, min_value=24, max_value=127, format=midi_note_name, id="root")
                yield Label("scale")
                yield Select([(scale, scale) for scale in SCALES.keys()], value=self.midi.scale, allow_blank=False, id="scale")
                yield Label("velocity")
                yield SpinButton(value=self.midi.velocity, min_value=0, max_value=127, id="velocity")
            with OptionsPanel():
                yield Label("preset")
                yield SpinButton(value=1, min_value=1, max_value=16, id="preset")
                yield Button("store", id="store")
                yield Button("recall", id="recall")
                yield Button("help", id="help")
            yield Plotter(mp=self.mp, id="plotter")

    def action_reset(self):
        self.mp.reset_counters()

    def action_start_stop(self):
        # TODO: mask mp.play_task.done() with a property
        if self.mp.play_task and not self.mp.play_task.done():
            self.mp.stop()
        else:
            self.mp.start()

    def action_recall(self):
        preset = self.query_one("#preset").value
        self.recall_preset(preset)

    def action_store(self):
        preset = self.query_one("#preset").value
        self.store_preset(preset)

    def update_recall_button_state(self):
        preset = self.query_one("#preset").value
        filename = "meadowphysics_preset{:0>2}.json".format(preset)
        self.query_one("#recall").disabled = not pathlib.Path(filename).exists()

    def store_preset(self, index):
        state = {
            "app": {
                "bpm": self.link.tempo,
            },
            "midi": {
                "channel": self.midi.channel,
                "scale": self.midi.scale,
                "root": self.midi.root,
                "velocity": self.midi.velocity,
            },
            "meadowphysics": {
                "clock_div": self.mp.clock_div,
                "counters": [],
            },
        }

        for counter in self.mp.counters:
            state["meadowphysics"]["counters"].append({
                "range_min": counter.range_min,
                "range_max": counter.range_max,
                "events": counter.events,
                "sync": counter.sync,
                "rule_dest": counter.rule_dest,
                "rule": counter.rule,
                "state": counter.state,
            })

        filename = "meadowphysics_preset{:0>2}.json".format(index)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(state, f)

        self.update_recall_button_state()

    def recall_preset(self, index):
        state = {}

        filename = "meadowphysics_preset{:0>2}.json".format(index)

        with open(filename, encoding="utf-8") as f:
            state = json.load(f)

        if not self.link.enabled or self.link.num_peers == 0:
            self.link.tempo = state["app"]["bpm"]
            self.query_one("#bpm").set_value(self.link.tempo)

        self.midi.channel = state["midi"]["channel"]
        self.query_one("#channel").set_value(self.midi.channel)

        self.midi.scale = state["midi"]["scale"]
        self.query_one("#scale").value = self.midi.scale

        self.midi.root = state["midi"]["root"]
        self.query_one("#root").set_value(self.midi.root)

        self.midi.velocity = state["midi"]["velocity"]
        self.query_one("#velocity").set_value(self.midi.velocity)

        self.mp.clock_div = state["meadowphysics"]["clock_div"]
        self.query_one("#div").set_value(self.mp.clock_div)

        for i, counter_state in enumerate(state["meadowphysics"]["counters"]):
            self.mp.counters[i].range_min = counter_state["range_min"]
            self.mp.counters[i].range_max = counter_state["range_max"]

            self.mp.counters[i].rule_dest = counter_state["rule_dest"]
            self.mp.counters[i].rule = Rule(counter_state["rule"])
            self.mp.counters[i].state = State(counter_state["state"])

            for j in range(COUNTERS):
                self.mp.counters[i].events[j] = Event(counter_state["events"][j])
                self.mp.counters[i].sync[j] = counter_state["sync"][j]

        self.mp.reset_counters()

    def on_button_pressed(self, event):
        if event.button.id == "store":
            preset = self.query_one("#preset").value
            self.store_preset(preset)
        elif event.button.id == "recall":
            preset = self.query_one("#preset").value
            self.recall_preset(preset)
        elif event.button.id == "help":
            self.push_screen(HelpScreen())

    def on_select_changed(self, event):
        if event.select.id == "grid-select":
            self.gi.disconnect()
            if event.select.value != Select.BLANK:
                asyncio.create_task(self.gi.grid.connect("127.0.0.1", event.select.value))
        elif event.select.id == "midi-select":
            if event.select.value == Select.BLANK:
                self.midi.close()
            else:
                self.midi.open(event.select.value)
        elif event.select.id == "scale":
            self.midi.scale = event.select.value

    def on_spin_button_changed(self, event):
        if event.spin_button.id == "channel":
            self.midi.channel = event.value
        elif event.spin_button.id == "bpm":
            self.link.tempo = event.value
        elif event.spin_button.id == "div":
            self.mp.clock_div = event.value
        elif event.spin_button.id == "root":
            self.midi.root = event.value
        elif event.spin_button.id == "velocity":
            self.midi.velocity = event.value
        elif event.spin_button.id == "preset":
            self.update_recall_button_state()

    def on_switch_changed(self, event):
        if event.switch.id == "link":
            self.link.enabled = event.switch.value

    def on_mount(self):
        self.update_recall_button_state()

        grid_select = self.query_one("#grid-select")
        midi_select = self.query_one("#midi-select")
        bpm = self.query_one("#bpm")

        def serialosc_device_added(id, type, port):
            self.grids.append(("{} ({})".format(type, id), port))

            if grid_select.value == Select.BLANK:
                grid_select.set_options(self.grids)
                grid_select.value = port
                asyncio.create_task(self.gi.grid.connect("127.0.0.1", port))
            else:
                current_grid_port = grid_select.value
                grid_select.set_options(self.grids)
                grid_select.value = current_grid_port

        def serialosc_device_removed(id, type, port):
            self.grids.remove(("{} ({})".format(type, id), port))

            if grid_select.value != port:
                current_grid_port = grid_select.value
                grid_select.set_options(self.grids)
                grid_select.value = current_grid_port
            else:
                grid_select.set_options(self.grids)

        serialosc = monome.SerialOsc()
        serialosc.device_added_event.add_handler(serialosc_device_added)
        serialosc.device_removed_event.add_handler(serialosc_device_removed)

        asyncio.create_task(serialosc.connect())

        def poll_midi_ports():
            midi_out = self.midi.midi_out
            new_ports = [(name, value) for value, name in enumerate(midi_out.get_ports())]

            if new_ports == self.midi_ports:
                return

            self.midi.close()
            self.midi_ports = new_ports
            midi_select.set_options(self.midi_ports)

        poll_midi_ports()

        self.set_interval(1, poll_midi_ports)
        self.set_interval(1, lambda: bpm.set_value(self.link.tempo, False))


async def main():
    link = aalink.Link(96, asyncio.get_running_loop())
    link.enabled = True

    midi = MidiOut()

    mp = Meadowphysics(link, midi)
    mp.start()

    gi = GridInterface(mp)
    ui = MeadowphysicsApp(mp, gi, link, midi)

    await ui.run_async()

    gi.disconnect()
    midi.close()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.run(main())
    except ImportError:
        asyncio.run(main())
