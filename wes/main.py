import argparse
from git import Repo, GitCommandError
import re
import csv
import shutil
import codecs
import datetime
import json
import logging

# Add to wes to the sys path
import sys
import os
wes_dir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wes_dir)
from wes.framework_plugins.common import JavaProcessor, PythonProcessor

# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("Main")


def clone_update_repo(project_folder, git_repo):
    success = True

    # Check if the project has a folder in the working Dir
    if os.path.isdir(project_folder):
        try:
            # If so pull changes from the repo
            logger.info("Pulling project changes...")
            r = Repo(project_folder)
            o = r.remotes.origin
            o.pull()
        except GitCommandError as e:
            logger.warning("Unable to pull project changes. Will try to re-clone.")
            shutil.rmtree(project_folder)
            success = clone_update_repo(project_folder, git_repo)
    else:
        try:
            # Project doesn't exist in the working dir yet, let's clone it
            logger.info("Cloning the project...")
            os.makedirs(project_folder)
            r = Repo.clone_from(git_repo, project_folder)
        except GitCommandError as e:
            logger.warning("An error occurred while cloning the project.")
            logger.warning("Verify the repository exists and you have access.")
            success = False

    return success


def find_framework_plugins():
    # Find all of the framework plugins
    framework_plugins_dir = os.path.join(os.path.dirname(__file__),
                                         'framework_plugins')
    plugin_file_regex = r'^plugin_.+\.py$'
    plugin_file_regex_pattern = re.compile(plugin_file_regex)
    framework_plugins = filter(lambda x: plugin_file_regex_pattern.match(x),
                               os.listdir(framework_plugins_dir))
    framework_plugins = list(map(lambda x: x.replace('.py', ''), framework_plugins))

    return framework_plugins


def import_all_framework_plugins(framework_plugins):
    # Import all the plugins and add each to a list
    plugins = []
    for module in framework_plugins:
        plugins.append(__import__('wes.framework_plugins.' + module, fromlist=['CustomFramework']))

    return plugins


def is_endpoint_regex(ep):
    if '*' in ep or '[' in ep or ']' in ep or '(' in ep or ')' in ep:
        return True
    else:
        return False


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

def _convert_elements(elements):
    # check elements
    if not elements:
        return []

    # add value
    for element in elements:
        if 'value' not in element:
            element['value'] = ""

    return elements


def seperate_endpoints(endpoints):
    """
    The endpoints returned from the individual plugins may contain
    lists for the methods and the endpoint string
    :param endpoints: List of endpoint dictionaries
    """
    seperated_endpoints = []

    # Seperate the list of endpoints to have unique methods and endpoints
    for endpoint in endpoints:
        for ep in endpoint['endpoints']:
            if not endpoint['methods']:
                # If there's no method set it to GET
                endpoint['methods'] = ['GET']
            for method in endpoint['methods']:
                tempDict = {
                    'endpoint': ep,
                    'method': method,
                    'plugin': endpoint['plugin'],
                    'params': endpoint['params'] or [],
                    'templates': list(set(endpoint['templates'])) or [],
                    'headers': list(set(endpoint['headers'])) if 'headers' in endpoint else [],
                    'filepath': endpoint['filepath'] or None,
                    'line_number': endpoint['line_number'] if 'line_number' in endpoint else None
                }
                seperated_endpoints.append(tempDict)
    
    return seperated_endpoints


def convert_endpoints_list_to_har(endpoints, project):
    """
    Used to convert list of endpoint dictionaries to HAR format
    :param endpoints: List of endpoint dictionaries
    :param project: Dictionary with project details
    """
    entries = []
    for endpoint in endpoints:
        # defaults
        query_string = []
        post_data_params = []
        mime_type = ""

        # url and method
        url = '{}/{}'.format(project['base_url'].rstrip('/'), endpoint['endpoint'].lstrip('/'))
        method = endpoint['method'] or "GET"

        # headers
        headers = _convert_elements(endpoint.get('headers'))

        # cookies
        cookies = _convert_elements(endpoint.get('cookies'))

        # query string
        if method.upper() == "GET":
            query_string = _convert_elements(endpoint.get('params'))

        # post data params
        if method.upper() == "POST":
            post_data_params = _convert_elements(endpoint.get('params'))

        # mime type
        if post_data_params:
            mime_type = "application/x-www-form-urlencoded"
        
        # wes specific properties
        plugin = endpoint.get('plugin')
        templates = endpoint.get('templates')
        filepath = endpoint.get('filepath')
        line_number = endpoint.get('line_number')
        git_repo = project.get('git_repo')

        # add to entries
        entries.append({'request': {
            'method': method,
            'url': url,
            'cookies': cookies,
            'headers': headers,
            'queryString': query_string,
            'postData': {
                'mimeType': mime_type,
                'params': post_data_params,
                'text': ""
            },
            'metadata': {
                'plugin': plugin,
                'templates': templates,
                'filepath': filepath,
                'lineNumber': line_number,
                'gitRepo': git_repo,
            }
        }})
        
    return {'log': {'entries': entries}}


