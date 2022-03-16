from argparse import ArgumentParser
import inkex
from inkex import Polyline, PathElement
from lxml import etree
from inkex.styles import Style


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
        pars.add_argument("--alignment", type=int, help="The type of connection to make")
    
    def effect(self):
        arg_parser = ArgumentParser()
        self.add_arguments(arg_parser)
        args,_ = arg_parser.parse_known_args()
        inkex.errormsg("what is alignment:{}".format(args.alignment))
        is_horizontal_connection = True if args.alignment == 1 else False

        combine_grids_worker = CombineGridsWorker(self.svg, is_horizontal_connection)
        combine_grids_worker.run()


class CombineGridsWorker():
    COMMANDS = ["combine_grids"]
    def __init__(self, svg, is_horizontal_connection):
        print("WORKER INIT")
        self.svg = svg
        self.is_horizontal_connection = is_horizontal_connection
        self.wires = []
        self.connector = None


    def group_wires(self, wires):
        '''
        Wires in the same grid are currently disjoint from each other
        Need to group them together so they get connected together

        Need to fix this for when wire groups are angled (Same x/y won't apply)
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

        inkex.errormsg("num groups:{}\n\n\n".format(len(wire_groups.keys())))
        return wire_groups

                
    def connect_wires(self, wire_groups_dict, interp_wires=None, interp_dict=None, interp_start_indices=None):
        start_points = sorted(list(wire_groups_dict.keys()))        
        wire_groups = [wire_groups_dict[k] for k in start_points]
        wire_lens = [len(w) for w in wire_groups]
        wire_indices = [0 for _ in range(len(wire_groups))] # starting indices
        inkex.errormsg("interp start indices:{}".format(interp_start_indices))
        while wire_indices != wire_lens:
            joint_wire_points = []
            interp_done = False # FIX THIS to better determine when to add interpolation wires!
            for wire_group_idx, curr_wire_idx in enumerate(wire_indices):
                max_idx = wire_lens[wire_group_idx]
                if curr_wire_idx != max_idx:
                    current_wire = wire_groups[wire_group_idx][curr_wire_idx]
                    joint_wire_points.extend([[p.x, p.y] for p in current_wire])
                    wire_indices[wire_group_idx] += 1
                if interp_wires is not None and not interp_done: # add custom routes if inputted by user
                    if curr_wire_idx == 0: joint_wire_points.extend([[p.x,p.y] for p in interp_wires[0]])
                    elif curr_wire_idx == max_idx - 1: joint_wire_points.extend([[p.x,p.y] for p in interp_wires[1]])
                    else:
                        interp_points = self.add_interpolation_points(curr_wire_idx, interp_wires, interp_dict)
                        joint_wire_points.extend(interp_points)
                    interp_done = True
                    
            joint_wire_points = ['{},{}'.format(p[0],p[1]) for p in joint_wire_points]
            self.create_path(joint_wire_points, is_horizontal=self.is_horizontal_connection)
    
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
        inkex.errormsg("what are points:{},{}".format(points, len(points)))
        return points

    def generate_interpolation_points(self, interpolation_wires, num_wires):
        interp_dict = {}
        for i in range(len(interpolation_wires) - 1):
            # exclude parts of interp wire that connect to sensor wire
            wire1 = interpolation_wires[i]
            wire2 = interpolation_wires[i+1]
            for j in range(1, len(wire1) - 1):
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
                points = ['{},{}'.format(p[0],p[1]) for p in line]
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
        
        connector_pins = []
        wires = []
        interpolation_wires = [] # for custom combination routing
        for elem in self.svg.get_selected():
            if type(elem) == PathElement: #connector
                points = [p for p in elem.path.end_points] 
                # if len(points) == 4: # figure out differnt condition for this
                #     connector_bbox = elem.bounding_box()
                #     connector_pins.append(elem)
                if len(points) > 2:
                    interpolation_wires.append(points)
                else:
                    wires.append(points)


        wire_groups = self.group_wires(wires)
        if len(interpolation_wires) == 0:
            self.connect_wires(wire_groups)
        else: #custom connection
            if len(interpolation_wires) > 2: # may not need to be the case in the future
                inkex.errormsg("only create two custom routes for interpolation")
                return
            else:
                # check lens of interpolation wires to make sure they are the same
                len_wire = len(interpolation_wires[0])
                same_length = all([len(w) == len_wire for w in interpolation_wires])
                if not same_length:
                    inkex.errormsg("interpolation wires have the same number of points")
                    return
                if self.is_horizontal_connection:
                    interpolation_wires = sorted(interpolation_wires, key=lambda w:-w[0].y)
                else:
                    interpolation_wires = sorted(interpolation_wires, key=lambda w:w[0].x)
                self.connect_custom_wires(wire_groups, interpolation_wires)
        
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