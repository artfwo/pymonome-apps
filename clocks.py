import asyncio
import aiosc
import time
import collections

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
