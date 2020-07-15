#! /usr/bin/env python3
#
# rove_bridge by artfwo - a proxy for monome apps that have
# static i/o ports such as rove and duplex
#

import asyncio
import aiosc
import itertools
import monome

class GridGate(aiosc.OSCProtocol):
    def __init__(self, prefix, bridge):
        self.prefix = prefix.strip('/')
        self.bridge = bridge

        super().__init__(handlers={
            '/{}/grid/led/set'.format(self.prefix):
                lambda addr, path, x, y, s:
                    # int(), because renoise sends float
                    self.bridge.grid.led_set(int(x), int(y), int(s)),
            '/{}/grid/led/all'.format(self.prefix):
                lambda addr, path, s:
                    self.bridge.grid.led_all(s),
            '/{}/grid/led/map'.format(self.prefix):
                lambda addr, path, x_offset, y_offset, *s:
                    self.bridge.grid.led_map(x_offset, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/row'.format(self.prefix):
                lambda addr, path, x_offset, y, *s:
                    self.bridge.grid.led_row(x_offset, y, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/col'.format(self.prefix):
                lambda addr, path, x, y_offset, *s:
                    self.bridge.grid.led_col(x, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/intensity'.format(self.prefix):
                lambda addr, path, i:
                    self.bridge.grid.led_intensity(i),
            '/{}/tilt/set'.format(self.prefix):
                lambda addr, path, n, s:
                    self.bridge.grid.tilt_set(n, s),
        })

    def grid_key(self, x, y, s):
        self.send('/{}/grid/key'.format(self.prefix), x, y, s, addr=(self.bridge._app_host, self.bridge._app_port))

class GridBridge(monome.GridApp):
    def __init__(self, bridge_host='127.0.0.1', bridge_port=8080, app_host='127.0.0.1', app_port=8000, app_prefix='/monome', loop=None):
        super().__init__()

        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop

        self._bridge_host = bridge_host
        self._bridge_port = bridge_port

        self._app_host = app_host
        self._app_port = app_port
        self._app_prefix = app_prefix

        self._gate = None

    def on_grid_ready(self):
        asyncio.ensure_future(self.init_gate())

    def on_grid_disconnect(self):
        print('{} disconnected'.format(self.grid.id))
        self.gate.transport.close()

    def on_grid_key(self, x, y, s):
        self.gate.grid_key(x, y, s)

    async def init_gate(self):
        # there is no remote_addr=(self._app_host, self._app_port)
        # because some endpoint implementations (oscP5) are pretty careless
        # about their source ports
        transport, protocol = await self._loop.create_datagram_endpoint(
            lambda: GridGate(self._app_prefix, self),
            local_addr=(self._bridge_host, self._bridge_port),
        )
        self.gate = protocol

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    device_map = {
        'm0001754': GridBridge(bridge_port=8080, app_port=8000, app_prefix='/monome')
    }

    def serialosc_device_added(id, type, port):
        if id in device_map:
            bridge_app = device_map[id]
            print('setting up {} for {}'.format(bridge_app.__class__.__name__, id))
            asyncio.ensure_future(bridge_app.grid.connect('127.0.0.1', port))
        else:
            print('no bridge configured for {}'.format(id))

    serialosc = monome.SerialOsc()
    serialosc.device_added_event.add_handler(serialosc_device_added)

    loop.run_until_complete(serialosc.connect())
    loop.run_forever()
