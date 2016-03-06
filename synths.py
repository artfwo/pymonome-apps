import itertools
import aiosc
import random
import struct

def pack_midi(message, channel, data1, data2):
    # typical music software counts midi channels from 1 to 16, and so do we
    channel = channel - 1
    return ((data2 & 127) << 16) | ((data1 & 127) << 8) | ((message & 15) << 4) | (channel & 15)

class Synth(aiosc.OSCProtocol):
    def __init__(self):
        self.batches = {}

    def note_on(self, channel, note, velocity):
        pass

    def note_off(self, channel, note):
        pass

    def cc(self, channel, controller, value):
        pass

    def panic(self):
        pass

    def batch(self, channel, batch):
        old_notes = self.batches.get(channel, set())
        note_offs = old_notes.difference(batch)
        note_ons = batch.difference(old_notes)
        self.batches[channel] = batch.copy()

        for n in note_ons:
            self.note_on(channel, n, random.randint(64, 127))

        for n in note_offs:
            self.note_off(channel, n)

class Renoise(Synth):
    def __init__(self):
        super().__init__()

    def note_on(self, channel, note, velocity):
        midi = pack_midi(0b1001, channel, note, velocity)
        self.send('/renoise/trigger/midi', midi)

    def note_off(self, channel, note):
        midi = pack_midi(0b1000, channel, note, 0)
        self.send('/renoise/trigger/midi', midi)

    def cc(self, channel, controller, value):
        midi = pack_midi(0b1011, channel, controller, value)
        self.send('/renoise/trigger/midi', midi)

    def program_change(self, channel, program):
        midi = pack_midi(0b1100, channel, program, 0)
        self.send('/renoise/trigger/midi', midi)

    def panic(self):
        self.send('/renoise/transport/panic')
