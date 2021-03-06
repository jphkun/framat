#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ----------------------------------------------------------------------
# Copyright 2019-2020 Airinnova AB and the FramAT authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------

# Author: Aaron Dettmann

"""
Module for creating the geometric mesh
"""

from collections import OrderedDict
from math import ceil

from mframework import FeatureSpec, UIDDict
import numpy as np

from ._element import Element
from ._log import logger
from ._util import Schemas as S
from ._util import pairwise

# TODO: Element --> Warning when overwriting data (first, from 'b' to 'c', then, from 'a' to 'c')
# TODO: need check that all material, cross section data is set from start to end....


def create_mesh(m):
    """Top-level function for mesh creation"""

    r = m.results
    abm = AbstractBeamMesh()

    for i, mbeam in enumerate(m.iter('beam')):
        logger.info(f"Meshing beam with index {i}...")

        # Support points (= named nodes)
        sup_points = OrderedDict()
        for uid, coord in mbeam.iter_uids('node'):
            sup_points[uid] = coord

        # Element lookup object for the new beam
        beam_id = abm.add_beam_line(sup_points, n=mbeam.get('nelem'))
        logger.info(f"Beam {i} has {abm.nelem_beam(beam_id)} elements")

        # ----- Beam element properties -----
        for pdef in mbeam.get('orientation'):
            for elem in abm.beams.iter_from_to(beam_id, pdef['from'], pdef['to']):
                elem.set('up', pdef['up'])

        for pdef in mbeam.get('material'):
            mat = m.get('material', uid=pdef['uid'])
            for elem in abm.beams.iter_from_to(beam_id, pdef['from'], pdef['to']):
                for p in ('E', 'G', 'rho'):
                    elem.set(p, mat.get(p))

        for pdef in mbeam.get('cross_section'):
            mat = m.get('cross_section', uid=pdef['uid'])
            for elem in abm.beams.iter_from_to(beam_id, pdef['from'], pdef['to']):
                for p in ('A', 'Iy', 'Iz', 'J'):
                    elem.set(p, mat.get(p))

        # ----- Loads -----
        for pdef in mbeam.get('point_load'):
            elem = abm.beams.get_by_uid(beam_id, pdef['at'])
            node_id = 1 if elem.p1.uid == pdef['at'] else 2
            elem.add('point_load', {'load': pdef['load'], 'node': node_id, 'local_sys': True})

        # for pdef in mbeam.get('distr_load'):
        #     for elem in abm.beams.iter_from_to(beam_id, pdef['from'], pdef['to']):
        #         ...

        # ----- Additional mass -----
        # for pdef in mbeam.get('point_mass'):
        #     elem = abm.beams.get_by_uid(beam_id, pdef['at'])
        #     node_id = 1 if elem.p1.uid == pdef['at'] else 2
        #     elem.add('point_load', {'load': pdef['load'], 'node': node_id, 'local_sys': True})

    logger.info(f"Abstract mesh created")
    logger.info(f"Discretisation:")
    logger.info(f"--> n_beams: {abm.nbeams:4d}")
    logger.info(f"--> n_elems: {abm.nelems:4d}")
    logger.info(f"--> n_nodes: {abm.nnodes:4d}")

    r.set_feature('mesh').set('abm', abm)


class Point:

    def __init__(self, coord, *, rel_coord=None, uid=None):
        assert uid is None or isinstance(uid, str)
        assert isinstance(coord, (list, np.ndarray)) and len(coord) == 3

        self.coord = np.array(coord)
        self.rel_coord = rel_coord
        self.uid = uid

    def __repr__(self):
        return f"{self.__class__.__qualname__}({self.coord!r}, {self.rel_coord!r}, {self.uid!r})"


class LineSegment:

    def __init__(self, p1, p2):
        assert isinstance(p1, Point) and isinstance(p2, Point)

        self.p1 = p1
        self.p2 = p2

        # Set the relative coordinates of the start and end point
        self.p1.rel_coord = 0
        self.p2.rel_coord = 1

        # Line direction
        self.dir = self.p2.coord - self.p1.coord
        self.len = np.linalg.norm(self.dir)
        self.all_points = [p1, p2]

    def __repr__(self):
        return f"{self.__class__.__qualname__}({self.p1!r}, {self.p2!r})"

    @property
    def from_uid(self):
        return self.p1.uid

    @property
    def to_uid(self):
        return self.p2.uid

    def split_into(self, n):
        """
        Split segment into smaller segments

        The new line segment will have n + 1 nodes.
        """

        assert isinstance(n, int) and n > 0

        self.all_points = [self.p1, ]

        for i in range(1, n):
            rel_coord = i/n
            self.all_points.append(
                Point(self.p1.coord + rel_coord*self.dir, rel_coord=rel_coord, uid=None)
            )

        self.all_points.append(self.p2)
        return self.all_points

    def iter_points(self, *, exclude_last=False):
        all_points = self.all_points[:-1] if exclude_last else self.all_points
        for p in all_points:
            yield p


