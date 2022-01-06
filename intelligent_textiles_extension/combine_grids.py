from operator import is_
from inkex.deprecated import INKEX_DIR
from networkx.algorithms.graphical import is_graphical
from networkx.algorithms.operators.binary import union
import sys
from base64 import b64decode
from argparse import ArgumentParser, REMAINDER

import appdirs
import inkex
from inkex import Line, Rectangle, Path, Polyline, PathElement
import wx
import wx.adv
from lxml import etree

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
        self.open_wire_idx = 0 # idx of next available wire
        self.bbox = bbox
        self.num_pins = len(self.points) // 2
    def connect_pins(self):
        points = self.points[self.open_wire_idx : self.open_wire_idx + 4]
        self.open_wire_idx += 4
        return points

    def get_points(self):
        return self.points[self.open_wire_idx:]

    def reverse_pins(self):
        self.points = self.points[::-1]
    
    def get_num_wire_joins(self, is_horizontal=True):# overloaded method for wire connection
         return 1 


class CombineGridsEffect(inkex.Effect):
    def add_arguments(self, pars):
        pars.add_argument("--alignment", type=bool, help="The type of connection to make")
    
    def effect(self):
        arg_parser = ArgumentParser()
        self.add_arguments(arg_parser)
        args,_ = arg_parser.parse_known_args()
        combine_grids_worker = CombineGridsWorker(self.svg, args.alignment)
        combine_grids_worker.run()


