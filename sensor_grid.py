from .base import InkstitchExtension
import json
import os
import sys
from base64 import b64decode
from argparse import ArgumentParser, REMAINDER

import appdirs
import inkex
from inkex import Line, Rectangle
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

# minimum space apart for wires in grid to avoid interference / shorting
MIN_GRID_SPACING = 2.5
class SensorGridFrame(wx.Frame):
    DEFAULT_FONT = "small_font"
    def __init__(self, rectangle, svg, *args, **kwargs):
        if sys.platform.startswith('win32'):
            import locale
            locale.setlocale(locale.LC_ALL, "C")
            lc = wx.Locale()
            lc.Init(wx.LANGUAGE_DEFAULT)  
        # self.group = kwargs.pop('group')
        # self.parent_node = parent_node
        self.rectangle = rectangle
        self.upper_left, self.upper_right, self.lower_left, self.lower_right = self.rectangle.get_rectangle_points()
        self.svg = svg
        self.paths = []
        


        inkex.errormsg("dims in GUI: {} x {}".format(self.rectangle.width, self.rectangle.height))

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
        self.lay_horizontal_wires(total_horizontal_spacing)
        self.lay_vertical_wires(total_vertical_spacing)

    def lay_horizontal_wires(self, horizontal_wire_spacing):
        '''
        vert spacing:2.9, curr_point_top: 26.509441, bottom: 38.099998

         4 curr_point_top: 38.09999799999999, bottom: 38.099998
        '''
        curr_point = list(self.upper_left)
        inkex.errormsg("vert spacing:{}, curr_point_top: {}, bottom: {}".format(horizontal_wire_spacing, curr_point[1], self.rectangle.bottom))
        wire_count = 0
        points = []
        while round(curr_point[1]) != round(self.rectangle.bottom - horizontal_wire_spacing):
            curr_point[1] += horizontal_wire_spacing
            inkex.errormsg(" 1 curr_point_top: {}, bottom: {}".format(curr_point[1], self.rectangle.bottom))
            # self.create_wire_segment(curr_point, self.rectangle.width, True)
            points.append('{},{}'.format(curr_point[0], curr_point[1]))
            wire_count += 1
            if wire_count < self.horizontal_wire_spinner.GetValue(): # avoid last wire to prevent shorting
                if wire_count % 2 == 1: # need to draw joining segment on right side
                    # self.create_wire_joiner([self.rectangle.right, curr_point[1]], horizontal_wire_spacing, is_horizontal=False)
                    points.append('{},{}'.format(self.rectangle.right, curr_point[1]))
                    points.append('{},{}'.format(self.rectangle.right, curr_point[1] + horizontal_wire_spacing))
                else: # need to draw joining segment on left side
                    # self.create_wire_joiner([self.rectangle.left, curr_point[1]], horizontal_wire_spacing, is_horizontal=False)
                    points.append('{},{}'.format(self.rectangle.left, curr_point[1]))
                    points.append('{},{}'.format(self.rectangle.left, curr_point[1] + horizontal_wire_spacing))
        inkex.errormsg("points:{}".format(points))
        self.create_path(points, is_horizontal=True)

    def lay_vertical_wires(self, vertical_wire_spacing):
        curr_point = list(self.upper_left)
        inkex.errormsg("vert spacing:{}, curr_point_top: {}, bottom: {}".format(vertical_wire_spacing, curr_point[1], self.rectangle.right))
        wire_count = 0
        points = []
        while round(curr_point[0]) != round(self.rectangle.right - vertical_wire_spacing):
            curr_point[0] += vertical_wire_spacing
            points.append('{},{}'.format(curr_point[0], curr_point[1]))
            inkex.errormsg(" 1 curr_point_top: {}, bottom: {}".format(curr_point[0], self.rectangle.right))
            # self.create_wire_segment(curr_point, self.rectangle.height, False)
            wire_count += 1
            if wire_count < self.vertical_wire_spinner.GetValue():
                if wire_count % 2 == 1: # need to draw joining segment on bottom side
                    # self.create_wire_joiner([curr_point[0], self.rectangle.bottom], vertical_wire_spacing, is_horizontal=True)
                    points.append('{},{}'.format(curr_point[0], self.rectangle.bottom))
                    points.append('{},{}'.format(curr_point[0] + vertical_wire_spacing, self.rectangle.bottom))
                else: # need to draw joining segment on top side
                    # self.create_wire_joiner([curr_point[0], self.rectangle.top], vertical_wire_spacing, is_horizontal=True)
                    points.append('{},{}'.format(curr_point[0], self.rectangle.top))
                    points.append('{},{}'.format(curr_point[0] + vertical_wire_spacing, self.rectangle.top))
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
            
    # OLD DISJOING CODE -- will save just in case it is needed for routing???
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

