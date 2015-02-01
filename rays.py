#! /usr/bin/env python3
#
# rays - python implementation of flin by tehn
# see http://monome.org/docs/app:parc for more information
# about the original app
#

import random
import asyncio
import monome

import clocks
import synths

scale = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 73]

def cancel_task(task):
    if task:
        task.cancel()

class Flin(monome.Monome):
    def __init__(self, clock, synth, channel, speed=6):
        super().__init__('/flin.py')
        self.clock = clock
        self.synth = synth
        self.channel = channel
        self.speed = speed

    def ready(self):
        self.led_all(0)
        self.play_tasks = [None for x in range(self.width)]
        self.col_presses = [-1 for x in range(self.width)]
        self.play_row = [0 for x in range(self.width)]

    def disconnect(self):
        self.led_all(0)
        for t in self.play_tasks:
            cancel_task(t)

    def grid_key(self, x, y, s):
        if y == (self.height - 1):
            cancel_task(self.play_tasks[x])
            return
        else:
            if s == 1:
                if self.col_presses[x] == -1:
                    # first button pressed, cancel player and store speed value
                    cancel_task(self.play_tasks[x])
                    self.col_presses[x] = y
                else:
                    # second button pressed, reset value and play
                    speed = self.col_presses[x] + 1
                    dur = y + 1
                    self.col_presses[x] = -1

                    cancel_task(self.play_tasks[x])
                    self.play_tasks[x] = asyncio.async(self.play(x, speed, dur))
                self.led_set(x, y, s) # light the led on press
            else:
                if self.col_presses[x] != -1:
                    # single button raised, so just use value
                    speed = self.col_presses[x] + 1
                    dur = 1
                    self.col_presses[x] = -1

                    cancel_task(self.play_tasks[x])
                    self.play_tasks[x] = asyncio.async(self.play(x, speed, dur))
                else:
                    # one button raised, ignore rest
                    self.col_presses[x] = -1
                    pass

    # collect notes and send them to the synth
    def pipe(self):
        notes = set()
        for x in range(self.width):
            if self.play_row[x] == 1:
                notes.add(scale[x])
        self.synth.batch(self.channel, notes)

    @asyncio.coroutine
    def play(self, x, speed, dur):
        try:
            # use clock's q=1 here and below so we have even intervals instead of waiting for a full cycle
            init_pos = yield from self.clock.sync()
            new_pos = init_pos
            while True:
                led_pos = (new_pos - init_pos) // (self.speed * speed) % (self.height * 2)
                col = [4] * self.height

                # set column values
                for i in range(led_pos, led_pos - dur, -1):
                    if i in range(0, self.height):
                        col[i] = 15

                # light bottom-most led so we know the column is active
                if led_pos >= self.height:
                    col[-1] = 15

                self.play_row[x] = 1 if col[0] > 4 else 0
                self.pipe()

                self.led_level_col(x, 0, col)

                # sync
                for i in range(self.speed * speed):
                    new_pos = yield from self.clock.sync()

        except asyncio.CancelledError:
            self.play_row[x] = 0
            self.pipe()
            self.led_col(x, 0, [0] * self.height)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # create clock
    #coro = loop.create_datagram_endpoint(clocks.FooClock, local_addr=('127.0.0.1', 9000))
    #transport, clock = loop.run_until_complete(coro)
    clock = clocks.InaccurateTempoClock(100)

    # create synth
    coro = loop.create_datagram_endpoint(synths.Renoise, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', 8001))
    transport, renoise = loop.run_until_complete(coro)

    coro = monome.create_serialosc_connection(lambda: Flin(clock, renoise, 0))
    serialosc = loop.run_until_complete(coro)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        for apps in serialosc.app_instances.values():
            for app in apps:
                app.disconnect()
        print('kthxbye')
