import flask
from flask import request, Response, Blueprint
import re
import sys
import os
from pprint import pprint

# Add to wes to the sys path
wesDir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wesDir)
from wes.database import (Endpoint, Parameter, ProductGroup, Header,
                          Product, Template)
from wes.main import load_db

api = Blueprint('api', __name__)

if 'WES_WORKING_DIR' in os.environ:
    workingDir = os.environ['WES_WORKING_DIR']
else:
    workingDir = os.path.join(os.getcwd(), 'workingDir')


if 'WES_DATABASE_URI' in os.environ:
    databaseUri = os.environ['WES_DATABASE_URI']
else:
    databaseUri = 'sqlite:///' + os.path.join(workingDir, 'endpoints.sqlite')

db = load_db(databaseUri=databaseUri)
s = db()

api_v1 = Blueprint('api_v1', __name__)

@api_v1.route('/options')
def options():
    """
    Lists all options you can use to search the REST endpoint.
    """

    return flask.jsonify({
        'filepath': {
            'type': 'text',
        },
        'templates': {
            'type': 'text',
        },
        'endpoint': {
            'type': 'text',
        },
        'gitRepo': {
            'type': 'select',
            'options': [gitRepo[0] for gitRepo in s.query(Product.gitRepo).distinct()],
        },
        'productGroup': {
            'type': 'select',
            'options': [productGroup[0] for productGroup in s.query(ProductGroup.name).distinct()],
        },
        'product': {
            'type': 'select',
            'options': [product[0] for product in s.query(Product.name).distinct()],
        },
        'method': {
            'type': 'select',
            'options': [method[0] for method in s.query(Endpoint.method).distinct()],
        },
        'params': {
            'type': 'text',
        },
        'plugin': {
            'type': 'select',
            'options': [plugin[0] for plugin in s.query(Endpoint.plugin).distinct()],
        },
        'onlyPrivate': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '0',
        },
        'onlyRegex': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '0',
        },
        'onlyNoParams': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '0',
        },
        'excludePrivate': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '1',
        },
        'excludeRegex': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '1',
        },
        'excludeNoParams': {
            'type': 'bool',
            'options': ['1', '0'],
            'default': '1',
        },
    })

def create_query_from_qs(session):
    """
    This method pulls out the parameters from the request and returns a sqlalchemy search filter
    :return: sqlalchemy search filter
    """
    q = session.query(Endpoint)
    if request.args.get('filepath', None):
        param = request.args.get('filepath')
        q = q.filter(Endpoint.filepath.ilike('%{}%'.format(param)))
    if request.args.get('templates', None):
        param = request.args.get('templates')
        q = q.filter(Endpoint.templates.any(Template.filepath.ilike('%{}%'.format(param))))
    if request.args.get('endpoint', None):
        param = request.args.get('endpoint')
        q = q.filter(Endpoint.endpoint.ilike('%{}%'.format(param)))
    if request.args.get('gitRepo', None):
        param = request.args.get('gitRepo')
        q = q.filter(Endpoint.product.has(Product.gitRepo.ilike('%{}%'.format(param))))
    if request.args.get('productGroup', None):
        param = request.args.get('productGroup')
        q = q.filter(Endpoint.product.has(Product.productGroup.has(ProductGroup.name.ilike('%{}%'.format(param)))))
    if request.args.get('product', None):
        param = request.args.get('product')
        q = q.filter(Endpoint.product.has(Product.name.ilike('%{}%'.format(param))))
    if request.args.get('method', None):
        param = request.args.get('method')
        q = q.filter(Endpoint.method.ilike('%{}%'.format(param)))
    if request.args.get('params', None):
        param = request.args.get('params')
        q = q.filter(Endpoint.parameters.any(Parameter.name.ilike('%{}%'.format(param))))
    if request.args.get('plugin', None):
        param = request.args.get('plugin')
        q = q.filter(Endpoint.plugin.ilike('%{}%'.format(param)))

    onlyPrivate = request.args.get('onlyPrivate', None)
    onlyRegex = request.args.get('onlyRegex', None)
    onlyNoParams = request.args.get('onlyNoParams', None)
    excludePrivate = request.args.get('excludePrivate', None)
    excludeRegex = request.args.get('excludeRegex', None)
    excludeNoParams = request.args.get('excludeNoParams', None)

    if onlyPrivate and onlyPrivate == '1':
        q = q.filter(Endpoint.private == True)

    if onlyRegex and onlyRegex == '1':
        q = q.filter(Endpoint.regex == True)

    if onlyNoParams and onlyNoParams == '1':
        q = q.filter(Endpoint.parameters == None)

    if excludePrivate and excludePrivate == '1':
        q = q.filter(Endpoint.private == False)

    if excludeRegex and excludeRegex == '1':
        q = q.filter(Endpoint.regex == False)

    if excludeNoParams and excludeNoParams == '1':
        q = q.filter(Endpoint.parameters != None)

    return q


def regex_search_list(data, regex):
    """
    Allows you to search across a list with regex returns True if any match in the list.
    :param data: The element to search
    :param regex: The regex search string
    :return: True if any elements match, false if none match
    """
    # Create the data into a list if it isn't already
    if type(data) is not list:
        data = [data]
    for d in data:
        if re.search(regex, d):
            return True
    return False


