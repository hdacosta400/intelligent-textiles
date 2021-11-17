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


class CombineGrids(InkstitchExtension):
    COMMANDS = ["combine_grids"]
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        InkstitchExtension.__init__(self, *args, **kwargs)
        for command in self.COMMANDS:
            self.arg_parser.add_argument("--%s" % command, type=inkex.Boolean)
    def cancel(self):
        self.cancelled = True
    def effect(self):
        pass



if __name__ == '__main__':
    inkex.errormsg(sys.argv[1:])
    parser = ArgumentParser()
    parser.add_argument("--horizontal_wires")
    parser.add_argument("--vertical_wires")
    parser.add_argument('args', nargs=REMAINDER)
    args, _ = parser.parse_known_args()
    inkex.errormsg("args:{}".format(args))
    CombineGrids(args.horizontal_wires, args.vertical_wires).run()