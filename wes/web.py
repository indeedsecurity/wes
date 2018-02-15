import flask
from flask import render_template
import argparse
import os
import sys

wesDir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wesDir)
from wes.api.v1 import api_v1

app = flask.Flask(__name__)
app.register_blueprint(api_v1, url_prefix='/wes/api/v1')

def console():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', action='store', type=int,
                        help='The port to run the server on.',
                        default=5000)
    parser.add_argument('-i', '--host', action='store',
                        help='The interface to run the server on.',
                        default='127.0.0.1')
    args = parser.parse_args()

    """
    Runs the flask app
    """
    app.run(host=args.host, port=args.port)

if __name__ == '__main__':
    console()
