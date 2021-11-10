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
        curr_point = list(self.lower_left)
        wire_count = 0
        points = []
        while round(curr_point[1]) != round(self.rectangle.top + horizontal_wire_spacing):
            curr_point[1] -= horizontal_wire_spacing
            connections = []
            if self.horizontal_wire_connector.has_available_wires():
                connections = self.horizontal_wire_connector.connect_wire()
            if wire_count % 2 == 0:
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

class Connector():
    '''
    Object to represent connector of wires
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
                rectangle = BoundingBoxMetadata(bbox.width, bbox.height, bbox.top, bbox.bottom, bbox.left, bbox.right)
                inkex.errormsg("rect points:{}".format(rectangle.get_rectangle_points()))
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

if __name__ == '__main__':
    inkex.errormsg(sys.argv[1:])
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    SensorGrid(args.horizontal_wires, args.vertical_wires).run()
