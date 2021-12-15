from networkx.algorithms.operators.binary import union
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
    def __init__(self, connector_pins, bbox):
        self.connector_pins = connector_pins
        self.points = [] # all coords where wires need to route to 
        for pin in self.connector_pins:
            points = [p for p in pin.path.end_points]
            for p in points:
                self.points.append(p)
        self.connected_wire = [False for _ in range(len(points))]
        self.open_wire_idx = 0 # idx of next available wire
        self.bbox = bbox
        self.num_pins = len(self.points) // 2
    def connect_pins(self):
        points = self.points[self.open_wire_idx : self.open_wire_idx + 4]
        self.open_wire_idx += 4
        return points

    def get_points(self):
        return self.points[self.open_wire_idx:]
    def get_num_wire_joins(self, is_horizontal=True):# overloaded method for wire connection
         return 1 


class CombineGrids(InkstitchExtension):
    COMMANDS = ["combine_grids"]
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

    def connect_wires_horizontally(self):
        rect1,rect2 = self.wires[0].bbox, self.wires[1].bbox
        left_wire = None 
        right_wire = None

        if rect1.left < rect2.left:
            left_wire, right_wire = self.wires
        else:
            right_wire, left_wire = self.wires
        
        union_wire_points = self.union_wires(left_wire, right_wire, is_horizontal=True)
        left_wire.wire.getparent().remove(left_wire.wire)
        right_wire.wire.getparent().remove(right_wire.wire)

        self.create_path(union_wire_points, is_horizontal=True)

    
    
    def connect_wires_vertically(self):
        rect1,rect2 = self.wires[0].bbox, self.wires[1].bbox
        top_wire = None 
        bottom_wire = None
        if rect1.top < rect2.top:
            top_wire, bottom_wire = self.wires
        else:
            bottom_wire, top_wire = self.wires
            
        union_wire_points = self.union_wires(top_wire, bottom_wire, is_horizontal=False)
        top_wire.wire.getparent().remove(top_wire.wire)
        bottom_wire.wire.getparent().remove(bottom_wire.wire)

        self.create_path(union_wire_points, is_horizontal=False)
    
    def horizontal_connector_union(self):
        sorted_wires = sorted(self.wires, key= lambda x: -x.bbox.top) # start at bottommost wire
        union_wire_connector_points = self.union_wires_to_connector(sorted_wires, True)
        self.create_path(union_wire_connector_points, is_horizontal=True)
        
        

            
    def vertical_connector_union(self):
        pass

    def union_wires_to_connector(self, wires, is_horizontal):
        inkex.errormsg("coming into union ")
        shape_arrangement = sorted(wires + [self.connector], key = lambda x: x.bbox.left)
        union_wire_points = []
        union_wire_sections = {} # map sections of unionized wire to each component wire multiplier

        flip = False # has any wire in union been flipped?
        inkex.errormsg("len wires:{}".format(len(wires)))
        for i in range(len(wires)):
            wire = wires[i]
            inkex.errormsg("num points:{}".format(len(wire.points)))
            points = None
            has_odd_wires = wire.get_num_endpoints() % 2 == 1
            points = wire.get_points() if not flip else wire.get_flipped_points(is_horizontal)
            if has_odd_wires:
                flip = not flip

        
            formatted_points = ['{},{}'.format(p.x,p.y) for p in points]
            union_wire_points.extend(formatted_points)
            # map last index where current wire ends
            union_wire_sections[len(union_wire_points)-1] = wire.get_num_wire_joins(is_horizontal)
            wire.wire.getparent().remove(wire.wire)
        
        # now we splice in connector to union wire
        connection_points = []
        wire_point_idx = 0

        def get_section_multiplier(current_index):
            for key in union_wire_sections.keys():
                if current_index <= key:
                    return union_wire_sections[key]
            return None # should never get here
        
        while wire_point_idx < len(union_wire_points):
            inkex.errormsg("curr idx:{}".format(wire_point_idx))
            wire_multiplier = get_section_multiplier(wire_point_idx)
            points = None
            splice_length = None
            if wire_point_idx == 0: #starting wire line'
                splice_length = 2 * wire_multiplier
            else:
                splice_length = min(4 * wire_multiplier, len(union_wire_points) - wire_point_idx)
            inkex.errormsg("sL:{}".format(splice_length))
            connection_points.extend(union_wire_points[wire_point_idx : wire_point_idx + splice_length])
            wire_point_idx += splice_length

            if wire_point_idx < len(union_wire_points):
                # add connector points unless we're at last point
                connector_pins = self.connector.connect_pins()
                inkex.errormsg("adding connector pins:{}".format(connector_pins))
                connector_points = ['{},{}'.format(p.x,p.y) for p in connector_pins]
                connection_points.extend(connector_points)
                inkex.errormsg("all points:{}".format(len(connection_points)))

        # return union_wire_points # to debug wire unions
        return connection_points


    def union_wires(self, min_wire, max_wire, is_horizontal): #TODO: refactor names , func enforces that min_wire is left/top and max_wire is right/bottom
        min_wire_points = min_wire.get_points()
        max_wire_points = max_wire.get_points()
        # inkex.errormsg("open connector idx:{}".format(self.connector.open_wire_idx))
        # determine how many points we have to scan over, scales by factor of 2 for every wire that gets joined to one another
        min_multiplier = min_wire.get_num_wire_joins(is_horizontal)
        max_multiplier = max_wire.get_num_wire_joins(is_horizontal)
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

            min_wire_splice_length = min(4 * min_multiplier, len(min_wire_points) - min_wire_idx)
            min_points = ['{},{}'.format(p.x,p.y) for p in min_wire_points[min_wire_idx: min_wire_idx + min_wire_splice_length]]
            union_wire_points.extend(min_points)
            min_wire_idx += min_wire_splice_length
        
        max_points = ['{},{}'.format(p.x,p.y) for p in max_wire_points[max_wire_idx: len(max_wire_points)]]
        union_wire_points.extend(max_points)
        inkex.errormsg("returning from connecting func:{}".format(union_wire_points))
            
        return union_wire_points

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
        inkex.errormsg("wtf")
        connector_pins = []
        connector_bbox = None
        for elem in self.svg.get_selected():
            if type(elem) == Polyline:
                wire = Wire(elem)
                self.wires.append(wire)
            elif type(elem) == PathElement: #connector
                connector_bbox = elem.bounding_box()
                points = [p for p in elem.path.end_points]
                if len(points) == 4:
                    connector_pins.append(elem)

        if connector_bbox is not None:
            self.connector = Connector(connector_pins, connector_bbox)

        if self.connector is None and len(self.wires) != 2: # user is selecting wires and not a connector
            inkex.errormsg(len(self.wires))
            inkex.errormsg("Please select only two wires to combine!")
            return
        if self.is_horizontal_connection:
            self.connect_wires_horizontally() if self.connector is None else self.horizontal_connector_union()
        else:
            inkex.errormsg(self.connector is None)
            self.connect_wires_vertically() if self.connector is None else self.vertical_connector_union()

