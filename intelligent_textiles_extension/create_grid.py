import json
import os
import sys
from base64 import b64decode
from argparse import ArgumentParser, REMAINDER

import appdirs
import inkex
from inkex import Line, Rectangle, Path, Polyline
import wx
import wx.adv
from lxml import etree
import pyembroidery


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
            inkex.errormsg("things selected:{}".format(len(self.svg.get_selected())))
            inkex.errormsg("type of elem:{}".format(type(elem)))
            inkex.errormsg("path:{}".format(elem.path))
            shape_points = [p for p in elem.path.end_points]
            bbox = elem.bounding_box()
            rectangle = BoundingBoxMetadata(inkex.units.convert_unit(bbox.width, 'mm'),
                                            inkex.units.convert_unit(bbox.height, 'mm'),
                                            inkex.units.convert_unit(bbox.top, 'mm'),
                                            inkex.units.convert_unit(bbox.bottom, 'mm'),
                                            inkex.units.convert_unit(bbox.left, 'mm'),
                                            inkex.units.convert_unit(bbox.right, 'mm'))

        create_grid_worker = CreateGridWorker(shape_points, rectangle, int(args.horizontal_wires), int(args.vertical_wires), self.svg, self.document)
        create_grid_worker.run()

        # parent = self.svg.get_current_layer()
        # self.draw_SVG_line(10,10,0,0, parent)

    def draw_SVG_line(self, x1, y1, x2, y2, parent):
        color = "red"
        line_attribs = {
                        'style' : "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
                        # 'd' : 'M 55.3977 90.881 H 114.748 V 80.9478 H 46.3977 V 78.0146 H 114.748 V 75.0815 H 46.3977 V 72.1483 H 114.748 V 69.2151 H 46.3977 V 66.2819 H 114.748 V 63.3488 H 46.3977 V 60.4156 H 114.748 V 57.4824 H 46.3977',
                        'points': 'M 0,0 9,9 5,5'
                        }

        line = etree.SubElement(parent, inkex.addNS('path','svg'), line_attribs)

        points = ['0,0', '10,10']
        color = "red"
        path_str = ' '.join(points)
        poly = inkex.Polyline(attrib={
        # 'id': "wire_segment",
        'style':"stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
        'points': path_str,
        })
        inkex.errormsg(str(poly.get_path()))

        line_attribs = {
                'style' : "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
                'd': str(poly.get_path())
        }
        
        etree.SubElement(self.svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)   

        # polyline(points,style=style)
