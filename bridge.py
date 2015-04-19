#! /usr/bin/env python3
#
# rove_bridge by artfwo - a proxy for monome apps that have
# static i/o ports such as rove and duplex
#
# usage:
#   ./bridge.py <device-id> <listen-port> <app-port> <prefix>
# example:
#   ./bridge.py m0001754 8080 8000 /rove

import asyncio
import aiosc
import itertools
import monome

class Gate(aiosc.OSCProtocol):
    def __init__(self, prefix, bridge):
        self.prefix = prefix.strip('/')
        self.bridge = bridge

        super().__init__(handlers={
            '/{}/grid/led/set'.format(self.prefix):
                lambda addr, path, x, y, s:
                    # TODO: int(), because renoise sends float
                    self.bridge.led_set(int(x), int(y), int(s)),
            '/{}/grid/led/all'.format(self.prefix):
                lambda addr, path, s:
                    self.bridge.led_all(s),
            '/{}/grid/led/map'.format(self.prefix):
                lambda addr, path, x_offset, y_offset, *s:
                    self.bridge.led_map(x_offset, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/row'.format(self.prefix):
                lambda addr, path, x_offset, y, *s:
                    self.bridge.led_row(x_offset, y, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/col'.format(self.prefix):
                lambda addr, path, x, y_offset, *s:
                    self.bridge.led_col(x, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/intensity'.format(self.prefix):
                lambda addr, path, i:
                    self.bridge.led_intensity(i),
            '/{}/tilt/set'.format(self.prefix):
                lambda addr, path, n, s:
                    self.bridge.tilt_set(n, s),
        })

    def grid_key(self, x, y, s):
        self.send('/{}/grid/key'.format(self.prefix), x, y, s, addr=(self.bridge.app_host, self.bridge.app_port))

class Bridge(monome.Monome):
    def __init__(self, bridge_host='127.0.0.1', bridge_port=8080, app_host='127.0.0.1', app_port=8000, app_prefix='/monome', loop=None):
        super().__init__('/bridge')
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

        self.bridge_host = bridge_host
        self.bridge_port = bridge_port

        self.app_host = app_host
        self.app_port = app_port
        self.app_prefix = app_prefix

    def ready(self):
        asyncio.async(self.init_gate())

    @asyncio.coroutine
    def init_gate(self):
        # there is no remote_addr=(self.app_host, self.app_port)
        # because some endpoint implementations (oscP5) are pretty careless
        # about their source ports
        transport, protocol = yield from self.loop.create_datagram_endpoint(
            lambda: Gate(self.app_prefix, self),
            local_addr=(self.bridge_host, self.bridge_port),
        )
        self.gate = protocol

    def grid_key(self, x, y, s):
        self.gate.grid_key(x, y, s)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    coro = monome.create_serialosc_connection({
        '*': lambda: Bridge(bridge_port=8080, app_port=8000, app_prefix='/rove'),
    }, loop=loop)
    loop.run_until_complete(coro)
    loop.run_forever()