def combineUrl(baseUrl, path):
    """
    :param baseUrl: the base url for the endpoint ex. https://www.indeed.com/
    :param path: the endpoint path ex. /salary
    :return: The combined url
    """
    return baseUrl.rstrip('/') + '/' + path.lstrip('/')

@api_v1.route('/endpoints')
def endpoints():
    """
    An endpoint that returns json and allows for the filtering based on the query strings you pass in. The following are
    supported query strings:
        - filepath=String
        - templates=String
        - endpoint=String
        - gitRepo=String
        - productGroup=String
        - product=String
        - method=String
        - params=String
        - plugin=String
        - onlyPrivate=Bool(1 or 0)
        - onlyRegex=Bool(1 or 0)
        - onlyNoParams=Bool(1 or 0)

    :return: JSON data from the search
    """
    # queries = create_tinydb_query_from_qs()
    result = create_query_from_qs(s).all()
    result = list(map(lambda x: x.to_dict(), result))
    # return all endpoints
    return flask.jsonify({'endpoints': result})

@api_v1.route('/products')
def products():
    """
    An endpoint that returns json of all the products in WES

    :return: JSON data
    """
    q = s.query(Product)

    results = {}
    for product in q.all():
        if product.name:
            results[product.name] = {
                'productGroup': product.productGroup.name,
                'gitRepo': product.gitRepo
            }
    return flask.jsonify(results)

@api_v1.route('/productGroups')
def productGroups():
    """
    An endpoint that returns json of all the product groups in WES

    :return: JSON data
    """
    q = s.query(ProductGroup)

    results = {}
    for productGroup in q.all():
        if productGroup.name:
            results[productGroup.name] = {
                'products': list(map(lambda x: x.name, productGroup.products))
            }
    return flask.jsonify(results)

@api_v1.route('/parameters')
def parameters():
    """
    An endpoint that returns json of all the product groups in WES

    :return: JSON data
    """
    q = s.query(Parameter)

    results = set()
    for parameter in q.all():
        results.add(parameter.name)
    return flask.jsonify(list(results))


@api_v1.route('/arachniYaml')
def arachniYaml():
    """
    An endpoint that returns YAML for the Arachni scanner. By default it filters out the endpoints that are private,
    have regex, and have no params. You can override this with the includePrivate, includeRegex, and includeNoParams
    query parameters. The following are supported query strings:
        - filepath=String
        - templates=String
        - endpoint=String
        - gitRepo=String
        - productGroup=String
        - product=String
        - method=String
        - params=String
        - plugin=String
        - onlyPrivate=Bool(1 or 0)
        - onlyRegex=Bool(1 or 0)
        - onlyNoParams=Bool(1 or 0)
        - includePrivate=Bool(1 or 0)
        - includeRegex=Bool(1 or 0)
        - includeNoParams=Bool(1 or 0)

    :return: YAML formatted for Arachni
    """

    q = create_query_from_qs(s)

    includePrivate = request.args.get('includePrivate', None)
    includeRegex = request.args.get('includeRegex', None)
    includeNoParams = request.args.get('includeNoParams', None)
    onlyPrivate = request.args.get('onlyPrivate', None)
    onlyRegex = request.args.get('onlyRegex', None)
    onlyNoParams = request.args.get('onlyNoParams', None)

    # Check for additional query strings
    # Check if we should include private endpoints
    if (includePrivate and includePrivate == '1') or (onlyPrivate and onlyPrivate == '1'):
        q = q
    else:
        # remove private endpoints
        q = q.filter(Endpoint.private == False)

    # Check if we should include endpoints with regex in them
    if (includeRegex and includeRegex == '1') or (onlyRegex and onlyRegex == '1'):
        q = q
    else:
        # remove endpoints with regex
        q = q.filter(Endpoint.regex == False)

    if (includeNoParams and includeNoParams == '1') or (onlyNoParams and onlyNoParams == '1'):
        q = q
    else:
        # remove endpoints with no params
        q = q.filter(Endpoint.parameters != None)

    result = q.all()
    result = list(map(lambda x: x.to_dict(), result))

    cleanEndpoints = []
    outputYaml = u""

    # Clean up the endpoints
    for r in result:
        if not r["method"]:
            r["method"] = "GET"

        cleanEndpoints.append({
            "method": r["method"],
            "url": combineUrl(r['baseUrl'], r['endpoint']),
            'parameters': r['params']
        })

    for endpoint in cleanEndpoints:
        outputYaml += u"- :type: :form\n"
        outputYaml += u"  :method: :{}\n".format(endpoint['method'].lower())
        outputYaml += u"  :action: {}\n".format(endpoint['url'])
        outputYaml += u"  :inputs:\n"
        if endpoint['parameters'] != "":
            for param in endpoint['parameters']:
                outputYaml += u"    {}: {}\n".format(param, "INDEEDSECURITY")
        outputYaml += u"  :source:\n"

    return Response(outputYaml, mimetype='application/x-yaml', headers={"Content-Disposition": "attachment;filename=vectors.yml"})
