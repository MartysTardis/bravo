from twisted.trial import unittest
from twisted.internet import reactor
from twisted.internet.task import LoopingCall, deferLater

from bravo.blocks import items, blocks
from bravo.inventory import Slot, Inventory
from bravo.entity import Furnace as FurnaceTile
from bravo.inventory.windows import FurnaceWindow
from bravo.utilities.furnace import FurnaceProcess

class FakeFactory(object):
    def __init__(self):
        self.protocols = []

class FakeProtocol(object):
    def __init__(self):
        self.windows = []
        self.write_packet_calls = []
        
    def write_packet(self, *args, **kwargs):
        self.write_packet_calls.append((args, kwargs))

coords = 0, 0, 0, 0, 0 # bigx, smallx, bigz, smallz, y
coords2 = 0, 0, 0, 0, 1

class TestFurnaceProcessInternals(unittest.TestCase):

    def setUp(self):
        self.tile = FurnaceTile(0, 0, 0)
        self.factory = FakeFactory()
        self.process = FurnaceProcess(self.tile, coords)
        self.process.factory = self.factory
        
    def test_fuel_slot(self):
        # empty slot
        self.assertFalse(self.process.hasFuel)
        # non-fuel item
        self.tile.inventory.fuel[0] = Slot(blocks['rose'].slot, 0, 1)
        self.assertFalse(self.process.hasFuel)
        # fuel item 
        self.tile.inventory.fuel[0] = Slot(items['coal'].slot, 0, 1)
        self.assertTrue(self.process.hasFuel)
        
    def test_crafting_slot(self):
        # empty slots
        self.assertFalse(self.process.canCraft)
        # have no recipe
        self.tile.inventory.crafting[0] = Slot(blocks['rose'].slot, 0, 1)
        self.assertFalse(self.process.canCraft)
        # have recipe
        self.tile.inventory.crafting[0] = Slot(blocks['sand'].slot, 0, 1)
        self.assertTrue(self.process.canCraft)
        # crating/crafted mismatch
        self.tile.inventory.crafted[0] = Slot(blocks['rose'].slot, 0, 1)
        self.assertFalse(self.process.canCraft)
        # crating/crafted match
        self.tile.inventory.crafted[0] = Slot(blocks['glass'].slot, 0, 1)
        self.assertTrue(self.process.canCraft)
        # match but no space left
        self.tile.inventory.crafted[0] = Slot(blocks['glass'].slot, 0, 64)
        self.assertFalse(self.process.canCraft)
        # TODO: test unstackable items when they are defined

class TestFurnaceProcessWindowsUpdate(unittest.TestCase):

    def setUp(self):
        self.tile = FurnaceTile(0, 0, 0)
        self.tile2 = FurnaceTile(0, 1, 0)
        
        # no any windows
        self.protocol1 = FakeProtocol()
        # window with different coordinates
        self.protocol2 = FakeProtocol()
        self.protocol2.windows.append(FurnaceWindow(1, Inventory(),
            self.tile2.inventory, coords2))
        # windows with proper coodinates
        self.protocol3 = FakeProtocol()
        self.protocol3.windows.append(FurnaceWindow(2, Inventory(),
            self.tile.inventory, coords))
        
        self.factory = FakeFactory()
        self.factory.protocols = {
            1: self.protocol1,
            2: self.protocol2,
            3: self.protocol3
        }
        self.process = FurnaceProcess(self.tile, coords)
        self.process.factory = self.factory
        
    def test_slot_update(self):
        self.process.update_all_windows_slot(1, None)
        self.process.update_all_windows_slot(2, Slot(blocks['glass'].slot, 0, 13))
        self.assertEqual(self.protocol1.write_packet_calls, [])
        self.assertEqual(self.protocol2.write_packet_calls, [])
        self.assertEqual(len(self.protocol3.write_packet_calls), 2)
        self.assertEqual(self.protocol3.write_packet_calls[0],
            (('window-slot',), {'wid': 2, 'slot': 1, 'primary': -1}))
        self.assertEqual(self.protocol3.write_packet_calls[1],
            (('window-slot',), {'wid': 2, 'slot': 2, 'primary': 20, 'secondary': 0, 'count': 13}))
        
    def test_bar_update(self):
        self.process.update_all_windows_progress(0, 55)
        self.assertEqual(self.protocol1.write_packet_calls, [])
        self.assertEqual(self.protocol2.write_packet_calls, [])
        self.assertEqual(self.protocol3.write_packet_calls,
            [(('window-progress',), {'wid': 2, 'bar': 0, 'progress': 55})])

class TestFurnaceProcessCrafting(unittest.TestCase):

    def setUp(self):
        self.states = []
        def fake_on_off(state):
            self.states.append(state)
    
        self.tile = FurnaceTile(0, 0, 0)
        self.protocol = FakeProtocol()
        self.protocol.windows.append(FurnaceWindow(7, Inventory(),
            self.tile.inventory, coords))
        self.factory = FakeFactory()
        self.factory.protocols = {1: self.protocol}
        self.process = FurnaceProcess(self.tile, coords)
        self.process.factory = self.factory
        self.process.on_off = fake_on_off

    def tearDown(self):
        self.states = []
        self.protocol.write_packet_calls = []
        
    def test_glass_from_sand_on_wood(self):
        '''Craft 1 glass from 1 sand on 1 wood'''
        self.tile.inventory.fuel[0] = Slot(blocks['wood'].slot, 0, 1)
        self.tile.inventory.crafting[0] = Slot(blocks['sand'].slot, 0, 1)
        self.process.update()

        def done():
            self.assertTrue(self.states[0]) # it was started...
            self.assertFalse(self.states[-1]) # ...and stopped at the end
            self.assertEqual(self.tile.inventory.fuel[0], None)
            self.assertEqual(self.tile.inventory.crafting[0], None)
            self.assertEqual(self.tile.inventory.crafted[0], (blocks['glass'].slot, 0, 1))
            self.assertEqual(len(self.protocol.write_packet_calls), 64)
            headers = [header[0] for header, params in self.protocol.write_packet_calls]
            self.assertEqual(headers.count('window-slot'), 3)
            self.assertEqual(headers.count('window-progress'), 61)

        d = deferLater(reactor, 18, done) # wood burn time is 15s
        return d

    def test_glass_from_sand_on_wood(self):
        '''Craft 2 blocks of glass from 2 blocks of sand on 10 saplings'''
        self.tile.inventory.fuel[0] = Slot(blocks['sapling'].slot, 0, 10)
        self.tile.inventory.crafting[0] = Slot(blocks['sand'].slot, 0, 2)
        self.process.update()

        def done():
            self.assertTrue(self.states[0]) # it was started...
            self.assertFalse(self.states[-1]) # ...and stopped at the end
            # 2 sands take 20s to smelt, only 4 saplings needed
            self.assertEqual(self.tile.inventory.fuel[0], (blocks['sapling'].slot, 0, 6))
            self.assertEqual(self.tile.inventory.crafting[0], None)
            self.assertEqual(self.tile.inventory.crafted[0], (blocks['glass'].slot, 0, 2))
            self.assertEqual(len(self.protocol.write_packet_calls), 89)
            headers = [header[0] for header, params in self.protocol.write_packet_calls]
            # 4 updates for fuel slot (4 saplings burned)
            # 2 updates for crafting slot (2 sand blocks melted)
            # 2 updates for crafted slot (2 glass blocks crafted)
            self.assertEqual(headers.count('window-slot'), 8)
            self.assertEqual(headers.count('window-progress'), 81)

        d = deferLater(reactor, 23, done) # smelting time is ~20s
        return d
