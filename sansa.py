#! /usr/bin/env python3
#
# sansa - python implementation of parc by tehn
# see http://monome.org/docs/app:parc for more information
# about the original app
#

import asyncio
import itertools
import random
import monome

import clocks
import synths

EDIT_NOTE = 0
EDIT_SUB = 1
EDIT_VEL = 2
EDIT_LINE = 3

@asyncio.coroutine
def blink(page, x, y, page_active):
    # blink led (bypassing page buffering) as long as page_active returns True
    if page_active():
        page.manager.led_level_set(x, y, 0 if page.buffer.levels[y][x] > 0 else 15)

        yield from asyncio.sleep(1/25)

        if page_active():
            page.manager.led_level_set(x, y, page.buffer.levels[y][x])

class ParcScene:
    def __init__(self, filename=None):
        self.sub = [1, 2, 3, 4, 5, 6, 7, 19, 9, 20, 11, 12, 14, 16, 32]
        # 4/ 2/ 1/ /2 /4 /8 /16 /32 6/ 3/ 1/ /3 /6 /12 /24 /48
        self.time = [384, 192,96,48, 24, 12, 6, 3, 576, 288, 96, 32, 16, 8, 4, 2]

        self.notes = [
            [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72],
            [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72],
            [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72],
            [36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50],
        ]

        self.vel_ranges = [(0, 127), (0, 127), (0, 127), (0, 127)]
        self.cc_ranges = [(0, 127), (0, 127), (0, 127), (0, 127)]

        self.midi_channels = [0, 1, 2, 3]
        self.midi_cc = [1, 2, 3, 4]

        note_data  = []
        sub_data = []
        vel_data = []
        line_data = []

        for i in range(4):
            note_data.append([[0 for col in range(16)] for row in range(15)])
            sub_data.append([[0 for col in range(16)] for row in range(15)])
            vel_data.append([[0 for col in range(16)] for row in range(15)])
            line_data.append([[0 for col in range(16)] for row in range(15)])

        self.data = [note_data, sub_data, vel_data, line_data]

    def load(self, filename):
        pass

    def save(self, filename):
        pass

class GlobalView(monome.Page):
    def ready(self):
        super().ready()

        self.presses_range1 = [set() for i in range(4)]
        self.presses_range2 = [set() for i in range(4)]

    def grid_key(self, x, y, s):
        if y < 4:
            # range rows
            if s == 1:
                self.presses_range1[y].add(x)
                self.presses_range2[y].add(x)
            else:
                self.presses_range1[y].remove(x) # TODO: handle KeyError
                if len(self.presses_range1[y]) == 0:
                    if len(self.presses_range2[y]) > 1:
                        # double press, set range
                        self.manager.ranges[y] = (min(self.presses_range2[y]), max(self.presses_range2[y]) + 1)
                    else:
                        # single press, set position
                        if x in range(*self.manager.ranges[y]):
                            self.manager.positions[y - 4] = x
                    self.presses_range2[y].clear()
                    self.refresh()
        else:
            # position rows
            if s == 1:
                self.manager.speeds[y - 4] = x
                self.refresh()

    def refresh(self):
        for y in range(4):
            range_row = [1 if i in range(*self.manager.ranges[y]) else 0 for i in range(self.width)]
            self.led_row(0, y, range_row)

        for y in range(4):
            speed_row = [0 for i in range(self.width)]
            speed_row[self.manager.speeds[y]] = 1
            self.led_row(0, y+4, speed_row)

    def disconnect(self):
        # stub to keep manager happy
        pass

class EditView(monome.Page):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = 0
        self.mode = 0

    def ready(self):
        super().ready()

    def grid_key(self, x, y, s):
        if y == 0 and s == 1:
            if x < 4:
                self.channel = x
                self.refresh()
            elif x < 8:
                self.mode = x - 4
                self.refresh()
        elif s == 1:
            data = self.manager.scene.data[self.mode][self.channel]
            data[y - 1][x] ^= 1
            self.led_set(x, y, data[y - 1][x])

    def refresh(self):
        data = self.manager.scene.data[self.mode][self.channel]

        top_row = [0] * self.width
        top_row[self.channel] = 1
        top_row[self.mode + 4] = 1
        self.led_row(0, 0, top_row)

        for r, row in enumerate(data):
            self.led_row(0, r + 1, row)

    def disconnect(self):
        # stub to keep manager happy
        pass

