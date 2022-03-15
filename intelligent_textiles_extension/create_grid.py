from argparse import ArgumentParser
import inkex
from inkex import Rectangle, Group
from lxml import etree
import pyembroidery
import matplotlib.pyplot as plt
import numpy as np

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
            inkex.errormsg("shape points, bbox:{} , {}".format(shape_points, bbox))
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
        # stitch_worker = MakeStitchesWorker(horizontal_wire, vertical_wire)
        # stitch_worker.make_horizontal_stitches()

    def lay_horizontal_wires(self, horizontal_wire_spacing):
        curr_point = list(self.lower_left)
        wire_count = 0
        points = []
        wires = []
        
        while wire_count != self.num_horizontal_wires:
            curr_point[1] -= horizontal_wire_spacing
            # if wire_count % 2 == 0:
            points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
            points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
            w = self.create_path(points, is_horizontal=True)
            wires.append(w)
            points = []
            # else:
            #     points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
            #     points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
            wire_count += 1
        # return self.create_path(points, is_horizontal=True)
        return wires

    def lay_vertical_wires(self, vertical_wire_spacing):
        curr_point = list(self.upper_left)
        wire_count = 0
        points = []
        wires = []
        while wire_count != self.num_vertical_wires:
            curr_point[0] += vertical_wire_spacing
            # if wire_count % 2 == 0:
            points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
            points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
            wires.append(self.create_path(points, is_horizontal=False))
            points = []
            # else:
            #     points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
            #     points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
            wire_count += 1
        return wires

    

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
        
        etree.SubElement(self.svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)  
        return path


class MakeStitchesWorker():
    def __init__(self, horizontal_wire, vertical_wire):
        self.horizontal_wire_points = sorted([p for p in horizontal_wire.get_path().end_points], key=lambda p: -p[1])
        self.vertical_wire = [p for p in vertical_wire.get_path().end_points]
        self.stitch_points = []
    
    def make_horizontal_stitches(self):
        unique_x_values = set([p.x for p in self.vertical_wire])
        
        pattern = pyembroidery.EmbPattern()
        # add stitches at end points
        # for p in self.horizontal_wire_points:
        #     pattern.add_stitch_absolute(pyembroidery.STITCH, p.x, p.y)
        
        stitch_array = []
        inkex.errormsg("HORZ WIRE PTS:{}".format(self.horizontal_wire_points))
        for i in range(0, len(self.horizontal_wire_points) - 1, 2):
            row_stitch_array = []

            p0 = self.horizontal_wire_points[i]
            p1 = self.horizontal_wire_points[i+1]

            row_stitch_array.append([p0.x, p0.y])   
            row_stitch_array.append([p1.x,p1.y])         

            
            
            intersection_points = []
            if all([p0.x < x < p1.x] for x in unique_x_values):
                for x_i in unique_x_values:
                    intersection_points.append([x_i, p0.y])
            
            intersection_points = sorted(intersection_points, key = lambda p: p[0])
            point_idx = 0
            if p0.x < p1.x: #p0 is on the right
                row_stitch_array.append([(p0.x + intersection_points[point_idx][0]) // 2, p0.y])
                row_stitch_array.append([(p1.x + intersection_points[-1][0]) // 2, p1.y])
            else:
                row_stitch_array.append([(p0.x + intersection_points[-1][0]) // 2, p0.y])
                row_stitch_array.append([(p1.x + intersection_points[0][0]) // 2, p1.y])
            inkex.errormsg("first and last endpoint x values: {} and {}".format(p0.x, p1.x))
            inkex.errormsg("first and last x values:{} and {}".format(intersection_points[point_idx][0], intersection_points[-1][0]))

            while point_idx < len(intersection_points)-1:
                
                mid_x = (intersection_points[point_idx][0] + intersection_points[point_idx+1][0]) // 2            
                point_idx += 1
                row_stitch_array.append([mid_x, p0.y])
            
            # need to stitch wire continously from bottom left to top right, so row_stitch array is reversed 
            # depending on what side of the wire we started on for this iteration
            if p0.x < p1.x: #left to right
                row_stitch_array = sorted(row_stitch_array, key= lambda p: p[0])
            else: # right to left
                row_stitch_array = sorted(row_stitch_array, key= lambda p: p[0], reverse=True)
            
            # add to stitch array
            stitch_array.extend(row_stitch_array)

        # add actual stitches now that the stitch points are in the order we want them to be in 
        for x, y in stitch_array:
            pattern.add_stitch_absolute(pyembroidery.STITCH, x, y)
        
        pyembroidery.write_pes(pattern, '/Users/hdacosta/Desktop/UROP/output/pattern.dst')

        # sanity_check
        # inkex.errormsg("num intersections:{}".format(len(intersection_points)))
        # self.visualize_stitches(pattern)
    def visualize_stitches(self, pattern):
        #visualize stitches
        stitch_info = np.asarray(pattern.stitches)
        #Extract info from np.array and convert to mm
        x_coord = stitch_info[:,0]/10
        y_coord = stitch_info[:,1]/10
        num_of_stitches = len(x_coord)
        #Plot the stitches
        stitch_loc = plt.scatter(x_coord, y_coord, s = 1, c = 'black')

        #Add label to every ith stitch
        i = 0
        while i <= num_of_stitches - 1: 
            plt.annotate(i, (x_coord[i], y_coord[i]))
            i += 1

        #label axis
        plt.title("Stitch Vis")
        plt.xlabel('X Coordinates (mm)')
        plt.ylabel('Y Coordinates (mm)')

        #show the plot
        plt.show()

         
    def make_vertical_stitches(self):
        pass 



if __name__ == '__main__':
    CreateGridEffect().run()


