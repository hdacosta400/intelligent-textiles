from argparse import ArgumentParser
from turtle import distance

import inkex
from inkex import Line, Rectangle, Path, Polyline
from lxml import etree
import pyembroidery
import math
from wiredb_proxy import WireDBProxy



MIN_GRID_SPACING = inkex.units.convert_unit(2.5, "mm")
class CreateCustomGridEffect(inkex.Effect):

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
        for elem in self.svg.get_selected():
            shape_points = [p for p in elem.path.end_points]
            if len(shape_points) > 5:
                inkex.errormsg("Please create a 4-sided shape.")
                return 
        create_custom_grid_worker = CreateCustomGridWorker(shape_points[:len(shape_points) - 1], int(args.horizontal_wires), int(args.vertical_wires), self.svg)
        create_custom_grid_worker.run()

class CreateCustomGridWorker():

    def __init__(self, shape_points, num_horizontal_wires, num_vertical_wires, svg):
        self.shape_points = shape_points
        self.num_horizontal_wires = num_horizontal_wires
        self.num_vertical_wires = num_vertical_wires
        self.svg = svg
        self.upper_left, self.lower_left, self.upper_right, self.lower_right = self.compute_corners()
        self.wiredb_proxy = WireDBProxy()

    def compute_euclidean_distance(self, x1, y1, x2, y2):
        return math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)


    def compute_corners(self):
        '''
        arranges the corners of a 4 sided polygon created by the user
        sp:[Vector2d(-277.469, 592.45), Vector2d(-177.218, 590.51), Vector2d(-149.406,518.717), Vector2d(-298.812, 521.304), Vector2d(-277.469, 592.45)]

        '''
        left_arranged = sorted(self.shape_points, key = lambda p: p.x)
        upper_left, lower_left = sorted(left_arranged[:2], key = lambda p: p.y)
        upper_right, lower_right = sorted(left_arranged[2:], key = lambda p: p.y)
        return  upper_left, lower_left, upper_right, lower_right
    
    def draw_corners(self):
        '''
        Debugging tool to make sure correct side vectors are identified
        '''
        # top
        points = ['{}, {}'.format(p.x, p.y) for p in [self.upper_left, self.upper_right]]
        self.create_path(points, "red")
        # left
        points = ['{}, {}'.format(p.x, p.y) for p in [self.upper_left, self.lower_left]]
        self.create_path(points, "blue")
        #right
        points = ['{}, {}'.format(p.x, p.y) for p in [self.upper_right, self.lower_right]]
        self.create_path(points, "purple")
        # bottom
        points = ['{}, {}'.format(p.x, p.y) for p in [self.lower_left, self.lower_right]]
        self.create_path(points, "orange")

        
    def run(self): 
        # self.draw_corners()
        if self.num_horizontal_wires != 0:
            # look at left and right side, take shorter one to compute spacing   
            left_side_distance = self.compute_euclidean_distance(self.upper_left.x, self.upper_left.y,
                                                                 self.lower_left.x, self.lower_left.y)

            right_side_distance = self.compute_euclidean_distance(self.upper_right.x, self.upper_right.y,
                                                                 self.lower_right.x, self.lower_right.y)
            min_height = min(left_side_distance, right_side_distance)

            total_horizontal_spacing = min_height / (self.num_horizontal_wires + 1)
            horizontal_wire_spacing = (min_height - total_horizontal_spacing) / self.num_horizontal_wires
            
            if (horizontal_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The horizontal wires must be at least {} mm apart
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, horizontal_wire_spacing))
                return

            horizontal_wire_ids = self.lay_horizontal_wires(left_side_distance, right_side_distance)
            self.wiredb_proxy.insert_new_wire_group(horizontal_wire_ids)

        if self.num_vertical_wires != 0:
            top_side_distance = self.compute_euclidean_distance(self.upper_left.x, self.upper_left.y,
                                                                 self.upper_right.x, self.upper_right.y)

            bottom_side_distance = self.compute_euclidean_distance(self.lower_left.x, self.lower_left.y,
                                                                 self.lower_right.x, self.lower_right.y)
            min_width = min(top_side_distance, bottom_side_distance)
            total_vertical_spacing = min_width / (self.num_vertical_wires + 1)
            vertical_wire_spacing = (min_width - total_vertical_spacing) / self.num_vertical_wires

            if (vertical_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The vertical wires must be at least {} mm apart 
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, vertical_wire_spacing))
                return

            vertical_wire_ids = self.lay_vertical_wires(top_side_distance, bottom_side_distance)
            self.wiredb_proxy.insert_new_wire_group(vertical_wire_ids)
    
    def segment_line(self, line, line_distance, num_points):
        '''
        Breaks line into num_points equal parts
        returns array of points 

        line: A shapely.LineString object (interpolation along line can be done manually but this is easier)
        '''
        points = []
        def parameterize_line(t):
            x_t = line[0][0] + (line[1][0] - line[0][0]) * t
            y_t = line[0][1] + (line[1][1] - line[0][1]) * t
            return x_t, y_t
        
        segment_length = 1 / (num_points + 1)
        for i in range(1 ,num_points+1): # adjust from 0 to n+1 bc we cant put in 0 to the parameterized line equation
            x, y = parameterize_line(i * segment_length)
            points.append([x,y])
        return points
    
    def lay_horizontal_wires(self, left_side_distance, right_side_distance):
        left_line = [(self.upper_left.x, self.upper_left.y), (self.lower_left.x, self.lower_left.y)]
        right_line = [(self.upper_right.x, self.upper_right.y), (self.lower_right.x, self.lower_right.y)]
        left_side_points = self.segment_line(left_line, left_side_distance, self.num_horizontal_wires)

        right_side_points = self.segment_line(right_line, right_side_distance, self.num_horizontal_wires)

        inkex.errormsg("\n\n num points lr:{} {}".format(len(left_side_points), len(right_side_points)))
        return self.lay_wire(left_side_points, right_side_points, is_horizontal=True)

    
    def lay_vertical_wires(self, top_side_distance, bottom_side_distance):
        top_line = [(self.upper_left.x, self.upper_left.y), (self.upper_right.x, self.upper_right.y)]
        bottom_line = [(self.lower_left.x, self.lower_left.y), (self.lower_right.x, self.lower_right.y)]
        top_side_points = self.segment_line(top_line, top_side_distance, self.num_vertical_wires)
        bottom_side_points = self.segment_line(bottom_line, bottom_side_distance, self.num_vertical_wires)
        return self.lay_wire(top_side_points, bottom_side_points, is_horizontal=False)
    

    def lay_wire(self, wire1_points, wire2_points, is_horizontal):
        points = []
        wire_count = 0
        wire1_idx = 0
        wire2_idx = 0
        wire_ids = []
        while wire1_idx < len(wire1_points) and wire2_idx < len(wire2_points):
            # if wire_count % 2 == 0:
            if wire1_idx < len(wire1_points):
                points.append('{},{}'.format(wire1_points[wire1_idx][0], wire1_points[wire1_idx][1]))
                wire1_idx += 1
            if wire2_idx < len(wire2_points):
                points.append('{},{}'.format(wire2_points[wire2_idx][0], wire2_points[wire2_idx][1]))
                wire2_idx += 1
            wire = self.create_path(points, is_horizontal)
            wire_ids.append(wire.get_id())
            points = []
            # else:
            #     if wire2_idx < len(wire2_points):
            #         points.append('{},{}'.format(wire2_points[wire2_idx][0], wire2_points[wire2_idx][1]))
            #         wire2_idx += 1 
            #     if wire1_idx < len(wire1_points):
            #         points.append('{},{}'.format(wire1_points[wire1_idx][0], wire1_points[wire1_idx][1]))
            #         wire1_idx += 1
        inkex.errormsg("num wires generated:{} is horz:{}".format(len(wire_ids), is_horizontal))
        return wire_ids

    def create_path(self, points, is_horizontal):
        '''
        Creates a wire segment path given all of the points sequentially
        '''
        
        color = "red" if is_horizontal else "blue"
        path_str = ' '.join(points)
        path = inkex.Polyline(attrib={
        'id': "wire_segment",
        'points': path_str,
        })

        line_attribs = {
                'style' : "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
                'd': str(path.get_path())
                # 'points': 'M 0,0 9,9 5,5'
        }
        
        elem = etree.SubElement(self.svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)  
        return elem

if __name__ == '__main__':
    CreateCustomGridEffect().run()