class CombineGridsWorker():
    COMMANDS = ["combine_grids"]
    def __init__(self, svg, is_horizontal_connection):
        self.svg = svg
        self.is_horizontal_connection = is_horizontal_connection
        self.wires = []
        self.connector = None

    def pair_wires_horizontally(self):
        inkex.errormsg("COMING INTO PAIR")
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

    
    def pair_wires_vertically(self):
        rect1,rect2 = self.wires[0].bbox, self.wires[1].bbox
        top_wire = None 
        bottom_wire = None
        if rect1.top < rect2.top:
            top_wire, bottom_wire = self.wires
        else:
            bottom_wire, top_wire = self.wires
        
        if top_wire.get_num_endpoints(is_horizontal=False) % 2 == 1:
            top_wire.set_flipped_points(is_horizontal=False)
        union_wire_points = self.union_wires(top_wire, bottom_wire, is_horizontal=False)
        top_wire.wire.getparent().remove(top_wire.wire)
        bottom_wire.wire.getparent().remove(bottom_wire.wire)

        self.create_path(union_wire_points, is_horizontal=False)
    
    
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
            
        return union_wire_points
    
    def horizontal_grid_union(self):
        sorted_wires = sorted(self.wires, key= lambda x: -x.bbox.top) # start at bottommost wire
        union_wire_connector_points = self.unify_grids(sorted_wires, True)
        self.create_path(union_wire_connector_points, is_horizontal=True)
        
    def vertical_grid_union(self):
        sorted_wires = sorted(self.wires, key= lambda x: x.bbox.left) # start at bottommost wire
        union_wire_connector_points = self.unify_grids(sorted_wires, False)
        self.create_path(union_wire_connector_points, is_horizontal=False)

    def combine_wires(self, wires, is_horizontal):
        union_wire_points = []
        union_wire_sections = {}
        flip = False # has any wire in union been flipped?
        for i in range(len(wires)):
            wire = wires[i]
            points = None
            has_odd_wires = wire.get_num_endpoints(is_horizontal) % 2 == 1
            points = wire.get_points() if not flip else wire.get_flipped_points(is_horizontal)
            if has_odd_wires:
                flip = not flip

            formatted_points = ['{},{}'.format(p.x,p.y) for p in points]
            union_wire_points.extend(formatted_points)
            # map last index where current wire ends
            union_wire_sections[len(union_wire_points)] = wire.get_num_wire_joins(is_horizontal)
            wire.wire.getparent().remove(wire.wire)
        return union_wire_points, union_wire_sections

    def get_section_multiplier(self, current_index, union_wire_sections):
        for key in union_wire_sections.keys():
            if current_index < key:
                return key, union_wire_sections[key]
        return 0,0
    
    def get_shape_arrangment(self, grids, is_horizontal):
        shape_arrangement = None
        if is_horizontal:
            shape_arrangement = sorted(grids, key = lambda x: x.bbox.left)
        else:
            shape_arrangement = sorted(grids, key = lambda x: x.bbox.top)
        return shape_arrangement
        
    def unify_grids(self, wires, is_horizontal):
        shape_arrangement = None
        grids = wires[:]
        has_connector = self.connector is not None
        if has_connector: # user want to hook up grids to pins
            grids.append(self.connector)

        if is_horizontal:
            shape_arrangement = sorted(grids, key = lambda x: x.bbox.left)
        else:
            shape_arrangement = sorted(grids, key = lambda x: x.bbox.top)
        
        reversed_connection = None
        max_wire = None
        if has_connector:
            reversed_connection = self.connector == shape_arrangement[0]
        else:
            max_wire = max(wires, key= lambda w: w.get_num_endpoints(is_horizontal))
            reversed_connection = max_wire == shape_arrangement[0]
            inkex.errormsg("len of wires before:{}".format(len(wires)))
            wires = set(wires)
            wires.remove(max_wire)
            wires = list(wires)
            wires = sorted(wires, key=lambda x: -x.bbox.top if is_horizontal else x.bbox.left)
            inkex.errormsg("len of wires after:{}".format(len(wires)))
        
        if reversed_connection:
            _ = [wire.set_flipped_points(is_horizontal) for wire in wires]
            if has_connector:
                self.connector.reverse_pins()
            else:
                max_wire.set_flipped_points(is_horizontal)

        inkex.errormsg([type(i) for i in wires])
        union_wire_points, union_wire_sections = self.combine_wires(wires, is_horizontal) # map sections of unionized wire to each component wire multiplier
        inkex.errormsg("NUM WIRES HERE:{}".format(wires[0].get_num_endpoints(is_horizontal)))
        # now we splice in connector to union wire
        connection_points = []
        wire_point_idx = 0
        if not has_connector:
            max_wire_idx = 0 # only used in wire case
            max_wire_points = max_wire.get_points()
        inkex.errormsg("ALL POINTS: {}".format(len(union_wire_points)))
        inkex.errormsg("SECTIONS: {}".format(union_wire_sections))
        while wire_point_idx < len(union_wire_points):
            inkex.errormsg("************************************")
            inkex.errormsg("CURRENT INDEX:{}".format(wire_point_idx))
            max_idx, wire_multiplier = self.get_section_multiplier(wire_point_idx, union_wire_sections)
            inkex.errormsg("END OF THIS WIRE:{}".format(max_idx))
            points = None
            if wire_point_idx == 0: #starting wire line
                inkex.errormsg("\t-------STARTING WIRE------------")
                connection_points.extend(union_wire_points[wire_point_idx : wire_point_idx + 2 * wire_multiplier])
                wire_point_idx += 2 * wire_multiplier
            else:
                inkex.errormsg("\t-------COMING FROM CONNECTOR TO WRAP------------")
                mult = 2 * wire_multiplier # default is that wire wraps back around
                next_idx = wire_point_idx + 2 * mult
                inkex.errormsg("what is next idx:{} , {}".format(next_idx, max_idx))
                if next_idx > max_idx:
                    inkex.errormsg("wrapping intp next wire section")
                    _, new_sect_multiplier = self.get_section_multiplier(next_idx, union_wire_sections)
                    inkex.errormsg("MULT OF NEXT WIRE:{}".format(new_sect_multiplier))
                    mult += new_sect_multiplier - 1
                    inkex.errormsg("TOTAL POINTS TO JUMP:{}".format(mult * 2))
                for _ in range(mult):
                    connection_points.extend(union_wire_points[wire_point_idx : wire_point_idx + 2])
                    wire_point_idx += 2

            if wire_point_idx < len(union_wire_points):
                if has_connector:
                    connector_pins = self.connector.connect_pins()
                    connector_points = ['{},{}'.format(p.x,p.y) for p in connector_pins]
                    connection_points.extend(connector_points)
                else:
                    max_multiplier = max_wire.get_num_wire_joins(is_horizontal)
                    max_wire_splice_length = min(4 * max_multiplier, len(max_wire_points) - max_wire_idx)
                    max_points = ['{},{}'.format(p.x,p.y) for p in max_wire_points[max_wire_idx: max_wire_idx + max_wire_splice_length]]
                    max_wire_idx += max_wire_splice_length
                    connection_points.extend(max_points)
            else:
                endpoints = wires[-1].get_num_endpoints(is_horizontal)
                if endpoints % 2 == 1:
                    if has_connector:
                        connector_pins = self.connector.connect_pins()
                        connector_points = ['{},{}'.format(p.x,p.y) for p in connector_pins]
                        connection_points.extend(connector_points)
                    else:
                        max_multiplier = max_wire.get_num_wire_joins(is_horizontal)
                        max_wire_splice_length = min(4 * max_multiplier, len(max_wire_points) - max_wire_idx)
                        max_points = ['{},{}'.format(p.x,p.y) for p in max_wire_points[max_wire_idx: max_wire_idx + max_wire_splice_length]]
                        max_wire_idx += max_wire_splice_length
                        connection_points.extend(max_points)

        # return union_wire_points # to debug wire unions
        if not has_connector:
            max_wire.wire.getparent().remove(max_wire.wire)

        # return union_wire_points
        return connection_points
    
    def create_path(self, points, is_horizontal):
        '''
        Creates a wire segment path given all of the points sequentially
        '''
        
        color = "red" if is_horizontal else "blue"
        path_str = ' '.join(points)
        inkex.errormsg("points:{}".format(path_str))
        path = inkex.Polyline(attrib={
        'id': "wire_segment",
        'points': path_str,
        })

        inkex.errormsg("input points:{}".format(points))
        inkex.errormsg("path str:{}".format(str(path.get_path())))
        line_attribs = {
                'style' : "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
                'd': str(path.get_path())
                # 'points': 'M 0,0 9,9 5,5'
        }
        
        etree.SubElement(self.svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)  

    def run(self):
        connector_pins = []
        connector_bbox = None
        for elem in self.svg.get_selected():
            inkex.errormsg("what is type:{}".format(type(elem)))
            if type(elem) == Polyline:
                wire = Wire(elem)
                self.wires.append(wire)
            elif type(elem) == PathElement: #connector
                points = [p for p in elem.path.end_points] 
                if len(points) == 4:
                    connector_bbox = elem.bounding_box()
                    connector_pins.append(elem)
                else:
                    wire = Wire(elem)
                    self.wires.append(wire)

        if connector_bbox is not None:
            self.connector = Connector(connector_pins, connector_bbox)
        
        inkex.errormsg("NUM OF WIRES @ INIT:{}".format(len(self.wires)))
        inkex.errormsg("WHAT TYPE OF ALIGNMENT:{}".format(self.is_horizontal_connection))
        if len(self.wires) == 2 and self.connector is None:
            self.pair_wires_horizontally() if self.is_horizontal_connection else self.pair_wires_vertically()
        else:
            self.horizontal_grid_union() if self.is_horizontal_connection else self.vertical_grid_union()


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

    def get_num_endpoints(self, is_horizontal):
        num_wires = 0
        for p1 in self.points:
            counter = 1
            for p2 in self.points:
                if p1 != p2:
                    if is_horizontal:
                        if p1.x == p2.x:
                            counter += 1
                    else:
                        if p1.y == p2.y:
                            counter += 1
            if counter > num_wires:
                num_wires = counter
        return num_wires
    
    def set_flipped_points(self, is_horizontal):
        self.points = self.get_flipped_points(is_horizontal)
    
    
    def get_flipped_points(self, is_horizontal):
        multiplier = self.get_num_wire_joins(is_horizontal)        
        flipped_points = []
        idx = 0
        while idx < len(self.points):
            sect1 = self.points[idx: idx + 2 * multiplier]
            sect2 = self.points[idx + 2 * multiplier: idx + 4 * multiplier]
            flipped_points.extend(sect1[::-1])
            flipped_points.extend(sect2[::-1])
            idx += 4 * multiplier
        return flipped_points



if __name__ == '__main__':
    CombineGridsEffect().run()