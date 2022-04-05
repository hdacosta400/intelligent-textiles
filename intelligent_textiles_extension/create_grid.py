from argparse import ArgumentParser
import inkex
from inkex import Rectangle, Group
from lxml import etree
import pyembroidery
import matplotlib.pyplot as plt
import numpy as np
import random
from wiredb_proxy import WireDBProxy
import wire_util

MIN_GRID_SPACING = inkex.units.convert_unit(2.5, "mm")
BBOX_SPACING = inkex.units.convert_unit(5, 'mm')

class BoundingBoxMetadata():
    '''
    Storage class to hold important information about rectangle
    '''
    def __init__(self, width, height, top, bottom, left, right):
        self.width = width
        self.height = height
        self.top = top
        self.bottom = bottom
        self.left = left
        self.right = right
    
    def get_rectangle_points(self):
        '''
        returns upper_left , upper_right, lower_left, lower_right points as list of tuples 
        in that order
        '''
        return [
            (self.left, self.top),
            (self.right, self.top),
            (self.left, self.bottom),
            (self.right, self.bottom)
            ]

class CreateGridEffect(inkex.Effect):

    def add_arguments(self, pars):
        pars.add_argument("--horizontal_wires", type=str,\
            help="The number of desired horizontal wires")
        pars.add_argument("--vertical_wires", type=str,\
            help="The number of desired vertical wires")

    def effect(self):
        arg_parser = ArgumentParser()
        self.add_arguments(arg_parser)
        args, _ = arg_parser.parse_known_args()
        inkex.errormsg("{},{}".format(args.horizontal_wires, args.horizontal_wires))

        things_selected = len(self.svg.get_selected())
        if things_selected != 1:
            inkex.errormsg("Please select only one object to create a grid for");
            return 
        
        shape_points = None
        rectangle = None 
        for elem in self.svg.get_selected(): # PATH ELEMENT
            units = "mm" if type(elem) == Rectangle else "px"
            shape_points = [p for p in elem.path.end_points]
            bbox = elem.bounding_box()
            inkex.errormsg("ID:{}".format(elem.get_id()))
            rectangle = BoundingBoxMetadata(inkex.units.convert_unit(bbox.width, units),
                                            inkex.units.convert_unit(bbox.height, units),
                                            inkex.units.convert_unit(bbox.top, units),
                                            inkex.units.convert_unit(bbox.bottom, units),
                                            inkex.units.convert_unit(bbox.left, units),
                                            inkex.units.convert_unit(bbox.right, units))

        create_grid_worker = CreateGridWorker(shape_points, rectangle, int(args.horizontal_wires), int(args.vertical_wires), self.svg)
        create_grid_worker.run()

class CreateGridWorker():

    def __init__(self, shape_points, rectangle, num_horizontal_wires, num_vertical_wires, svg):
        self.shape_points = shape_points
        self.rectangle = rectangle
        self.num_horizontal_wires = num_horizontal_wires
        self.num_vertical_wires = num_vertical_wires
        self.svg = svg
        self.upper_left, self.upper_right,self.lower_left,self.lower_right = self.rectangle.get_rectangle_points()
        self.wiredb_proxy = WireDBProxy()


    def run(self):
        # check vertical and horizontal spacing
        if self.num_horizontal_wires != 0:
            total_horizontal_spacing = self.rectangle.height / (self.num_horizontal_wires + 1)
            horizontal_wire_spacing = (self.rectangle.height - total_horizontal_spacing) / self.num_horizontal_wires
            
            if (horizontal_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The horizontal wires must be at least {} mm apart
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, horizontal_wire_spacing))
                return
            horizontal_wire_ids = self.lay_horizontal_wires(total_horizontal_spacing)
            self.wiredb_proxy.insert_new_wire_group(horizontal_wire_ids)

        if self.num_vertical_wires != 0:
            total_vertical_spacing = self.rectangle.width / (self.num_vertical_wires + 1)
            vertical_wire_spacing = (self.rectangle.width - total_vertical_spacing) / self.num_vertical_wires

            if (vertical_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The vertical wires must be at least {} mm apart 
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, vertical_wire_spacing))
                return
            vertical_wire_ids = self.lay_vertical_wires(total_vertical_spacing)
            self.wiredb_proxy.insert_new_wire_group(vertical_wire_ids)
        

    # TODO: maybe combine these two functions
    def lay_horizontal_wires(self, horizontal_wire_spacing):
        curr_point = list(self.lower_left)
        wire_count = 0
        points = []
        wires = []
        wire_ids = []
        while wire_count != self.num_horizontal_wires:
            curr_point[1] -= horizontal_wire_spacing
            # if wire_count % 2 == 0:
            points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
            points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
            elem = wire_util.create_path(self.svg, points, is_horizontal=True)
            wires.append(elem)
            wire_ids.append(elem.get_id())
            points = []
            wire_count += 1
        return wire_ids

    def lay_vertical_wires(self, vertical_wire_spacing):
        curr_point = list(self.upper_left)
        wire_count = 0
        points = []
        wires = []
        wire_ids = []
        while wire_count != self.num_vertical_wires:
            curr_point[0] += vertical_wire_spacing
            points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
            points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
            elem = wire_util.create_path(self.svg, points, is_horizontal=False)
            wires.append(elem)
            wire_ids.append(elem.get_id())
            points = []
            wire_count += 1
        return wire_ids

if __name__ == '__main__':
    CreateGridEffect().run()


