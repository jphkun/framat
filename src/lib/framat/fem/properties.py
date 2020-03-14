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
FEM properties
"""

from collections import defaultdict

from framat.fem.element import Element
from framat.helpers.moresyntax import PropertyHandler


# XXX: BACKCOMP =====
class Materials:

    def __init__(self):
        self.by_uid = {}

    def add_entry(self, material_uid, properties):
        self.by_uid.update({material_uid: properties})

    @classmethod
    def from_model_entry(cls, entry):
        instance = cls()
        for material in entry:
            instance.add_entry(material['uid'], {key: material[key]
                               for key in Element.MATERIAL_PROPS})
        return instance

class Profiles:

    def __init__(self):
        self.by_uid = {}

    def add_entry(self, profile_uid, properties):
        self.by_uid.update({profile_uid: properties})

    @classmethod
    def from_model_entry(cls, entry):
        instance = cls()
        for material in entry:
            instance.add_entry(material['uid'], {key: material[key]
                               for key in Element.PROFIL_PROPS})
        return instance
# ================
# ================
# ================


class Material(PropertyHandler):
    def __init__(self):
        super().__init__()
        self.allowed_keys = Element.MATERIAL_PROPS
        self.props = {key: 0 for key in self.allowed_keys}


class CrossSection(PropertyHandler):
    def __init__(self):
        super().__init__()
        self.allowed_keys = Element.CROSS_SECTION_PROPS
        self.props = {key: 0 for key in self.allowed_keys}
