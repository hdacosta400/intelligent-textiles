import inkex

class InkstitchExtension(inkex.Effect):
    """Base class for Inkstitch extensions.  Not intended for direct use."""

    def get_current_layer(self):
        # if no layer is selected, inkex defaults to the root, which isn't
        # particularly useful
        current_layer = self.svg.get_current_layer()
        if current_layer is self.document.getroot():
            try:
                current_layer = self.document.xpath(".//svg:g[@inkscape:groupmode='layer']", namespaces=inkex.NSS)[0]
            except IndexError:
                # No layers at all??  Fine, we'll stick with the default.
                pass
        return current_layer

    def no_elements_error(self):
        if self.svg.selected:
            # l10n This was previously: "No embroiderable paths selected."
            inkex.errormsg(_("Ink/Stitch doesn't know how to work with any of the objects you've selected.") + "\n")
        else:
            inkex.errormsg(_("There are no objects in the entire document that Ink/Stitch knows how to work with.") + "\n")

        inkex.errormsg(_("Tip: Run Extensions > Ink/Stitch > Troubleshoot > Troubleshoot Objects") + "\n")

    def descendants(self, node, selected=False, troubleshoot=False):  # noqa: C901
        nodes = []

        if node.tag == Comment:
            return []

        element = EmbroideryElement(node)

        if element.has_command('ignore_object'):
            return []

        if node.tag == SVG_GROUP_TAG and node.get(INKSCAPE_GROUPMODE) == "layer":
            if len(list(layer_commands(node, "ignore_layer"))):
                return []

        if (node.tag in EMBROIDERABLE_TAGS or node.tag == SVG_GROUP_TAG) and element.get_style('display', 'inline') is None:
            return []

        # defs, masks and clippaths can contain embroiderable elements
        # but should never be rendered directly.
        if node.tag in [SVG_DEFS_TAG, SVG_MASK_TAG, SVG_CLIPPATH_TAG]:
            return []

        # command connectors with a fill color set, will glitch into the elements list
        if is_command(node) or node.get(CONNECTOR_TYPE):
            return []

        if self.svg.selected:
            if node.get("id") in self.svg.selected:
                selected = True
        else:
            # if the user didn't select anything that means we process everything
            selected = True

        for child in node:
            nodes.extend(self.descendants(child, selected, troubleshoot))

        if selected:
            if node.tag == SVG_GROUP_TAG:
                pass
            elif (node.tag in EMBROIDERABLE_TAGS or is_clone(node)) and not is_pattern(node):
                nodes.append(node)
            # add images, text and patterns for the troubleshoot extension
            elif troubleshoot and (node.tag in NOT_EMBROIDERABLE_TAGS or is_pattern(node)):
                nodes.append(node)

        return nodes