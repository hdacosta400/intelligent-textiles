import inkex
from lxml import etree
import math

def create_path(svg, points, is_horizontal):
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
    
    elem = etree.SubElement(svg.get_current_layer(), inkex.addNS('path','svg'), line_attribs)  
    return elem


def compute_euclidean_distance(x1, y1, x2, y2):
    return math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)


def segment_line(line, num_points):
    '''
    Breaks line into num_points equal parts
    returns array of points 
    '''
    points = []

    def parameterize_line(t):
        x_t = line[0][0] + (line[1][0] - line[0][0]) * t
        y_t = line[0][1] + (line[1][1] - line[0][1]) * t
        return x_t, y_t
    
    segment_length = 1 / (num_points + 1)
    for i in range(1 ,num_points+1): # adjust from 0 to n+1 bc we cant put in 0 to the parameterized line equation
        x, y = parameterize_line(i * segment_length)
        points.append([x,y])
    return points

