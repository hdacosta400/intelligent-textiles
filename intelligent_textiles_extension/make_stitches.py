import inkex
from inkex.paths import Path
import pyembroidery
from argparse import ArgumentParser
import numpy as np
from matplotlib import pyplot as plt
from lxml import etree
import math
from bezier import Curve
from scipy import interpolate
import simplepath

class MakeStitchesEffect(inkex.Effect):
    def add_arguments(self, pars):
        pars.add_argument("--wire_type", type=int)
    
    def effect(self):
        arg_parser = ArgumentParser()
        self.add_arguments(arg_parser)
        args,_ = arg_parser.parse_known_args()
        wire = None 

        # add a case for multiple selections (grid stitching)
        for elem in self.svg.get_selected():
            wire = elem

        # debugging for mapping out control and end points of a path
        # poi = [p for p in wire.path.end_points]
        # points = ['{},{}'.format(p.x,p.y) for p in poi]
        # self.create_path(points, True)
        # poi = [p for p in wire.path.control_points]
        # points = ['{},{}'.format(p.x,p.y) for p in poi]
        # self.create_path(points, False)

        is_curve = True if args.wire_type == 1 else False
        make_stitches_worker = MakeStitchesWorker(wire, is_curve)
        make_stitches_worker.run()
    
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

class MakeStitchesWorker(inkex.Effect):
    def __init__(self, wire, is_curve):
        self.wire = wire
        self.is_curve = is_curve

        self.control_points = []
        if self.is_curve:
            self.control_points = [p for p in wire.path.control_points]

        self.end_points = [p for p in wire.path.end_points]
        self.wire_points = []
        if self.is_curve:
            points = []
            path = simplepath.parsePath(wire.path)
            for t, ele in path:
                for i in range(0,len(ele)-1,2):
                    x = ele[i]
                    y = ele[i+1]
                    points.append([x,y])
            self.wire_points = points
        else:
            self.wire_points = self.end_points
        
    
    def stitch_curve(self):
        '''
        Bezier curves represented with 4 points
        We can use them and a general parametric equation to generate stitch points
        '''
        stitch_points = []

        nodes = np.asfortranarray([
            # [p.x for p in  self.wire_points],
            # [p.y for p in  self.wire_points]
            [p[0] for p in  self.wire_points],
            [p[1] for p in  self.wire_points]
        ]).astype('double')

        curve = Curve.from_nodes(nodes, copy=True)


        t = 0.01
        point = curve.evaluate(t)
        x = point[0][0]
        y = point[1][0]
        stitch_points.append([x,y])
        for _ in range(99): # change this number to change pitch of stitches, may also convert to user input in the future
            point = curve.evaluate(t)
            x = point[0][0]
            y = point[1][0]
            stitch_points.append([x,y])
            t += .01
        return stitch_points

    def compute_euclidean_distance(self, x1, y1, x2, y2):
        return math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)

    def segment_line(self, line, num_points):
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
        for i in range(1 ,num_points+2): # adjust from 0 to n+1 bc we cant put in 0 to the parameterized line equation
            x, y = parameterize_line(i * segment_length)
            points.append([x,y])
        return points

    def stitch_segment(self):
        stitch_points = []
        for i in range(len(self.wire_points) - 1):
            p1 = self.wire_points[i]
            p2 = self.wire_points[i+1]
            stitch_points.append([p1.x, p1.y])
            line = [[p1.x, p1.y], [p2.x, p2.y]]
            num_points = 3 # could make this a user input somehow?
            stitch_points.extend(self.segment_line(line, num_points))
        return stitch_points



        
    def make_stitches(self, stitch_points):
        pattern = pyembroidery.EmbPattern()
        for x, y in stitch_points:
            pattern.add_stitch_absolute(pyembroidery.STITCH, x, y)
        pyembroidery.write_pes(pattern, '/Users/hdacosta/Desktop/UROP/output/pattern1.dst')
        self.visualize_stitches(pattern)


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
            i += 5

        #label axis
        plt.title("Stitch Vis")
        plt.xlabel('X Coordinates (mm)')
        plt.ylabel('Y Coordinates (mm)')

        #show the plot
        plt.show()

    def run(self):
        stitch_points = None
        if self.is_curve:
            stitch_points = self.stitch_curve()
        else:
            stitch_points = self.stitch_segment()
        self.make_stitches(stitch_points)



if __name__ == '__main__':
    MakeStitchesEffect().run()