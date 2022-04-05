from argparse import ArgumentParser
from ast import Return
from tokenize import group
import inkex
from inkex import Polyline, PathElement
from lxml import etree
from sympy import Segment, Point
from wiredb_proxy import WireDBProxy

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
		self.wiredb_proxy = WireDBProxy()
		self.interp_wire_helper = None


	def group_wires(self, wires):
		'''
		Wires in the same grid are currently disjoint from each other
		Need to group them together so they get connected together
		Need to fix this for when wire groups are angled (Same x/y won't apply)

		'''

		wire_groups = {}
		wire_ids = [wire.get_id() for wire in wires]
		id_to_wire = {wire.get_id() : wire for wire in wires}
		wires_allocated = []

		while len(wires_allocated) != len(wire_ids):
			for idx, w_id in enumerate(wire_ids):
				if w_id not in wires_allocated:
					wire_group = self.wiredb_proxy.retrieve_wire_group_with_id(w_id)
					if wire_group == []: # interpolation wire!
						inkex.errormsg("points of interp wire @ group detetction:{}".format(len([[p.x,p.y] for p in wires[idx].path.end_points])))
						self.interpolation_wires.append(wires[idx])
						wires_allocated.append(wires[idx])
					else:
						if self.is_horizontal_connection: # sort wire ids from top to bottom
							wire_group = sorted(wire_group, key=lambda w:-[p for p in id_to_wire[w].path.end_points][0].y)
						else: # sort wire ids from left to right
							wire_group = sorted(wire_group, key=lambda w: [p for p in id_to_wire[w].path.end_points][0].x)

						wire_groups[min(wire_group)] = [id_to_wire[id] for id in wire_group] # get wire object of id
						wires_allocated.extend(wire_group)
		
		# inkex.errormsg("num interp wires detected:{}".format(len(self.interpolation_wires)))
		tmp_wires = [w for w in self.wires if w not in self.interpolation_wires]
		self.wires = tmp_wires
		return wire_groups

				
	def arrange_wire_groups(self, wire_groups_dict):
		'''
		Before connecting wire groups, we first need to arrange them 
		from left -> right for horizontal connections and top -> bottom for 
		vertical connections

		returns: list of keys in wire_groups dict sorted by this order
		'''
		key_wirepoint_pairs = [] # list of (key, first wire point in key group)
		for key in wire_groups_dict.keys():
			wire1_points = [p for p in wire_groups_dict[key][0].path.end_points]
			key_wirepoint_pairs.append((key, wire1_points[0]))
		if self.is_horizontal_connection: # left to right
			key_wirepoint_pairs = sorted(key_wirepoint_pairs, key=lambda p: p[1].x)
		else:
			key_wirepoint_pairs = sorted(key_wirepoint_pairs, key=lambda p: -p[1].y)
		
		return [k for k,_ in key_wirepoint_pairs]
	

	def connect_wires(self, wire_groups_dict, interp_wires=None, interp_dict=None, interp_start_indices=None):
		arranged_group_keys = self.arrange_wire_groups(wire_groups_dict)     # list of group ids sorted
		wire_groups = [wire_groups_dict[k] for k in arranged_group_keys] # list of wire groups (which is a list of wires)
		wire_lens = [len(w) for w in wire_groups] # list of (number of wires) for each wire group
		wire_indices = [0 for _ in range(len(wire_groups))] # list of current wire indices for each wire group
		generated_combined_wires = []
		generated_ids = []
		while wire_indices != wire_lens:
			joint_wire_points = []
			for wire_group_idx, curr_wire_idx in enumerate(wire_indices):
				max_idx = wire_lens[wire_group_idx]
				group_key = arranged_group_keys[wire_group_idx]
				if curr_wire_idx != max_idx: # add the wire itself
					current_wire = wire_groups[wire_group_idx][curr_wire_idx]
					joint_wire_points.extend([[p.x, p.y] for p in current_wire.path.end_points])
					wire_indices[wire_group_idx] += 1
	
				# range where interpolation routing is present
				start, end = self.interp_wire_helper.is_in_group_interpolation_range(group_key, curr_wire_idx)
				if start is not None: # we are in interpolation range!
					inkex.errormsg("IN interp range!")
					interp_points = self.interp_wire_helper.get_custom_interpolation_route(group_key, start, end, curr_wire_idx)
					joint_wire_points.extend(interp_points)

			generated_combined_wires.append(joint_wire_points)       
			joint_wire_points = ['{},{}'.format(p[0],p[1]) for p in joint_wire_points]
			elem = self.create_path(joint_wire_points, is_horizontal=self.is_horizontal_connection)
			generated_ids.append(elem.get_id())

		# generate new grouping of wires
		self.wiredb_proxy.insert_new_wire_group(generated_ids)

		# can move this block before to prevent drawing of wires
		is_valid_routing = self.has_valid_interpolation_points(generated_combined_wires)
		if not is_valid_routing:
			inkex.errormsg("Please change your template routing wires.")
			return

	def connect_custom_wires(self, wire_groups_dict):
		# how many wires are grouped together???
		num_wires = len(wire_groups_dict[list(wire_groups_dict.keys())[0]])
		interpolation_wires = [[p for p in w.path.end_points] for w in self.interpolation_wires]
		interp_dict = self.generate_interpolation_points(interpolation_wires, num_wires)

		# determine the wiregroups where the interpolation wires start
		# interp_start_indices = self.calculate_interp_wire_group(wire_groups_dict, interpolation_wires)
		self.connect_wires(wire_groups_dict, interpolation_wires, interp_dict, interp_start_indices=None) 

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
		'''
		Find where interpolation wires start on a wire group
		(and where they end on another?)
		'''
		start_points = sorted(list(wire_groups_dict.keys()))
		interp_start_indices = []
		for sp in start_points:
			for wire_idx, wire in enumerate(wire_groups_dict[sp]):
			# assumption that interpolation wire starts at END of a wire
				for w in interpolation_wires:
					if wire[-1].x == w[0][0] and wire[-1].y == w[0][1]:
						interp_start_indices.append((sp,wire_idx))

		return interp_start_indices
 


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
				# inkex.errormsg("\n\n\IDs:{}".format(elem.get_id()))
				self.wires.append(elem)

		wire_groups = self.group_wires(self.wires)
		if len(self.interpolation_wires) != 0: #custom connection			
			# sort interpolation wires
			interp_wire_points = []
			interp_wire_dict = {}
			for interp in self.interpolation_wires:
				points = [p for p in interp.path.end_points]
				interp_wire_points.append(points)
				interp_wire_dict[interp] = points
			if self.is_horizontal_connection:
				interp_wire_points = sorted(interp_wire_points, key=lambda w:-w[0].y)
			else:
				interp_wire_points = sorted(interp_wire_points, key=lambda w:w[0].x)
			
			tmp_interp_wires = []
			for p in interp_wire_points:
				# find the wire that set of points corresponds to 
				for key in interp_wire_dict.keys():
					if interp_wire_dict[key] == p:
						tmp_interp_wires.append(key)
			self.interpolation_wires = tmp_interp_wires
			# construct helper class to deal with custom routing logic 
			self.interp_wire_helper = InterpolationWires(self.interpolation_wires, wire_groups)
		self.connect_wires(wire_groups)
		
		# remove old wires
		old_wire_ids = [elem.get_id() for elem in self.svg.get_selected()]
		# self.wiredb_proxy.delete_wire_groups_with_id(old_wire_ids)
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
		
		elem = etree.SubElement(self.svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)  
		return elem

	
