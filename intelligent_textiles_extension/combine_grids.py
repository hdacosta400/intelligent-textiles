from argparse import ArgumentParser
import inkex
from inkex import Polyline, PathElement
from lxml import etree
from sympy import Segment, Point

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


MIN_GRID_SPACING = inkex.units.convert_unit(1.5, "mm") # change this to user input in future?
class CombineGridsEffect(inkex.Effect):
    def add_arguments(self, pars):
        pars.add_argument("--alignment", type=int, help="The type of connection to make")
    
    def effect(self):
        arg_parser = ArgumentParser()
        self.add_arguments(arg_parser)
        args,_ = arg_parser.parse_known_args()
        is_horizontal_connection = True if args.alignment == 1 else False

        combine_grids_worker = CombineGridsWorker(self.svg, is_horizontal_connection)
        combine_grids_worker.run()


class CombineGridsWorker():
    COMMANDS = ["combine_grids"]
    def __init__(self, svg, is_horizontal_connection):
        self.svg = svg
        self.is_horizontal_connection = is_horizontal_connection
        self.wires = []
        self.interpolation_wires = [] # for custom combination routing
        self.connector = None


    def group_wires(self, wires):
        '''
        Wires in the same grid are currently disjoint from each other
        Need to group them together so they get connected together
        Need to fix this for when wire groups are angled (Same x/y won't apply)

        TODO: integrate IDs somehow
        '''
        wire_groups = {}
        # if self.is_horizontal_connection: # wires will have same x
        for w_points in wires:
            # points = [p for p in w.path.end_points]
            p = w_points[0]
            key = p.x if self.is_horizontal_connection else p.y
            if key not in wire_groups:
                wire_groups[key] = [w_points]
            else:
                wire_groups[key].append(w_points)
        for k in wire_groups:
            if self.is_horizontal_connection: # sort wires from top to bottom
                wire_groups[k] = sorted(wire_groups[k], key=lambda w:-w[0].y)
            else: # sort wires from left to right
                wire_groups[k] = sorted(wire_groups[k], key=lambda w:w[0].x)

        return wire_groups

                
    def connect_wires(self, wire_groups_dict, interp_wires=None, interp_dict=None, interp_start_indices=None):
        start_points = sorted(list(wire_groups_dict.keys()))        
        wire_groups = [wire_groups_dict[k] for k in start_points]
        wire_lens = [len(w) for w in wire_groups]
        wire_indices = [0 for _ in range(len(wire_groups))] # starting indices
        generated_combined_wires = []
        while wire_indices != wire_lens:
            joint_wire_points = []
            interp_done = False # FIX THIS to better determine when to add interpolation wires!
            for wire_group_idx, curr_wire_idx in enumerate(wire_indices):
                max_idx = wire_lens[wire_group_idx]
                if curr_wire_idx != max_idx: # add the wire itself
                    current_wire = wire_groups[wire_group_idx][curr_wire_idx]
                    joint_wire_points.extend([[p.x, p.y] for p in current_wire])
                    wire_indices[wire_group_idx] += 1
                if interp_wires is not None and not interp_done: # add custom routes if inputted by user
                    if curr_wire_idx == 0: joint_wire_points.extend([[p.x,p.y] for p in interp_wires[0]])
                    elif curr_wire_idx == max_idx - 1: joint_wire_points.extend([[p.x,p.y] for p in interp_wires[1]])
                    else:
                        interp_points = self.add_interpolation_points(curr_wire_idx, interp_wires, interp_dict)
                        # check if interp points intersect with any others
                        #NEED ALL POINTS HERE!
                        joint_wire_points.extend(interp_points)
                    interp_done = True

            generated_combined_wires.append(joint_wire_points)       
            joint_wire_points = ['{},{}'.format(p[0],p[1]) for p in joint_wire_points]
            self.create_path(joint_wire_points, is_horizontal=self.is_horizontal_connection)
            
            # can move this block before to prevent drawing of wires

        is_valid_routing = self.has_valid_interpolation_points(generated_combined_wires)
        if not is_valid_routing:
            inkex.errormsg("Please change your template routing wires.")
            return
    
    def has_valid_interpolation_points(self, generated_combined_wires):
        '''
        generated_combined_wires: list of interpolation wire_points for each wire

        checks if the interpolation wires (1) don't intersect and (2) are sufficienty far away from each other

        the minimum pitch between interpolation wires determined by MIN_GRID_SPACING 
        but can easily be made a user input in the future
        '''
        for wire1 in generated_combined_wires:
            for wire2 in generated_combined_wires:
                if wire1 != wire2:
                    for i in range(len(wire1) - 1):
                        wire1_p1 = Point(wire1[i])
                        wire1_p2 = Point(wire1[i+1])
                        wire1_segment = Segment(wire1_p1, wire1_p2)
                        # check current segment across all segments in next wire
                        for j in range(len(wire2) - 1):
                            wire2_p1 = Point(wire2[j])
                            wire2_p2 = Point(wire2[j+1])
                            wire2_segment = Segment(wire2_p1, wire2_p2)

                            # check for intersection
                            intersection = wire1_segment.intersection(wire2_segment)

                            if intersection != []:
                                inkex.errormsg("There are intersecting routing wires present.")
                                return False # has intersecting points
                            
                            # check for distance
                            min_distance = min(wire1_segment.distance(wire2_p1), wire1_segment.distance(wire2_p2),
                                               wire2_segment.distance(wire1_p1), wire2_segment.distance(wire1_p2))
                            if min_distance < MIN_GRID_SPACING:
                                inkex.errormsg("The routing wires are closer than the minimum {} distance.".format(MIN_GRID_SPACING))
                                return False
        return True

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

    def generate_interpolation_points(self, interpolation_wires, num_wires):
        '''
        Generates a dict mapping a pair of points on interpolation wires to the intermediate
        points to be used by wires 
        '''
        interp_dict = {}
        for i in range(len(interpolation_wires) - 1):
            
            wire1 = interpolation_wires[i]
            wire2 = interpolation_wires[i+1]
            for j in range(1, len(wire1) - 1): # exclude parts of interp wire that connect to sensor wire
                x1, y1 = wire1[j].x, wire1[j].y
                x2, y2 = wire2[j].x, wire2[j].y
                line = [[x1, y1], [x2, y2]]
                interp_dict[(x1, y1, x2, y2)] = [[x1, y1]]
                # FOR NOW, assume interp wires are placed @ top and bottommost wire
                # need to account for these points already placed by subtracting 2
                # in future, user may only want custom wiring for SOME wires and default for others
                # in this case, need to add additional detection mechanisms to see where they are
                interp_points = self.segment_line(line, num_wires - 2)
                interp_dict[(x1, y1, x2, y2)].extend(interp_points)
                # points = ['{},{}'.format(p[0],p[1]) for p in line]
                # self.create_path(points, False)
        return interp_dict

    def calculate_interp_wire_group(self, wire_groups_dict, interpolation_wires):
        start_points = sorted(list(wire_groups_dict.keys()))
        interp_start_indices = []
        for sp in start_points:
            for wire_idx, wire in enumerate(wire_groups_dict[sp]):
            # assumption that interpolation wire starts at END of a wire
                for w in interpolation_wires:
                    if wire[-1].x == w[0][0] and wire[-1].y == w[0][1]:
                        interp_start_indices.append((sp,wire_idx))

        return interp_start_indices

    def connect_custom_wires(self, wire_groups_dict, interpolation_wires):
        # how many wires are grouped together???
        num_wires = len(wire_groups_dict[list(wire_groups_dict.keys())[0]])
        interp_dict = self.generate_interpolation_points(interpolation_wires, num_wires)

        # determine the wiregroups where the interpolation wires start
        interp_start_indices = self.calculate_interp_wire_group(wire_groups_dict, interpolation_wires)
        self.connect_wires(wire_groups_dict, interpolation_wires, interp_dict, interp_start_indices)  


    def add_interpolation_points(self, wire_idx, interpolation_wires, interpolation_dict):
        '''
        Generates list of interpolation points to add to current wire
        FOR NOW ASSUMING TWO INTERPOLATION WIRES
        '''
        wire1, wire2 = interpolation_wires
        intermediate_points = []
        for i in range(1, len(wire1) - 1):
            x1, y1 = wire1[i].x, wire1[i].y
            xn, yn = wire2[i].x , wire2[i].y
            interpolation_points = interpolation_dict[(x1,y1,xn,yn)]
            intermediate_points.append(interpolation_points[wire_idx])
        return intermediate_points

        

    def run(self):
        
        for elem in self.svg.get_selected():
            if type(elem) == PathElement: #connector
                points = [p for p in elem.path.end_points] 
                # if len(points) == 4: # figure out differnt condition for this
                #     connector_bbox = elem.bounding_box()
                #     connector_pins.append(elem)
                if len(points) > 2:
                    self.interpolation_wires.append(points)
                else:
                    self.wires.append(points)


        wire_groups = self.group_wires(self.wires)
        if len(self.interpolation_wires) == 0:
            self.connect_wires(wire_groups)
        else: #custom connection
            if len(self.interpolation_wires) > 2: # may not need to be the case in the future
                inkex.errormsg("only create two custom routes for interpolation")
                return
            else:
                # check lens of interpolation wires to make sure they are the same
                len_wire = len(self.interpolation_wires[0])
                same_length = all([len(w) == len_wire for w in self.interpolation_wires])
                if not same_length:
                    inkex.errormsg("interpolation wires have the same number of points")
                    return
                if self.is_horizontal_connection:
                    self.interpolation_wires = sorted(self.interpolation_wires, key=lambda w:-w[0].y)
                else:
                    self.interpolation_wires = sorted(self.interpolation_wires, key=lambda w:w[0].x)
                self.connect_custom_wires(wire_groups, self.interpolation_wires)
        
        # remove old wires
        for elem in self.svg.get_selected(): elem.getparent().remove(elem)
        return

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



if __name__ == '__main__':
    CombineGridsEffect().run()