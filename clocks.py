import asyncio
import aiosc
import time
import collections
import queue

try:
    import rtmidi2
except ImportError:
    pass

class RtMidiClock:
    def __init__(self, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop

        self.ticks = -1
        self.bpm = 120
        self._last_tick = time.time()
        self._tick_intervals = collections.deque(maxlen=96)

        self._tick_event = asyncio.Event()
        self._tick_queue = queue.Queue()

        self._rtmin = rtmidi2.MidiIn("RtMidiClock")
        self._rtmin.ignore_types(False, False, False)
        self._rtmin.callback = self._on_midi_message

        self.stopped = False
        self.start()

    def start(self):
        self._read_ticks_task = asyncio.async(self._read_ticks())
        self._rtmin.open_virtual_port("RtMidi In Sync")

    def stop(self):
        self._rtmin.close_port()
        self._read_ticks_task.cancel()

    def _on_midi_message(self, msg, time):
        msgtype = msg[0]
        if msgtype == 248:
            # tick
            self._tick_queue.put(248)
        elif msgtype == 250:
            # start
            self.ticks = -1
            self.stopped = False
        elif msgtype == 251:
            # continue
            self.stopped = False
        elif msgtype == 252:
            # stop
            self.stopped = True

    @asyncio.coroutine
    def _read_ticks(self):
        while True:
            b = yield from self._loop.run_in_executor(None, self._tick_queue.get, True, 0.250)
            if b is not None and not self.stopped:
                self.ticks += 1

                # update bpm
                current_tick = time.time()
                self._tick_intervals.append(current_tick - self._last_tick)
                self.bpm = 1 / (sum(self._tick_intervals) / len(self._tick_intervals)) / 24 * 60
                self._last_tick = current_tick

                self._tick_event.set()
                self._tick_event.clear()

    @asyncio.coroutine
    def sync(self, q=1):
        yield from self._tick_event.wait()
        while self.ticks % q != 0:
            yield from self._tick_event.wait()
        return self.ticks


class FooClock(aiosc.OSCProtocol):
    def __init__(self):
        super().__init__(handlers={
            '/bang': lambda addr, path, *args: self.__bang_handler(),
            '/start': lambda addr, path, *args: self.__start_handler(),
        })
        self.__bang_event = asyncio.Event()

        self.ticks = 0
        self.last_tick = time.time()
        self.bang_intervals = collections.deque(maxlen=96)
        self.bpm = 120

    def __bang_handler(self):
        self.ticks += 1

        current_tick = time.time()
        self.bang_intervals.append(current_tick - self.last_tick)
        self.bpm = 1 / (sum(self.bang_intervals) / len(self.bang_intervals)) / 24 * 60
        self.last_tick = current_tick

        self.__bang_event.set()
        self.__bang_event.clear()

    def __start_handler(self):
        self.ticks = 0

    @asyncio.coroutine
    def sync(self, q=1):
        yield from self.__bang_event.wait()
        while self.ticks % q != 0:
            yield from self.__bang_event.wait()
        return self.ticks

class InaccurateTempoClock:
    def __init__(self, tempo):
        self.tempo = tempo
        self.ticks = 0
        self.__bang_event = asyncio.Event()
        self.__ticktask = asyncio.async(self.__tick())
        self.bpm = tempo

    @asyncio.coroutine
    def __tick(self):
        while True:
            self.ticks += 1
            self.__bang_event.set()
            self.__bang_event.clear()
            yield from asyncio.sleep(60 / self.tempo / 4 / 24)

    @asyncio.coroutine
    def sync(self, q=1):
        yield from self.__bang_event.wait()
        while self.ticks % q != 0:
            yield from self.__bang_event.wait()
        return self.ticks
