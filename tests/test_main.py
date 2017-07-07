import pytest
import os
from wes.main import load_db, load_projects_csv
import sqlalchemy

def test_load_db(tmpdir):
    databaseUri = 'sqlite:///' + os.path.join(str(tmpdir), 'endpoints.sqlite')
    assert type(load_db(databaseUri)) is sqlalchemy.orm.session.sessionmaker
