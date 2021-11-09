from .base import InkstitchExtension
import json
import os
import sys
from base64 import b64decode
from argparse import ArgumentParser, REMAINDER

import appdirs
import inkex
from inkex import Line, Rectangle, Path
import wx
import wx.adv
from lxml import etree

from ..elements import nodes_to_elements
from ..gui import PresetsPanel, SimulatorPreview, info_dialog
from ..i18n import _
from ..lettering import Font, FontError
from ..svg import get_correction_transform
from ..svg.tags import (INKSCAPE_LABEL, INKSTITCH_LETTERING, SVG_GROUP_TAG,
                        SVG_PATH_TAG)
from ..utils import DotDict, cache, get_bundled_dir, get_resource_dir
from .commands import CommandsExtension
from .lettering_custom_font_dir import get_custom_font_dir

import svgwrite
from svgwrite.extensions import Inkscape
import numpy as np

# minimum space apart for wires in grid to avoid interference / shorting
MIN_GRID_SPACING = 2.5
BBOX_SPACING = 5
class SensorGridFrame(wx.Frame):
    DEFAULT_FONT = "small_font"
    def __init__(self, shape_points, rectangle, wire_connector, svg, *args, **kwargs):
        if sys.platform.startswith('win32'):
            import locale
            locale.setlocale(locale.LC_ALL, "C")
            lc = wx.Locale()
            lc.Init(wx.LANGUAGE_DEFAULT)  
        self.shape_points = shape_points
        self.rectangle = rectangle
        self.vertical_wire_connector, self.horizontal_wire_connector = wire_connector
        self.upper_left, self.upper_right, self.lower_left, self.lower_right = self.rectangle.get_rectangle_points()
        self.svg = svg
        self.paths = []
        
        self.cancel_hook = kwargs.pop('on_cancel', None)
        wx.Frame.__init__(self, None, wx.ID_ANY,
                          _("Ink/Stitch Sensor Grid")
                          ) 
        self.preview = SimulatorPreview(self, target_duration=1)
        # self.presets_panel = PresetsPanel(self)

        self.vertical_wire_spinner = wx.SpinCtrl(self, wx.ID_ANY, min = 1, initial = 1);
        self.vertical_wire_spinner.Bind(wx.EVT_SPINCTRL, lambda event: self.on_change("vertical_wires", event))

        self.horizontal_wire_spinner = wx.SpinCtrl(self, wx.ID_ANY, min = 1, initial = 1);
        self.horizontal_wire_spinner.Bind(wx.EVT_SPINCTRL, lambda event: self.on_change("horizontal_wires", event))

        self.horizontal_wire = None
        self.vertical_wire = None

        self.cancel_button = wx.Button(self, wx.ID_ANY, _("Cancel"))
        self.cancel_button.Bind(wx.EVT_BUTTON, self.cancel)
        self.Bind(wx.EVT_CLOSE, self.cancel)

        self.apply_button = wx.Button(self, wx.ID_ANY, _("Apply and Quit"))
        self.apply_button.Bind(wx.EVT_BUTTON, self.apply)

        self.__do_layout()
        self.load_settings()
        self.apply_settings()

    
    def load_settings(self):
        """
        Load settings into SVG Group element
        """
        self.settings = DotDict({
            "vertical_wires": 0,
            "horizontal_wires": 0
        })
    
    def apply_settings(self):
        self.vertical_wire_spinner.SetValue(self.settings.vertical_wires)
        self.horizontal_wire_spinner.SetValue(self.settings.horizontal_wires)


    def on_change(self, attribute, event):
        self.settings[attribute] = event.GetEventObject().GetValue()
        self.preview.update() 


    def apply(self, event):
        self.preview.disable()
        self.create_grid_layout()
        # self.save_settings()
        self.close()

    def create_grid_layout(self):
        # check vertical and horizontal spacing
        total_horizontal_spacing = self.rectangle.height / (self.horizontal_wire_spinner.GetValue() + 1)
        total_vertical_spacing = self.rectangle.width / (self.vertical_wire_spinner.GetValue() + 1)
        # can only actually add wires within boundaries of rectangle
        horizontal_wire_spacing = (self.rectangle.height - total_horizontal_spacing) / self.horizontal_wire_spinner.GetValue()
        vertical_wire_spacing = (self.rectangle.width - total_vertical_spacing) / self.vertical_wire_spinner.GetValue()
        if (horizontal_wire_spacing < MIN_GRID_SPACING):
            inkex.errormsg('''The horizontal wires must be at least {} mm apart
                            They are currently {} mm apart. Either decrease the
                            number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, horizontal_wire_spacing))
            return
        if (vertical_wire_spacing < MIN_GRID_SPACING):
            inkex.errormsg('''The vertical wires must be at least {} mm apart 
                            They are currently {} mm apart. Either decrease the
                            number of wires or increase the size of the grid and try again.'''.format(MIN_GRID_SPACING, vertical_wire_spacing))
            return
        self.lay_horizontal_wires(total_horizontal_spacing)
        self.lay_vertical_wires(total_vertical_spacing)

    def lay_horizontal_wires(self, horizontal_wire_spacing):
        '''
        vert spacing:2.9, curr_point_top: 26.509441, bottom: 38.099998

         4 curr_point_top: 38.09999799999999, bottom: 38.099998
        '''
        curr_point = list(self.lower_left)
        wire_count = 0
        points = []
        while round(curr_point[1]) != round(self.rectangle.top + horizontal_wire_spacing):
            curr_point[1] -= horizontal_wire_spacing
            connections = []
            if self.horizontal_wire_connector.has_available_wires():
                connections = self.horizontal_wire_connector.connect_wire()
            if wire_count % 2 == 0:
            # self.create_wire_segment(curr_point, self.rectangle.width, True)
                points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
                points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                for p in connections:
                    points.append('{},{}'.format(p.x, p.y))
            else:
                points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))

            wire_count += 1

        self.create_path(points, is_horizontal=True)

    def lay_vertical_wires(self, vertical_wire_spacing):
        curr_point = list(self.upper_left)
        wire_count = 0
        points = []
        while round(curr_point[0]) != round(self.rectangle.right - vertical_wire_spacing):
            curr_point[0] += vertical_wire_spacing
            connections = []
            if self.vertical_wire_connector.has_available_wires():
                connections = self.vertical_wire_connector.connect_wire()
            if wire_count % 2 == 0:
                points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
                points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
                for p in connections:
                    points.append('{},{}'.format(p.x, p.y))
            else:
                points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
                points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
            
            wire_count += 1

        
        inkex.errormsg("vertical points:{}".format(points))
        self.create_path(points, is_horizontal=False)

    def create_path(self, points, is_horizontal):
        '''
        Creates a wire segment path given all of the points sequentially
        '''
        color = "red" if is_horizontal else "blue"
        path_str = ' '.join(points)
        path = inkex.Polyline(attrib={
        'id': "wire_segment",
        'style': "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
        'points': path_str,
        # 'transform': inkex.get_correction_transform(svg),
        })
        self.svg.get_current_layer().append(path)
        # store wire objects for future use
        if is_horizontal:
            self.horizontal_wire = path
        else:
            self.vertical_wire = path

    def close(self):
        self.preview.close()
        self.Destroy()

    def cancel(self, event):
        if self.cancel_hook:
            self.cancel_hook()

        self.close()
    
    def __do_layout(self):
        outer_sizer = wx.BoxSizer(wx.VERTICAL)
        wire_sizer = wx.BoxSizer(wx.HORIZONTAL)
        wire_sizer.Add(wx.StaticText(self, wx.ID_ANY, "Number of vertical wires"), 0, wx.LEFT | wx.ALIGN_CENTRE_VERTICAL, 0)
        wire_sizer.Add(self.vertical_wire_spinner, 0, wx.LEFT, 10)
        wire_sizer.Add(wx.StaticText(self, wx.ID_ANY, "Number of horizontal wires"), 0, wx.LEFT | wx.ALIGN_CENTRE_VERTICAL, 0)
        wire_sizer.Add(self.horizontal_wire_spinner, 0, wx.LEFT, 10)
        outer_sizer.Add(wire_sizer, 0, wx.EXPAND | wx.LEFT | wx.TOP | wx.RIGHT, 10)


        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        buttons_sizer.Add(self.cancel_button, 0, wx.RIGHT, 10)
        buttons_sizer.Add(self.apply_button, 0, wx.RIGHT | wx.BOTTOM, 10)
        outer_sizer.Add(buttons_sizer, 0, wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer_sizer)
        self.Layout()
        size = self.GetSize()
        size.height = size.height + 200
        self.SetSize(size)

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


        # [(228.1611254982255, 926.1796798412221),
        # (318.94651979684267, 926.1796798412221),
        # (228.1611254982255, 958.3789548850492), 
        # (318.94651979684267, 958.3789548850492)]
    
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
    def get_rectangle_path(self):
        '''
        get polyline path to draw rectangle
        '''
        ul, ur, ll, lr = self.get_rectangle_points()
        rectangle_sides = []
        rectangle_sides.append('{},{}'.format(ul[0], ul[1]))
        rectangle_sides.append('{},{}'.format(ur[0], ul[1]))
        rectangle_sides.append('{},{}'.format(lr[0], lr[1]))
        rectangle_sides.append('{},{}'.format(ll[0], ll[1]))
        rectangle_sides.append('{},{}'.format(ul[0], ul[1])) 
        return rectangle_sides

class Connector():
    '''
    Object to represent connector of wires

    IF:
    x a b c d
    ^
    every connector has 32 connection points
    I can split a list of 64 in HALF for vertical and horizontal
    Impose constraint where first half is always for vert and second is always for horz
    '''
    def __init__(self, connector_points):
        self.connector_points = connector_points # all coords where wires need to route to 
        self.open_wire_idx = 0 # idx of next available wire
        inkex.errormsg("num connectors:{}".format(len(self.connector_points)))
    def has_available_wires(self):
        return self.open_wire_idx <= len(self.connector_points) - 4 # every connector is 4 points
    def connect_wire(self):
        if self.has_available_wires():
            points = self.connector_points[self.open_wire_idx:self.open_wire_idx + 4]
            self.open_wire_idx += 2
            return points
        else:
            inkex.errormsg("connector has no more open connections. Decrease the number of wires!")
            return None



class SensorGrid(InkstitchExtension):
    COMMANDS = ["grid"]
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        for command in self.COMMANDS:
            self.arg_parser.add_argument("--%s" % command, type=inkex.Boolean)
    def cancel(self):
        self.cancelled = True
    def effect(self):

        rectangle = None
        shape_points = None
        connector_points = []
        connectors = [] # list of connector objects
        for elem in self.svg.get_selected(): # PATH ELEMENT
            '''
            need this for loop for when multiple elements are selected (object , 2 connectors[?])
            for now it is just the object itself
            '''
            inkex.errormsg("things selected:{}".format(len(self.svg.get_selected())))
            inkex.errormsg("type of elem:{}".format(type(elem)))
            shape_points = [p for p in elem.path.end_points]
            inkex.errormsg("points:{},{}".format(shape_points,len(shape_points)))
            

            if len(shape_points) > 4 and rectangle is None: # use bounding box of OBJECT 
                #for now, this will differentiate the OBJECT from the CONNECTORS
                bbox = elem.bounding_box()
                self.parse_poly_points(shape_points, bbox)
                rectangle = BoundingBoxMetadata(bbox.width, bbox.height, bbox.top, bbox.bottom, bbox.left, bbox.right)
                inkex.errormsg("rect points:{}".format(rectangle.get_rectangle_points()))
                '''
                rect points:[(228.1611254982255, 926.1796798412221),
                 (318.94651979684267, 926.1796798412221),
                  (228.1611254982255, 958.3789548850492), 
                  (318.94651979684267, 958.3789548850492)]
                '''
            elif len(shape_points) == 4:
                # first and last points represent the ends that will be used for routing!
                for p in shape_points:
                    connector_points.append(p)
                if len(connector_points) == 64: # num of points making up a connector
                    connectors.append(Connector(connector_points))
                    connector_points = []
                

        # if shape_points is not None and rectangle is not None and len(connectors) > 0:
        if True:
            app = wx.App()
            frame = SensorGridFrame(shape_points, rectangle, connectors, self.svg, on_cancel=self.cancel)

            # position left, center
            current_screen = wx.Display.GetFromPoint(wx.GetMousePosition())
            display = wx.Display(current_screen)
            display_size = display.GetClientArea()
            frame_size = frame.GetSize()
            frame.SetPosition((int(display_size[0]), int(display_size[3] / 2 - frame_size[1] / 2)))

            frame.Show()
            app.MainLoop()

            if self.cancelled:
                # This prevents the superclass from outputting the SVG, because we
                # may have modified the DOM.
                sys.exit(0)
        else:
            inkex.errormsg("Please make sure the shape and its connectors are selected!")
            return

    def parse_poly_points(self, points, bbox):
        '''
        Gets point information about an arbitrary 2D shape

        '''
        '''
         path:m 317.78536,934.4352 c -0.67685,-1.25744 -1.67024,-2.34352 -2.78632,-3.25714 -1.25632,-1.02842 -2.66812,-1.83832 -4.15539,-2.45201 -1.78985,-0.73855 -3.68901,-1.19293 -5.59631,-1.54834 -1.81005,-0.33729 -3.62744,-0.58546 -5.45846,-0.75544 -2.89029,-0.26831 -5.81456,-0.3418 -8.69802,-0.0783 -3.90247,0.35659 -7.73021,1.33038 -11.55644,2.24417 -1.97806,0.4724 -3.95572,0.92877 -5.92383,1.3954 -2.44397,0.57946 -4.87322,1.17475 -7.37128,1.66696 -2.2786,0.44898 -4.61444,0.81219 -6.87236,0.53902 -2.51982,-0.30485 -4.9426,-1.40227 -7.39733,-2.11244 -2.72794,-0.7892 -5.49534,-1.10014 -8.40369,-1.57114 -2.85905,-0.46302 -5.85431,-1.08072 -8.4021,-0.19688 -4.01143,1.3916 -6.9136,6.50551 -7.00068,11.22902 -0.0536,2.90687 0.95896,5.66588 2.81869,7.63997 1.13362,1.20333 2.58202,2.11502 4.10168,2.79571 3.37999,1.514 7.11249,1.88533 10.77209,2.4194 2.45185,0.35782 4.87097,0.78869 7.29639,1.21498 2.7619,0.48544 5.53197,0.96494 8.29565,1.4592 2.61337,0.46738 5.22101,0.94795 7.82848,1.46784 3.24613,0.64723 6.49199,1.35537 9.77656,1.65601 3.44322,0.31517 6.92899,0.1825 10.39475,-0.0256 4.59811,-0.27614 9.16098,-0.68514 13.64707,-1.98754 4.72529,-1.37185 9.36539,-3.73493 12.42144,-7.53161 1.79698,-2.23246 3.04628,-4.96059 3.35586,-7.85478 0.23373,-2.18499 -0.0682,-4.46463 -1.08645,-6.3564
         z, style:fill:none;stroke:#000000;stroke-width:0.9;stroke-linecap:rou

        m dx dy (starting point)
        c dx1 dy1, dx2 dy2, dx dy (slope @ beginning, slope @ end, ending point of line)

        only care about point right after m and every THIRD point after c?
        '''
        # points = [p for p in shapeElement.path.end_points]
        path = []
        for p in points:
            path.append('{},{}'.format(p.x, p.y)) # this gives me the points!
        rect = BoundingBoxMetadata(bbox.width, bbox.height, bbox.top, bbox.bottom, bbox.left, bbox.right)
        corners = rect.get_rectangle_path()

    def create_path(self, points, color):
        '''
        Creates a wire segment path given all of the points sequentially
        '''
        # color = "red" if is_horizontal else "blue"
        path_str = ' '.join(points)
        path = inkex.Polyline(attrib={
        'id': "wire_segment",
        'style': "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
        'points': path_str,
        # 'transform': inkex.get_correction_transform(svg),
        })
        self.svg.get_current_layer().append(path)

if __name__ == '__main__':
    inkex.errormsg(sys.argv[1:])
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    SensorGrid(args.horizontal_wires, args.vertical_wires).run()




'''
Code Archive

Clean this up later when something works
'''

   # OLD DISJOINT CODE -- will save just in case it is needed for routing???
    # def create_wire_segment(self, start_point, length, is_horizontal):
    #     color = "red" if is_horizontal else "blue"
    #     direction = "h" if is_horizontal else "v"
    #     # length = self.rectangle.width if is_horizontal else self.rectangle.height
    #     path = inkex.PathElement(attrib={
    #     'id': "wire_segment",
    #     'style': "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
    #     'd': "m {},{} {} {} ".format(str(start_point[0]), str(start_point[1]), direction, length),
    #     # 'transform': inkex.get_correction_transform(svg),
    #     })
    #     self.svg.get_current_layer().append(path)
    
    
    # def create_wire_joiner(self, start_point, length, is_horizontal):
    #     '''
    #     joins two wires going in the same direction for continuous sowing
    #     '''
    #     color = "blue" if is_horizontal else "red"
    #     direction = "h" if is_horizontal else "v"
    #     path = inkex.PathElement(attrib={
    #     'id': "wire_segment",
    #     'style': "stroke: %s; stroke-width: 0.4; fill: none; stroke-dasharray:0.4,0.4" % color,
    #     'd': "m {},{} {} {} ".format(str(start_point[0]), str(start_point[1]), direction, length),
    #     # 'transform': inkex.get_correction_transform(svg),
    #     })
    #     self.svg.get_current_layer().append(path)