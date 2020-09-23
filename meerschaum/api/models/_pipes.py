#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
Register new Pipes
"""
from meerschaum.utils.misc import attempt_import
pydantic, sqlalchemy, databases = attempt_import('pydantic', 'sqlalchemy', 'databases')

class MetaPipe(pydantic.BaseModel):
    location_key : str
    metric_key : str
    connector_keys : str ### e.g. sql:main