class CreateGridWorker():

    def __init__(self, shape_points, rectangle, num_horizontal_wires, num_vertical_wires, svg, document):
        self.shape_points = shape_points
        self.rectangle = rectangle
        self.num_horizontal_wires = num_horizontal_wires
        self.num_vertical_wires = num_vertical_wires
        self.svg = svg
        self.upper_left, self.upper_right,self.lower_left,self.lower_right = self.rectangle.get_rectangle_points()
        self.document = document


    def run(self):
        # check vertical and horizontal spacing
        horizontal_wire = None
        vertical_wire = None
        if self.num_horizontal_wires != 0:
            total_horizontal_spacing = self.rectangle.height / (self.num_horizontal_wires + 1)
            horizontal_wire_spacing = (self.rectangle.height - total_horizontal_spacing) / self.num_horizontal_wires
            
            if (horizontal_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The horizontal wires must be at least {} mm apart
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, horizontal_wire_spacing))
                return
            horizontal_wire = self.lay_horizontal_wires(total_horizontal_spacing)
        if self.num_vertical_wires != 0:
            total_vertical_spacing = self.rectangle.width / (self.num_vertical_wires + 1)
            vertical_wire_spacing = (self.rectangle.width - total_vertical_spacing) / self.num_vertical_wires

            if (vertical_wire_spacing < MIN_GRID_SPACING):
                inkex.errormsg('''The vertical wires must be at least {} mm apart 
                                They are currently {} mm apart. Either decrease the
                                number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, vertical_wire_spacing))
                return
            vertical_wire = self.lay_vertical_wires(total_vertical_spacing)
        

        # dynamic stitching stuff!
        stitch_worker = MakeStitchesWorker(horizontal_wire, vertical_wire)
        stitch_worker.make_horizontal_stitches()

    def lay_horizontal_wires(self, horizontal_wire_spacing):
        curr_point = list(self.lower_left)
        wire_count = 0
        points = []
        while wire_count != self.num_horizontal_wires:
            curr_point[1] -= horizontal_wire_spacing
            if wire_count % 2 == 0:
                points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
                points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                # for p in connections:
                #     points.append('{},{}'.format(p.x, p.y))
            else:
                points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
            wire_count += 1
        inkex.errormsg("RESULT:{}".format(points))
        return self.create_path(points, is_horizontal=True)

    def lay_vertical_wires(self, vertical_wire_spacing):
        curr_point = list(self.upper_left)
        wire_count = 0
        points = []
        while wire_count != self.num_vertical_wires:
            curr_point[0] += vertical_wire_spacing
            if wire_count % 2 == 0:
                points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
                points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
            else:
                points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
                points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
            wire_count += 1

        return self.create_path(points, is_horizontal=False)

    

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
        return path


class MakeStitchesWorker():
    def __init__(self, horizontal_wire, vertical_wire):
        self.horizontal_wire_points = [p for p in horizontal_wire.get_path().end_points]
        self.vertical_wire = [p for p in vertical_wire.get_path().end_points]
        self.stitch_points = []
    
    def make_horizontal_stitches(self):
        unique_x_values = set([p.x for p in self.vertical_wire])
        inkex.errormsg("unique x's:{}".format(unique_x_values))
        
        pattern = pyembroidery.EmbPattern()
        # add stitches at end points
        # for p in self.horizontal_wire_points:
        #     pattern.add_stitch_absolute(pyembroidery.STITCH, p.x, p.y)
        
        stitched = [False for _ in range(len(self.horizontal_wire_points))]
        for i in range(0, len(self.horizontal_wire_points) - 1, 2):
            p0 = self.horizontal_wire_points[i]
            p1 = self.horizontal_wire_points[i+1]

            if not stitched[i]:
                pattern.add_stitch_absolute(pyembroidery.STITCH, p0.x, p0.y)
                stitched[i] = True
            if not stitched[i+1]:
                pattern.add_stitch_absolute(pyembroidery.STITCH, p1.x, p1.y)
                stitched[i+1] = True
            
            intersection_points = []
            if all([p0.x < x < p1.x] for x in unique_x_values):
                for x_i in unique_x_values:
                    intersection_points.append([x_i, p0.y])
            
            intersection_points = sorted(intersection_points, key = lambda p: p[0])
            point_idx = 0

            pattern.add_stitch_absolute(pyembroidery.STITCH, (p0.x + intersection_points[point_idx][0]) // 2, p0.y)
            pattern.add_stitch_absolute(pyembroidery.STITCH, (p1.x + intersection_points[point_idx][-1]) // 2 , p0.y)
            while point_idx < len(intersection_points)-1:
                mid_x = (intersection_points[point_idx][0] + intersection_points[point_idx+1][0]) // 2            
                point_idx += 1
                pattern.add_stitch_absolute(pyembroidery.STITCH, mid_x, p0.y)

        # inkex.errormsg("where are my stitches:{}, num_stitches = {}".format(pattern.stitches, len(pattern.stitches)))
        pyembroidery.write_pes(pattern, '/Users/hdacosta/Desktop/UROP/output/pattern.dst')

        # sanity_check
        # inkex.errormsg("num intersections:{}".format(len(intersection_points)))





    def make_vertical_stitches(self):
        pass 



if __name__ == '__main__':
    CreateGridEffect().run()