class ConnectionObject():
	'''
	Object representing the group where an interpolation wire starts
	'''
	def __init__(self, group1, group1_idx):
		self.group1 = group1
		self.group1_idx = group1_idx # wire index of group that interpolation wire is connected to 

class InterpolationWires():
	def __init__(self, interpolation_wires, wire_groups_dict):
		'''
		interpolation_wires: list of elements representing wires
		wire_groups_dict: dict mapping wire_id to a grouping of wires
		'''
		self.interpolation_wires = interpolation_wires
		self.wire_groups_dict = wire_groups_dict
		self.group_interpolation_ranges = {} # maps group id to the indices where an interpolation point starts
		# dict mapping interpolation wire id to ConnectionObject
		self.group_connections = {}
		#dict mapping g_key, start_idx, end_idx to list of interpolation points to use
		self.interp_points_dict = {} 
		self.determine_group_connections()
		self.generate_interpolation_points()


	def localize_interpolation_wire(self, start_point):
		inkex.errormsg("\n\n start point of interp: {} \n\n".format(start_point))
		for g_key in self.wire_groups_dict.keys():
			wire_group = self.wire_groups_dict[g_key]
			for wire_idx, wire_elem in enumerate(wire_group):
				wire_points = [p for p in wire_elem.path.end_points]
				wire_start = wire_points[0]
				wire_end = wire_points[-1]
				inkex.errormsg("\n\nstart end {}  {}\n\n".format(wire_start, wire_end))
				def check_same_point(p1, p2):
					return round(p1.x, 2) == round(p2.x, 2) and round(p1.y, 2) == round(p2.y, 2)
				inkex.errormsg(round(start_point.x,2) == round(wire_end.x,2) and round(start_point.y,2) == round(wire_end.y, 2))
				if check_same_point(start_point, wire_start) or check_same_point(start_point, wire_end):
					inkex.errormsg("FOUND A WIRE!")
					if g_key not in self.group_interpolation_ranges:
						self.group_interpolation_ranges[g_key] = []
					self.group_interpolation_ranges[g_key].append(wire_idx)
					# interpolation wire has been localized
					return g_key, wire_idx
		return None, None 

	def determine_group_connections(self):
		'''
		Calculate the groups that each interpolation wire is connecting
		'''
		for w in self.interpolation_wires:
			points = [p for p in w.path.end_points]
			start_point = points[0]
			end_point = points[-1]
			group1 = None
			group1_idx = None

			# now look over all wire groups
			group1, group1_idx = self.localize_interpolation_wire(start_point)
			if group1 is None:
				inkex.errormsg("Please make sure to connect custom wires to endpoints in the wire group")
			else:
				self.group_connections[w.get_id()] = (group1, group1_idx)

		inkex.errormsg("what is ranges:{}".format(self.group_interpolation_ranges))

	def get_group_interpolation_range(self, g_key):
		'''
		Returns the indices in a wire group where interpolation wires start from
		'''
		if g_key in self.group_interpolation_ranges:
			return sorted(self.group_interpolation_ranges[g_key])
		return []
	
	def is_in_group_interpolation_range(self, g_key, wire_idx):
		if g_key in self.group_interpolation_ranges:
			index_ranges = sorted(self.group_interpolation_ranges[g_key])
			for i in range(len(index_ranges) - 1):
				start = index_ranges[i]
				end = index_ranges[i+1]
				if start <= wire_idx <= end:
					return start,end
		return None, None	

	def is_group_wire_interpolation_start_point(self, g_key, wire_idx):
		'''
		Determines if a wire in a wire group is a START point for an interpolation wire
		'''
		if g_key in self.group_interpolation_ranges:
			return wire_idx in self.group_interpolation_ranges[g_key]
		return False

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

	def generate_interpolation_points(self):
		'''
		populates self.interp_points_dict,
		which maps every pair of interpolation points connecting two wire groups to the list of wires needed

		TODO: MAKE THIS DOCUMENTATION CLEARER
		'''
		interp_dict = {}
		# if g_key in self.group_interpolation_ranges.keys():
		# 	interp_range = self.group_interpolation_ranges[g_key]
		# 	if start_idx in interp_range and end_idx in interp_range:
		for g_key in self.group_interpolation_ranges.keys(): # for every group
			interp_range = self.group_interpolation_ranges[g_key] # get interpolation range
			inkex.errormsg("\n\nwhat is interp range:{}".format(interp_range))
			for i in range(len(interp_range) - 1): # go over interp wires in pairs
				start_idx = interp_range[i] # first wire index
				end_idx = interp_range[i+1] # second wire index
				# find the wire objects starting at these indices
				def find_wire(g_key, wire_idx):
					for interp_id in self.group_connections.keys():
						if self.group_connections[interp_id] == (g_key, wire_idx): # if there is an interpolation wire found at group & index
							interp_id_list = [wire.get_id() for wire in self.interpolation_wires]
							return self.interpolation_wires[interp_id_list.index(interp_id)]
					return None
				start_interp_wire = find_wire(g_key, start_idx)
				end_interp_wire = find_wire(g_key, end_idx)
				start_interp_wire_points = [p for p in start_interp_wire.path.end_points]
				end_interp_wire_points = [p for p in end_interp_wire.path.end_points]
				inkex.errormsg("interp wire points: {} \n\n {}".format(start_interp_wire_points, end_interp_wire_points))
				num_wires = end_idx - start_idx + 1
				# generate interpolation points between the two wires
				for point_idx in range(1, len(start_interp_wire_points) - 1): # exclude parts of interp wire that connect to sensor wire
					x1, y1 = start_interp_wire_points[point_idx].x, start_interp_wire_points[point_idx].y
					x2, y2 = end_interp_wire_points[point_idx].x, end_interp_wire_points[point_idx].y
					line = [[x1, y1], [x2, y2]] 
					interp_dict[(x1, y1, x2, y2)] = [[x1, y1]] # map these points to the line connecting corresponding points
					interp_points = self.segment_line(line, num_wires - 2) # partition the line into num_wires parts
					interp_dict[(x1, y1, x2, y2)].extend(interp_points)

				# we now have a dict of interpolation points, mapping each pair of points
				# on interpolation wires to the interpolated points between them

				# we know want to map g_key, start_idx, end_idx to each interpolation WIRE
				# this requires that we iterate over interp_dict point pairs and combine
				# corresponding indices
				self.interp_points_dict[(g_key, start_idx, end_idx)] = []
				for idx in range(0, num_wires):
					wire_points = []
					if idx == 0: # need to add first interpolation wire
						# exclude first and last point so as not to double count points on group wires
						wire_points = [[p.x,p.y] for p in start_interp_wire_points[1:len(start_interp_wire_points)-1]]
					elif idx == num_wires - 1:						
						# exclude first and last point so as not to double count points on group wires
						wire_points = [[p.x,p.y] for p in end_interp_wire_points[1:len(start_interp_wire_points)-1]]
					else: # we are within range
						for j in range(1, len(start_interp_wire_points) - 1):
							x1, y1 = start_interp_wire_points[j].x, start_interp_wire_points[j].y
							xn, yn = end_interp_wire_points[j].x , end_interp_wire_points[j].y
							interpolation_points = interp_dict[(x1,y1,xn,yn)]
							wire_points.append(interpolation_points[idx])
					
					self.interp_points_dict[(g_key, start_idx, end_idx)].append(wire_points)
		return None # should never get here

	def get_custom_interpolation_route(self, g_key, start_idx, end_idx, wire_idx):
		# re adjust indices to 0 
		return self.interp_points_dict[(g_key, start_idx, end_idx)][wire_idx - start_idx]



if __name__ == '__main__':
	CombineGridsEffect().run()