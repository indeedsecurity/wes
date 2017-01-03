import pytest
import os
from wes.main import load_db, load_projects_csv
from tinydb import TinyDB

def test_load_db(tmpdir):
    assert type(load_db(str(tmpdir))) is TinyDB