def convert_set_values_to_lists(endpoints):
    """
    To make our endpoint lists JSON serializable we need to convert the set values
    to lists
    :param endpoints: List of endpoint dictionaries
    """
    for endpoint in endpoints:
        for k, v in endpoint.items():
            if type(v) is set:
                endpoint[k] = list(v)
    
    return endpoints


def add_plugin_to_endpoints(endpoints, plugin):
    """
    Add the endpoint key to each endpoint dictionary in the list
    :param endpoints: List of endpoint dictionaries
    :param plugin: String of the plugin name
    """
    for endpoint in endpoints:
        endpoint.update({
            'plugin': plugin,
        })
    
    return endpoints

def main(sysargs=sys.argv[1:]):
    # parse through command line arguments
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', '--repo', action='store',
                       help='The url to to the git repo to be tested')
    group.add_argument('-f', '--folder', action='store',
                       help='The project folder to scan. This can be provided '
                       'instead of a git repo.')
    parser.add_argument('-u', '--base-url', action='store', required=True,
                        help='The base url for the endpoints found')
    parser.add_argument('-d', '--working-dir', action='store',
                        help='The directory to clone the repo into',
                        default='workingDir')
    parser.add_argument('output_file', action='store',
                        help='The file to output endpoints in HAR format. '
                        'Use a \'-\' if you\'d like STDOUT.')

    args = parser.parse_args(sysargs)

    # Determine our working directory
    working_dir = None
    if args.working_dir != 'workingDir':
        working_dir = args.working_dir
    elif 'WES_WORKING_DIR' in os.environ:
        working_dir = os.environ['WES_WORKING_DIR']
    else:
        working_dir = os.path.join(os.getcwd(), args.working_dir)

    if not os.path.isdir(working_dir):
        os.makedirs(working_dir)

    project = {
        'base_url': args.base_url,
        'git_repo': args.repo if hasattr(args, 'repo') else None,
        'folder': args.folder if hasattr(args, 'folder') else None,
        'product': None,
        'product_group': None, 
    }

    # Create commonly used variables for each Repo
    if project['folder']:
        git_config_path = os.path.realpath(os.path.join(project['folder'], '.git', 'config'))

        try:
            if os.path.isfile(git_config_path):
                import configparser
                git_config = configparser.ConfigParser()
                git_config.read_file(open(git_config_path))
                project['git_repo'] = git_config['remote "origin"']['url']
            else:
                raise Exception('Not a git repo...')

        except:
            pass

    if project['git_repo']:
        repo_path = project['git_repo'].split(':')[-1]
        if repo_path.endswith('.git'):
            repo_path = repo_path[:-4]  # remove .git

        project['product_group'] = repo_path.split('/')[0]
        project['product'] = repo_path.split('/')[1]
        project['folder'] = os.path.join(working_dir, project['product_group'], project['product'])
        project['folder'] = os.path.realpath(project['folder'])

        # Update the repo
        success = clone_update_repo(project['folder'], project['git_repo'])
        if not success:
            logger.debug("Unable to clone or update the project.")
            sys.exit()

    # Make sure we're using the real path
    project['folder'] = os.path.abspath(os.path.realpath(project['folder']))

    logger.info("----------Processing the {}/{} project----------".format(project['product_group'], project['product']))

    # Find and import all framework plugins
    framework_plugins = find_framework_plugins()
    plugins = import_all_framework_plugins(framework_plugins)

    # Load up the processors so they only preprocess once per project
    processors = {
        'java': JavaProcessor(project['folder']),
        'python': PythonProcessor(project['folder'])
    }
    logger.info('Preprocessing the project...')
    for name, processor in processors.items():
        processor.load_project()

    endpoints = []

    # Loop through all the plugins
    for plugin in plugins:
        plugin_obj = plugin.CustomFramework(working_dir=project['folder'], processors=processors)

        # If the project is identified by the plugin try to find the endpoints
        # for the project with the find_endpoints() method
        if plugin_obj.identify():
            plugin_name = plugin.__name__.replace('wes.framework_plugins.plugin_', '')
            logger.info("Identified the project as a %s project.", plugin_name)

            plugin_endpoints = plugin_obj.find_endpoints()

            # convert sets to lists so they're json serializable
            plugin_endpoints = convert_set_values_to_lists(plugin_endpoints)

            # add in plugin to the endpoint dictionaries
            plugin_endpoints = add_plugin_to_endpoints(plugin_endpoints, plugin_name)

            # add to complete list of endpoints
            if plugin_endpoints:
                endpoints += plugin_endpoints

    # seperate endpoints into individual methods and paths
    endpoints = seperate_endpoints(endpoints)

    # convert list of endpoint dictionaries to har format
    har_endpoints = convert_endpoints_list_to_har(endpoints, project)

    # TODO: Log how many endpoints were found
    logger.info('Found {} endpoints in the project.'.format(len(endpoints)))

    # Output the results to STDOUT or a file
    if args.output_file == '-':
        print(json.dumps(har_endpoints, indent=1))
    else:
        with open(args.output, 'w') as f:
            json.dump(har_endpoints, f, indent=1, default=str)
            

if __name__ == '__main__':
    main()
