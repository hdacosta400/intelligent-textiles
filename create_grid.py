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

import numpy as np

MIN_GRID_SPACING = 2.5
BBOX_SPACING = 5

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

        self.horizontal_wire_points = None
        self.vertical_wire_points = None
    
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
    def is_horizontally_aligned(self, other):
        '''
        Verifies whether or not two bounding boxes can be
        connected horizontally

        Essentially other cannot be directly under this bbox with some buffer
        '''
        return abs(self.left - other.left) >= self.width

    def is_vertically_aligned(self, other):
        '''
        Verifies whether or not two bounding boxes can be
        connected vertically 

        Essentially other cannot be directly next to this bbox with some buffer
        '''
        return abs(self.top - other.top) >= self.height
    
    def add_wire(self, wire_points):
        '''
        If wire is contained in BBOX, adds it to object
        '''
        # wire will always go to left - BBOX_SPACING and top - BBOX_SPACING
        x_coord = self.left - BBOX_SPACING
        y_coord = self.top - BBOX_SPACING
        for point in wire_points:
            if x_coord == point.x:
                self.horizontal_wire_points = wire_points
            elif y_coord == point.y:
                self.vertical_wire_points = wire_points
    
    def get_wire_points(self, is_horizontal):
        return self.horizontal_wire_points if is_horizontal else self.vertical_wire_points
    
    def wires_grouped(self):
        inkex.errormsg("yuo yo")
        inkex.errormsg("horiz_points:{}".format(self.horizontal_wire_points))
        inkex.errormsg("vertical_points:{}".format(self.vertical_wire_points))
        return self.horizontal_wire_points is not None and self.vertical_wire_points is not None

class CreateGridFrame(wx.Frame):
    DEFAULT_FONT = "small_font"
    def __init__(self, shape_points, rectangle, svg, *args, **kwargs):
        if sys.platform.startswith('win32'):
            import locale
            locale.setlocale(locale.LC_ALL, "C")
            lc = wx.Locale()
            lc.Init(wx.LANGUAGE_DEFAULT)  
        self.shape_points = shape_points
        self.rectangle = rectangle
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
            if wire_count % 2 == 0:
                points.append('{},{}'.format(self.rectangle.left - BBOX_SPACING, curr_point[1]))
                points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                # for p in connections:
                #     points.append('{},{}'.format(p.x, p.y))
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
            if wire_count % 2 == 0:
                points.append('{},{}'.format(curr_point[0], self.rectangle.top - BBOX_SPACING))
                points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
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


class CreateGrid(InkstitchExtension):
    COMMANDS = ["create_grid"]
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        for command in self.COMMANDS:
            self.arg_parser.add_argument("--%s" % command, type=inkex.Boolean)
        self.arg_parser.add_argument("--horizontal_wires")
        self.arg_parser.add_argument("--vertical_wires")
        self.arg_parser.add_argument('args', nargs=REMAINDER)
        args, _ = self.arg_parser.parse_known_args()
        inkex.errormsg("args:{}".format(args))

    def cancel(self):
        self.cancelled = True
    
    def effect(self):

        rectangle = None
        shape_points = None
        things_selected = len(self.svg.get_selected())
        if things_selected != 1:
            inkex.errormsg("Please select only one object to create a grid for");
            return 
        
        for elem in self.svg.get_selected(): # PATH ELEMENT
            inkex.errormsg("things selected:{}".format(len(self.svg.get_selected())))
            inkex.errormsg("type of elem:{}".format(type(elem)))
            shape_points = [p for p in elem.path.end_points]
            bbox = elem.bounding_box()
            rectangle = BoundingBoxMetadata(bbox.width, bbox.height, bbox.top, bbox.bottom, bbox.left, bbox.right)
                

        # if shape_points is not None and rectangle is not None and len(connectors) > 0:
        app = wx.App()
        frame = CreateGridFrame(shape_points, rectangle, self.svg, on_cancel=self.cancel)

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
        


# if __name__ == '__main__':
#     inkex.errormsg(sys.argv[1:])
#     parser = ArgumentParser()
#     parser.add_argument("--horizontal_wires")
#     parser.add_argument("--vertical_wires")
#     parser.add_argument('args', nargs=REMAINDER)
#     args, _ = parser.parse_known_args()
#     inkex.errormsg("args:{}".format(args))
#     # CreateGrid(args.horizontal_wires, args.vertical_wires).run()