class Parc(monome.SeqPageManager):
    def __init__(self, clock, synth):
        self.global_view = GlobalView(self)
        self.edit_view = EditView(self)

        super().__init__([
            self.global_view,
            self.edit_view,
        ], prefix='/parc.py')

        self.clock = clock
        self.synth = synth

        self.scene = ParcScene()
        self.play_tasks = []

    def ready(self):
        super().ready()

        self.ranges = [(0, self.width) for i in range(4)]
        self.speeds = [7 for i in range(4)]
        self.positions = [0 for i in range(4)]

        self.global_view.refresh()
        self.edit_view.refresh()

        for i in range(4):
            self.play_tasks.append(asyncio.async(self.play(i)))

    def disconnect(self):
        super().disconnect()

        for task in self.play_tasks:
            task.cancel()

        self.led_all(0)
        self.synth.panic()

    @asyncio.coroutine
    def play(self, channel):
        note_value = None
        sub_value = self.scene.sub[0]
        vel_value = self.scene.vel_ranges[channel][1]
        line_value = self.scene.cc_ranges[channel][0]

        # sync once to ensure further syncs are consistent across channels
        yield from self.clock.sync(self.scene.time[self.speeds[channel]])

        while True:
            pos = self.positions[channel]

            asyncio.async(blink(self.global_view, pos, channel, lambda: self.global_view.is_active()))

            note_col    = [row[pos] for row in self.scene.data[EDIT_NOTE][channel]]
            sub_col     = [row[pos] for row in self.scene.data[EDIT_SUB][channel]]
            vel_col     = [row[pos] for row in self.scene.data[EDIT_VEL][channel]]
            line_col    = [row[pos] for row in self.scene.data[EDIT_LINE][channel]]

            # =====================
            # sub
            # =====================
            sub_values = list(itertools.compress([0, 1, 2, 3, 4, 5, 6], sub_col))
            if sub_values:
                sub_index = random.choice(sub_values)
                sub_value = self.scene.sub[sub_index]

                # blink sub
                asyncio.async(blink(self.edit_view, pos, sub_index + 1,
                    lambda: self.edit_view.is_active() and \
                            self.edit_view.channel == channel and \
                            self.edit_view.mode == EDIT_SUB))

            beat_div = 60 / self.clock.bpm / 24 * self.scene.time[self.speeds[channel]]
            sub_div = beat_div / sub_value

            for i in range(sub_value):
                # =====================
                # line
                # =====================
                line_values = list(itertools.compress([0, 1, 2, 3, 4, 5, 6], line_col))
                if line_values:
                    line_index = random.choice(line_values)

                    line_min, line_max = self.scene.cc_ranges[channel]
                    line_div = (line_max - line_min) / self.height
                    line_value = int(line_max - (line_div * line_index))

                    # blink line
                    asyncio.async(blink(self.edit_view, pos, line_index + 1,
                        lambda: self.edit_view.is_active() and \
                                self.edit_view.channel == channel and \
                                self.edit_view.mode == EDIT_LINE))

                    self.synth.cc(channel, self.scene.midi_cc[channel], line_value)

                # =====================
                # vel
                # =====================
                vel_values = list(itertools.compress([0, 1, 2, 3, 4, 5, 6], vel_col))
                if vel_values:
                    vel_index = random.choice(vel_values)

                    vel_min, vel_max = self.scene.cc_ranges[channel]
                    vel_div = (vel_max - vel_min) / self.height
                    vel_value = int(vel_max - (vel_div * vel_index))

                    # blink vel
                    asyncio.async(blink(self.edit_view, pos, vel_index + 1,
                        lambda: self.edit_view.is_active() and \
                                self.edit_view.channel == channel and \
                                self.edit_view.mode == EDIT_VEL))

                # =====================
                # note
                # =====================
                note_values = list(itertools.compress([0, 1, 2, 3, 4, 5, 6], note_col))
                if note_values:
                    # note_off_previous note
                    if note_value is not None:
                        self.synth.note_off(channel, note_value)
                        note_value = None
                    note_index = random.choice(note_values)
                    note_value = self.scene.notes[channel][note_index]

                    # blink note
                    asyncio.async(blink(self.edit_view, pos, note_index + 1,
                        lambda: self.edit_view.is_active() and \
                                self.edit_view.channel == channel and \
                                self.edit_view.mode == EDIT_NOTE))

                    # blink in the top row
                    asyncio.async(blink(self.edit_view, channel, 0,
                        lambda: self.edit_view.is_active()))

                    self.synth.note_on(self.scene.midi_channels[channel], note_value, vel_value)
                else:
                    # note_off_previous note
                    if note_value is not None:
                        self.synth.note_off(self.scene.midi_channels[channel], note_value)
                        note_value = None

                # sleep for sub_div ms if we're still retriggering
                if i < sub_value - 1:
                    yield from asyncio.sleep(sub_div)

            # advance position
            self.positions[channel] += 1
            if self.positions[channel] not in range(*self.ranges[channel]):
                self.positions[channel] = self.ranges[channel][0]

            # sync manually, so we can catch speed changes in the middle of a sync
            tick = yield from self.clock.sync()
            while tick % self.scene.time[self.speeds[channel]] != 0:
                tick = yield from self.clock.sync()


@asyncio.coroutine
def cleanup():
    yield from asyncio.sleep(0.2)

if __name__ == '__main__':
    from concurrent.futures import ThreadPoolExecutor
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(100))

    # create clock
    #coro = loop.create_datagram_endpoint(clocks.FooClock, local_addr=('127.0.0.1', 9000))
    #transport, clock = loop.run_until_complete(coro)
    clock = clocks.InaccurateTempoClock(90)

    # create synth
    coro = loop.create_datagram_endpoint(synths.Renoise, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', 8001))
    transport, renoise = loop.run_until_complete(coro)

    coro = monome.create_serialosc_connection(lambda: Parc(clock, renoise))
    serialosc = loop.run_until_complete(coro)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        for apps in serialosc.app_instances.values():
            for app in apps:
                app.disconnect()
        loop.run_until_complete(cleanup())
        print('kthxbye')