class Wire():
    def __init__(self, wire):
        self.wire = wire
        self.points = [p for p in self.wire.path.end_points]
        # inkex.errormsg("wire_points:{}".format(["{},{}".format(p.x,p.y) for p in self.points]))
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
            if (is_horizontal and p1.x == p2.x) or (not is_horizontal and p1.y == p2.y):
                return point_counter // 2
            else:
                point_counter += 1
        return 1
    
    def get_points(self):
        return self.points

    def get_num_endpoints(self):
        left_side = self.bbox.left
        return sum([1 for p in self.points if p.x == left_side])
    
    
    def get_flipped_points(self, is_horizontal):
        multiplier = self.get_num_wire_joins(is_horizontal)        
        flipped_points = []
        debug_dict = {}
        for i in range(len(self.points)):
            debug_dict[self.points[i]] = i
        inkex.errormsg([i for i in range(len(self.points))])
        idx = 0
        while idx < len(self.points):
            sect1 = self.points[idx: idx + 2 * multiplier]
            sect2 = self.points[idx + 2 * multiplier: idx + 4 * multiplier]
            flipped_points.extend(sect1[::-1])
            flipped_points.extend(sect2[::-1])
            idx += 4 * multiplier
        arr = []
        for p in flipped_points:
            arr.append(debug_dict[p])
        inkex.errormsg("flipped:{}".format(arr))
        return flipped_points



if __name__ == '__main__':
    CombineGrids().run()