class RectangleMetadata():
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
    
class SensorGrid(InkstitchExtension):
    COMMANDS = ["grid"]
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        for command in self.COMMANDS:
            self.arg_parser.add_argument("--%s" % command, type=inkex.Boolean)
        # self.arg_parser.add_argument("--horizontal_wires")
        # self.arg_parser.add_argument("--vertical_wires")
        # self.num_horizontal_wires = self.options.horizontal_wires
        # self.num_vertical_wires = self.options.vertical_wires
        # inkex.errormsg("params:{}, {}".format(self.num_horizontal_wires, self.num_vertical_wires))


    def cancel(self):
        self.cancelled = True
    def effect(self):

        # if not self.svg.selected:
        #     inkex.errormsg(_("Please select a single rectangle to apply a grid."))
        #     return

        # get dims of user's grid in MM (for now, have users select mm as measurement)
        # TODO: do conversion for later version??
        rectangle = None

        for elem in self.svg.get_selected():
            if not isinstance(elem, Rectangle):
                inkex.errormsg("type of elem:{}, path:{}, style:{}".format(type(elem), elem.get_path(), elem.style))
                inkex.errormsg(_("Please select a rectangle"))
                return
            inkex.errormsg("top {}, bottom {}, left {}, right {}".format(elem.top, elem.bottom, elem.left, elem.right))
            inkex.errormsg("path {}".format(elem.path))
            rectangle = RectangleMetadata(elem.width, elem.height, elem.top, elem.bottom, elem.left, elem.right)
            # try to draw line from here?
            # parent = elem.getparent()
            # inkex.errormsg("what is parent:{} --> {}".format(parent, type(parent)))
            # def draw_SVG_line(x1, y1, x2, y2):
            #     # line_style   = { 'stroke': 'dashed',
            #     #                 'stroke-width':str(5),
            #     #                 'fill': 'none'
            #     #             }

            #     # line_attribs = {'style' : line_style,
            #     #                 inkex.addNS('label','inkscape') : name,
            #     node = inkex.Rectangle()
            #     d = "path M 50.18 26.5094 h 10.16 v 11.5906 h -10.16 z"
            #     node.set("d", d)
            #     dasharray = inkex.Style("stroke-dasharray:0.5,0.5;")
            #     node.set("style","stroke-dasharray:0.5,0.5;")
            #     inkex.errormsg("NODE PATH:{}".format(node.get_path()))
            #     return node
            # node = draw_SVG_line(elem.left + 1, elem.top, elem.left + 1, elem.bottom)
            # elem = inkex.etree.SubElement(parent, node)
            # self.get_current_layer().append(elem)
            # path = inkex.PathElement(attrib={
            # 'id': "HERE",
            # 'style': "stroke: %s; stroke-width: 0.4; fill: none;" % "red",
            # 'd': "m 0,86.039999 h 30.48 l 45.719999,22.86 ",
            # # 'transform': inkex.get_correction_transform(svg),
            # })
            # self.svg.get_current_layer().append(path)
            # for elem in self.svg.get_selected():
            #     elem.style['fill'] = 'green'
            #     elem.style["stroke"] = 'dashed'

            
            

        app = wx.App()
        frame = SensorGridFrame(rectangle, self.svg, on_cancel=self.cancel)

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

    def path_style(self, element):
        color = element.style('stroke', '#000000')
        return "stroke:%s;stroke-width:1px;fill:none" % (color)
'''


top 26.509441, bottom 38.099998, left 43.18, right 53.34
path M 43.18 26.5094 h 10.16 v 11.5906 h -10.16 z
dims in GUI: 10.16 x 11.590557

'''



if __name__ == '__main__':
    inkex.errormsg(sys.argv[1:])
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    SensorGrid(args.horizontal_wires, args.vertical_wires).run()