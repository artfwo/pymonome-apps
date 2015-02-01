#! /usr/bin/env python

import liblo
target = liblo.Address(9000)

from mididings import *

config(client_name='midi2fclk')

ticks = 0
send = False

def midi2osc(ev):
    global ticks, send
    if ev.type == SYSRT_CLOCK:
        if send:
            liblo.send(target, "/bang", ticks)
            ticks += 1
    elif ev.type == SYSRT_START:
        print('>> starting')
        liblo.send(target, "/start", ticks)
        send = True
        ticks = 0
    elif ev.type == SYSRT_STOP:
        print('>> stopping @' + str(ticks))
        send = False
    return None

run(Process(midi2osc))
