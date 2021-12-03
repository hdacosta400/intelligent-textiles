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

class Connector():
    '''
    Object to represent connector of wires
    '''
    def __init__(self, connector_points, bbox):
        self.connector_points = connector_points # all coords where wires need to route to 
        self.open_wire_idx = 0 # idx of next available wire
        self.bbox = bbox
        inkex.errormsg("num connectors:{}".format(len(self.connector_points)))
    def has_available_wires(self):
        return self.open_wire_idx <= len(self.connector_points) - 4 # every connector is 4 points
    def connect_wire(self):
        if self.has_available_wires():
            points = self.connector_points[self.open_wire_idx:self.open_wire_idx + 4]
            self.open_wire_idx += 2
            return points
        else:
            inkex.errormsg("connector has no more open connections. Decrease the number of wires!")
            return None

class CombineGrids(InkstitchExtension):
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        self.arg_parser.add_argument("--alignment")
        args, _ = self.arg_parser.parse_known_args()
        self.is_horizontal_connection = True if args.alignment == "1" else False
        inkex.errormsg(self.is_horizontal_connection)
        self.wires = []
        self.connector = None
    def cancel(self):
        self.cancelled = True
    
    
    def check_horizontal_wire_directions(self, num_left_wires, num_right_wires):
        '''
        Checks that the wires can be connected in such a way that union 
        goes in the SAME direction (so that they can be hooked up to connectors later)
        '''
        if num_left_wires < num_right_wires and num_left_wires % 2 == 0:
            return False 
        if num_right_wires < num_left_wires and num_right_wires % 2 == 1:
            return False 
        return True

    def connect_horizontally(self):
        rect1,rect2 = self.wires[0].bbox, self.wires[1].bbox
        left_wire = None 
        right_wire = None
        if rect1.left < rect2.left:
            left_wire, right_wire = self.wires
        else:
            right_wire, left_wire = self.wires
            
        self.union_wires(left_wire, right_wire, is_horizontal=True)
    
    def connect_vertically(self):
        rect1,rect2 = self.wires[0].bbox, self.wires[1].bbox
        top_wire = None 
        bottom_wire = None
        if rect1.top < rect2.top:
            top_wire, bottom_wire = self.wires
        else:
            bottom_wire, top_wire = self.wires
            
        self.union_wires(top_wire, bottom_wire, is_horizontal=False)


    def union_wires(self, min_wire, max_wire, is_horizontal):
        min_wire_points = min_wire.points
        max_wire_points = max_wire.points

        # determine how many points we have to scan over, scales by factor of 2 for every wire that gets joined to one another
        min_multiplier = min_wire.get_num_wire_joins(is_horizontal)
        max_multiplier = max_wire.get_num_wire_joins(is_horizontal)

        inkex.errormsg("mult:{}, {}".format(min_multiplier, max_multiplier))

        min_wire_idx = 2 * min_multiplier
        max_wire_idx = 0
        min_points = ['{},{}'.format(p.x,p.y) for p in min_wire_points[0: min_wire_idx]]
        union_wire_points = []
        union_wire_points.extend(min_points)

        while min_wire_idx != len(min_wire_points):
            # 4 * multiplier points constitutes a wrap around from one wire path to the next
            max_wire_splice_length = min(4 * max_multiplier, len(max_wire_points) - max_wire_idx)
            max_points = ['{},{}'.format(p.x,p.y) for p in max_wire_points[max_wire_idx: max_wire_idx + max_wire_splice_length]]
            union_wire_points.extend(max_points)
            max_wire_idx += max_wire_splice_length
            inkex.errormsg("max wire idx:{}".format(max_wire_idx))

            inkex.errormsg("min wire idx:{}".format(min_wire_idx))
            min_wire_splice_length = min(4 * min_multiplier, len(min_wire_points) - min_wire_idx)
            min_points = ['{},{}'.format(p.x,p.y) for p in min_wire_points[min_wire_idx: min_wire_idx + min_wire_splice_length]]
            union_wire_points.extend(min_points)
            min_wire_idx += min_wire_splice_length
            inkex.errormsg("min wire idx:{}".format(min_wire_idx))

        max_points = ['{},{}'.format(p.x,p.y) for p in max_wire_points[max_wire_idx: len(max_wire_points)]]
        inkex.errormsg("idx of right wire: {}:{}".format(max_wire_idx,len(max_wire_points)))
        union_wire_points.extend(max_points)
        # done unionizing the wires
        # remove old wires (.wire is used to access the actual svg element within the object)
        min_wire.wire.getparent().remove(min_wire.wire)
        max_wire.wire.getparent().remove(max_wire.wire)

        # add new combined one
        self.create_path(union_wire_points, is_horizontal)

    def create_path(self, points, is_horizontal):
        '''
        Creates a wire segment path given all of the points sequentially
        '''
        color = "red" if is_horizontal else "blue"
        path_str = ' '.join(points)
        path = inkex.Polyline(attrib={
        'id': "wire_segment",
        'style': "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
        'points': path_str,
        })
        self.svg.get_current_layer().append(path)

    def effect(self):
        connector_points = []
        connector_bbox = None
        for elem in self.svg.get_selected():
            # inkex.errormsg("things selected:{}".format(len(self.svg.get_selected())))
            inkex.errormsg("type of elem:{}".format(type(elem)))
            # have to separate shapes and wires here!
            if type(elem) == Polyline:
                # self.wires.append(elem)
                # self.wire_rectangles.append(elem.bounding_box())

                #V2
                wire = Wire(elem)
                self.wires.append(wire)

            # elif type(elem) == PathElement: #connector
            #     self.wire_rectangles.append(elem.bounding_box())
            #     connector_bbox = elem.bbox()
            #     points = self.get_points(elem)
            #     for p in points:
            #         connector_points.append(p)
        
        self.connector = Connector(connector_points, connector_bbox)

        if len(self.wires) != 2:
            inkex.errormsg(len(self.wires))
            inkex.errormsg("Please select only two wires to combine!")
            return
        if self.is_horizontal_connection:
            self.connect_horizontally()
        else:
            self.connect_vertically()

class Wire:
    #TODO: move this into a util class
    def __init__(self, wire):
        self.wire = wire
        self.points = [p for p in self.wire.path.end_points]
        self.bbox = self.wire.bounding_box()

    def get_num_wire_joins(self, is_horizontal):
        '''
        Determines how many wires were horizontally joined together to create the current wire object

        The default is 1
        '''
        point_counter = 1
        for i in range(len(self.points) - 1):
            p1 = self.points[i]
            p2 = self.points[i+1]
            inkex.errormsg("points:{},{}".format(p1,p2))
            if (is_horizontal and p1.x == p2.x) or (not is_horizontal and p1.y == p2.y):
                return point_counter // 2
            else:
                point_counter += 1
        # should never get here?
        return None
    '''
    Determine how many points of connection a wire has on each side (left right for horizontal case / top bottom for vertical case)
    '''
    def get_num_left_endpoints(self):
        left_side = self.bbox.left
        return sum([1 for p in self.points if p.x == left_side])

    def get_num_right_endpoints(self):
        right_side = self.bbox.right
        return sum([1 for p in self.points if p.x == right_side])

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    CombineGrids().run()