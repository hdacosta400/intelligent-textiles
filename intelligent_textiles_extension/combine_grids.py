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
        '''
        wire_groups = {}
        # if self.is_horizontal_connection: # wires will have same x
        for w in wires:
            points = [p for p in w.path.end_points]
            p = points[0]
            key = p.x if self.is_horizontal_connection else p.y
            if key not in wire_groups:
                wire_groups[key] = [points]
            else:
                wire_groups[key].append(points)
        for k in wire_groups:
            if self.is_horizontal_connection: # sort wires from top to bottom
                wire_groups[k] = sorted(wire_groups[k], key=lambda w:-w[0].y)
            else: # sort wires from left to right
                wire_groups[k] = sorted(wire_groups[k], key=lambda w:w[0].x)

        inkex.errormsg("num groups:{}\n\n\n".format(len(wire_groups.keys())))
        return wire_groups

                
    def connect_wires(self, wire_groups_dict):
        start_points = sorted(list(wire_groups_dict.keys()))        
        wire_groups = [wire_groups_dict[k] for k in start_points]
        wire_lens = [len(w) for w in wire_groups]
        wire_indices = [0 for _ in range(len(wire_groups))] # starting indices
        while wire_indices != wire_lens:
            joint_wire_points = []
            for i in range(len(wire_indices)):
                wire_idx = wire_indices[i]
                max_idx = wire_lens[i]
                if wire_idx != max_idx:
                    joint_wire_points.extend(wire_groups[i][wire_idx])
                    wire_indices[i] += 1
                    
            joint_wire_points = ['{},{}'.format(p.x,p.y) for p in joint_wire_points]
            self.create_path(joint_wire_points, is_horizontal=self.is_horizontal_connection)

    def run(self):
        
        connector_pins = []
        wires = []
        for elem in self.svg.get_selected():
            if type(elem) == PathElement: #connector
                points = [p for p in elem.path.end_points] 
                if len(points) == 4:
                    connector_bbox = elem.bounding_box()
                    connector_pins.append(elem)
                else:
                    wires.append(elem)


        wire_groups = self.group_wires(wires)
        self.connect_wires(wire_groups)
        
        # remove old wires
        for elem in self.svg.get_selected(): elem.getparent().remove(elem)
        return

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