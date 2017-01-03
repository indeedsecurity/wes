from setuptools import setup, find_packages

import sys
if sys.version_info[0] < 3 or sys.version_info[1] < 3:
    sys.exit('Error: WES only runs on Python 3.3 and above.')

setup(
    name='wes',
    version='1.0.0',
    packages=find_packages(),
    author='Caleb Coffie',
    author_email='calebc@indeed.com',
    install_requires=[
        'GitPython',
        'lxml',
        'typed_ast',
        'flask',
        'pytest',
        'pytest-mock',
        'pytest-cov',
        'SQLAlchemy',
        'psycopg2',
        'javalang==0.11.0'
    ],
    long_description=open('README.md').read(),
    entry_points={
        'console_scripts': [
            'wes = wes.main:main',
        ],
    }
)
