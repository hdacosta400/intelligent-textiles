from .base import InkstitchExtension
import sys
from base64 import b64decode
from argparse import ArgumentParser, REMAINDER

import appdirs
import inkex
from inkex import Line, Rectangle, Path, Polyline, PathElement
import wx
import wx.adv
from lxml import etree

from .create_grid import BoundingBoxMetadata

class CombineGridsFrame(wx.Frame):
    DEFAULT_FONT = "small_font"
    def __init__(self, shape1, shape2, svg, *args, **kwargs):
        if sys.platform.startswith('win32'):
            import locale
            locale.setlocale(locale.LC_ALL, "C")
            lc = wx.Locale()
            lc.Init(wx.LANGUAGE_DEFAULT)  
        pass

        
class CombineGrids(InkstitchExtension):
    COMMANDS = ["combine_grids"]
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        self.arg_parser.add_argument("--alignment")
        args, _ = self.arg_parser.parse_known_args()
        inkex.errormsg("args:{}".format(args.alignment))
        self.is_horizontal_connection = True if args.alignment == 1 else False
        self.wires = []
        self.wire_rectangles = []
    def cancel(self):
        self.cancelled = True
    def connect_horizontally(self):
        rect1, rect2 = self.wire_rectangles
        if not rect1.is_horizontally_aligned(rect2):
            inkex.errormsg("Unable to horizontally connect the two objects.")
            return
        leftmost_rectangle = None
        letmost_wire = None 
        other_rectangle = None
        other_wire = None
        if rect1.left < rect2.left:
            leftmost_rectangle = rect1
            letmost_wire = self.wires[0]
            other_rectangle = rect2
            other_wire = self.wires[1]
        else:
            leftmost_rectangle = rect2
            letmost_wire = self.wires[1]
            other_rectangle = rect1
            other_wire = self.wires[0]  
        
        
    def effect(self):
        for elem in self.svg.get_selected():
            # inkex.errormsg("things selected:{}".format(len(self.svg.get_selected())))
            inkex.errormsg("type of elem:{}".format(type(elem)))
            # have to separate shapes and wires here!
            wire_points = [p for p in elem.path.end_points]
            if type(elem) == Polyline:
                self.wires.append(wire_points)
                self.wire_rectangles.append(elem.bounding_box())
        if len(self.wires) != 2:
            inkex.errormsg("Please select only two wires to combine!")
            return
        if self.is_horizontal_connection:

                         

        
        
        
        
        


if __name__ == '__main__':
    inkex.errormsg(sys.argv[1:])
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    CombineGrids(args.horizontal_wires, args.vertical_wires).run()