class PolygonalChain:

    def __init__(self, sup_points, n=10):
        """
        Polygonal chain

        Args:
            :sup_points: (dict) key: support point uid, value: nodes coordinates
            :n: (int) number of elements for the entire chain

        Attr:
            :segments: (list) line segment
            :len: (float) length of the polygon
        """

        # Ensure that dictionary items are ordered correctly
        assert isinstance(sup_points, OrderedDict)
        assert isinstance(n, int)

        self.node_uids = sup_points.keys()
        self.segments = []
        self.len = 0

        # Add line segments
        points = []
        for uid, coord in sup_points.items():
            points.append(Point(coord, rel_coord=None, uid=uid))

        edges = []
        for p1, p2 in pairwise(points):
            edges.append(LineSegment(p1, p2))

        for seg in edges:
            self.add_segment(seg)

        self.set_node_num(n)

    def __repr__(self):
        return f"< {self.__class__.__qualname__} for {self.node_uids!r} >"

    def add_segment(self, seg):
        assert isinstance(seg, LineSegment)
        self.segments.append(seg)
        self.len += seg.len

    def set_node_num(self, n):
        for seg in self.segments:
            n_seg = ceil(n*(seg.len/self.len))
            seg.split_into(n_seg)

    def iter_points(self):
        curr_len = 0
        # All but last segments...
        for seg in self.segments[:-1]:
            for p in seg.iter_points(exclude_last=True):
                eta_poly = curr_len/self.len + p.rel_coord*(seg.len/self.len)
                yield Point(p.coord, rel_coord=eta_poly, uid=p.uid)
            curr_len += seg.len

        # Last segment...
        seg = self.segments[-1]
        for p in seg.iter_points(exclude_last=False):
            eta_poly = curr_len/self.len + p.rel_coord*(seg.len/self.len)  # TODO: duplicate
            yield Point(p.coord, rel_coord=eta_poly, uid=p.uid)


# ===== Abstract beam element =====

schema_load = {'load': S.vector6x1, 'node': S.pos_int, 'local_sys': {'type': bool}}
schema_mass = {'mass': {'type': S.pos_number}, 'node': S.pos_int}

fspec = FeatureSpec()

for p in Element.PROP_TYPES:
    fspec.add_prop_spec(p, S.pos_number)

fspec.add_prop_spec('up', S.vector3x1)
fspec.add_prop_spec('point_load', schema_load, singleton=False)
fspec.add_prop_spec('dist_load', schema_load, singleton=False)
fspec.add_prop_spec('point_mass', schema_mass, singleton=False)

# =================================


class AbstractEdgeElement(fspec.user_class):

    def __init__(self, p1, p2):
        """
        Edge element defined by spatial coordinates and abstract attributes

        Args:
            :p1: (obj) Point object of start point
            :p2: (obj) Point object of end point
        """

        super().__init__()

        assert isinstance(p1, Point) and isinstance(p2, Point)
        self.p1 = p1
        self.p2 = p2

    def __repr__(self):
        return f"< {self.__class__.__qualname__}({self.p1!r}, {self.p2!r}) >"


class AbstractBeamMesh:

    def __init__(self):
        """
        Mesh consisting of multiple, disconnected polygonal chains. The mesh
        may have globally defined abstract attributes.

        Attr:
            :beams: (list) list of beam look-up objects
        """

        # Each beam has a lookup dict object
        self.beams = UIDDict()

        # Bookkeeping
        self._num_beams = -1  # Number of beams -1
        self._num_elems = -1  # Number of elements -1
        self._num_nodes = -1  # Number of nodes -1

        # Global node numbers of named nodes
        self.glob_nums = {}

    def __repr__(self):
        return f"< {self.__class__.__qualname__} for {self.glob_nums!r} >"

    def add_beam_line(self, sup_points, n=10):
        """
        TODO
        """

        self._num_beams += 1
        self._num_nodes += 1

        polygon = PolygonalChain(sup_points, n=n)
        for (num1, p1), (num2, p2) in pairwise(enumerate(polygon.iter_points(), start=self._num_nodes)):
            self._num_elems += 1
            self.beams[self._num_beams] = AbstractEdgeElement(p1, p2)

            if p1.uid is not None:
                self.glob_nums[p1.uid] = num1
                try:
                    self.beams.assign_uid(self._num_beams, p1.uid)
                except KeyError:
                    pass
            if p2.uid is not None:
                self.glob_nums[p2.uid] = num2
                try:
                    self.beams.assign_uid(self._num_beams, p2.uid)
                except KeyError:
                    pass

        self._num_nodes += len(self.beams[self._num_beams])
        return self._num_beams

    @property
    def nbeams(self):
        return self._num_beams + 1

    def nelem_beam(self, beam_id):
        return len(self.beams[beam_id])

    @property
    def nelems(self):
        return self._num_elems + 1

    @property
    def nnodes(self):
        return sum(len(v.values()) + 1 for v in self.beams.values())

    def ndofs(self, ndof_per_node=6):
        return self.nnodes*ndof_per_node

    def get_sup_points(self, beam_id):
        xyz = self.beams[beam_id][0].p1.coord.reshape((1, 3))
        for elem in self.beams[beam_id].values():
            xyz = np.append(xyz, elem.p2.coord.reshape((1, 3)), axis=0)
        return xyz

    def get_lims_beam(self, beam_id):
        xyz = self.get_sup_points(beam_id)
        x_max = np.max(xyz[:, 0])
        y_max = np.max(xyz[:, 1])
        z_max = np.max(xyz[:, 2])
        x_min = np.min(xyz[:, 0])
        y_min = np.min(xyz[:, 1])
        z_min = np.min(xyz[:, 2])
        return (x_min, x_max), (y_min, y_max), (z_min, z_max)

    def get_lims(self):
        x_max = 0
        y_max = 0
        z_max = 0
        x_min = 0
        y_min = 0
        z_min = 0
        for beam_id in self.beams.keys():
            (x_minb, x_maxb), (y_minb, y_maxb), (z_minb, z_maxb) = self.get_lims_beam(beam_id)
            if x_maxb > x_max:
                x_max = x_maxb
            if y_maxb > y_max:
                y_max = y_maxb
            if z_maxb > z_max:
                z_max = z_maxb
            if x_minb < x_min:
                x_min = x_minb
            if y_minb < y_min:
                y_min = y_minb
            if z_minb < z_min:
                z_min = z_minb
        return (x_min, x_max), (y_min, y_max), (z_min, z_max)
