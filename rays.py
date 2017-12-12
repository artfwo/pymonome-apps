#! /usr/bin/env python3
#
# rays - python implementation of flin by tehn
# see http://monome.org/docs/app:flin for more information
# about the original app
#

import random
import asyncio
import monome

import clocks
import synths

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

def cancel_task(task):
    if task:
        task.cancel()

class Flin(monome.App):
    def __init__(self, clock, synth, channel, clockdiv=6):
        super().__init__('/flin.py')
        self.clock = clock
        self.synth = synth
        self.channel = channel
        self.clockdiv = clockdiv

        self.scale = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 73]
        self.play_tasks = []

    def on_grid_ready(self):
        self.grid.led_all(0)
        self.play_tasks = [asyncio.async(asyncio.sleep(0)) for x in range(self.grid.width)]
        self.col_presses = [-1 for x in range(self.grid.width)]
        self.play_row = [0 for x in range(self.grid.width)]

    def on_grid_disconnect(self):
        self.grid.led_all(0)
        for t in self.play_tasks:
            cancel_task(t)

    def on_grid_key(self, x, y, s):
        if y == (self.grid.height - 1):
            self.play_tasks[x].cancel()
            return
        else:
            if s == 1:
                if self.col_presses[x] == -1:
                    # first button pressed, cancel player and store speed value
                    self.play_tasks[x].cancel()
                    self.col_presses[x] = y
                else:
                    # second button pressed, reset value and play
                    speed = self.col_presses[x] + 1
                    dur = y + 1
                    self.col_presses[x] = -1

                    self.play_tasks[x].cancel()
                    self.play_tasks[x] = asyncio.async(self.play(x, speed, dur))
                self.grid.led_set(x, y, s) # light the led on press
            else:
                if self.col_presses[x] != -1:
                    # single button raised, so just use value
                    speed = self.col_presses[x] + 1
                    dur = 1
                    self.col_presses[x] = -1

                    self.play_tasks[x].cancel()
                    self.play_tasks[x] = asyncio.async(self.play(x, speed, dur))
                else:
                    # one button raised, ignore rest
                    self.col_presses[x] = -1
                    pass

    # collect notes and send them to the synth
    def pipe(self):
        notes = set()
        for x in range(self.grid.width):
            if self.play_row[x] == 1:
                notes.add(self.scale[x])
        self.synth.batch(self.channel, notes)

    async def play(self, x, speed, dur):
        try:
            # use clock's q=1 here and below so we have even intervals instead of waiting for a full cycle
            init_pos = await self.clock.sync()
            new_pos = init_pos
            while True:
                led_pos = (new_pos - init_pos) // (self.clockdiv * speed) % (self.grid.height * 2)
                col = [4] * self.grid.height

                # set column values
                for i in range(led_pos, led_pos - dur, -1):
                    if i in range(0, self.grid.height):
                        col[i] = 15

                # light bottom-most led so we know the column is active
                if led_pos >= self.grid.height:
                    col[-1] = 15

                self.play_row[x] = 1 if col[0] > 4 else 0
                self.pipe()

                self.grid.led_level_col(x, 0, col)

                # sync
                for i in range(self.clockdiv * speed):
                    new_pos = await self.clock.sync()

        except asyncio.CancelledError:
            self.play_row[x] = 0
            self.pipe()
            self.grid.led_col(x, 0, [0] * self.grid.height)

    def quit(self):
        if self.grid:
            self.grid.led_all(0)
        for t in self.play_tasks:
            t.cancel()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    #clock = clocks.RtMidiClock()
    clock = clocks.InaccurateTempoClock(100)

    # create synth
    coro = loop.create_datagram_endpoint(synths.Renoise, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', 8001))
    transport, renoise = loop.run_until_complete(coro)

    rays = Flin(clock, renoise, 1)
    asyncio.async(monome.SerialOsc.create(loop=loop, autoconnect_app=rays))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        rays.quit()
        print('kthxbye')
