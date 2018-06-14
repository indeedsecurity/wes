import os
import sys
from pprint import pprint
from wes.main import load_db, clone_update_repo, find_framework_plugins, \
    import_all_framework_plugins, extend_endpoints_with_metadata
from wes.framework_plugins.common import JavaProcessor, PythonProcessor

import pytest

# @pytest.mark.skip(reason="We need to fix a bunch of django stuff before we can get this test to not throw exceptions")
def test_integration(tmpdir_factory):
    # Determine our working directory
    working_dir = str(tmpdir_factory.getbasetemp())

    projects = [{'base_url': 'http://west.example.com/', 'git_repo': 'git@github.com:indeedsecurity/WEST.git'}]

    for project in projects:
        # Create commonly used variables for each Repo
        project_repo_path = project['git_repo'].split(':')[-1][:-4]
        project_name = project['git_repo'].split('/')[-1][:-4]
        product_group = project_repo_path.split('/')[0]

        print("{}Processing the {} project{}".format(10*"-", project_repo_path, 10*"-"))

        group_folder = os.path.join(working_dir, product_group)
        project_folder = os.path.join(working_dir, product_group, project_name)

        # clone/update the repositories
        clone_update_repo(project_folder, project['git_repo'])

        # Find and import all framework plugins
        framework_plugins = find_framework_plugins()
        plugins = import_all_framework_plugins(framework_plugins)

        # Find all the endpoints
        endpoints = []

        # Load up the processors so they only preprocess once per project
        processors = {
            'java': JavaProcessor(project_folder),
            'python': PythonProcessor(project_folder)
        }
        print('Pre-processing the project...')
        for name, processor in processors.items():
            processor.load_project()

        # Loop through all the plugins
        for plugin in plugins:
            plugin_obj = plugin.CustomFramework(working_dir=os.path.abspath(project_folder), processors=processors)

            # If the project is identified by the plugin try to find the endpoints
            # for the project with the find_endpoints() method
            if plugin_obj.identify():
                print("** Identified the project as a {} project.".format(plugin.__name__[29:]))

                plugin_endpoints = plugin_obj.find_endpoints()

                if plugin_endpoints:
                    plugin_endpoints = extend_endpoints_with_metadata(plugin_endpoints,
                                                                      project['git_repo'],
                                                                      product_group,
                                                                      project_name,
                                                                      plugin.__name__[29:],
                                                                      project['base_url'])

                    endpoints += plugin_endpoints

        # Load the list of all endpoints from the west project
        sys.path.append(os.path.abspath(os.path.join(project_folder, 'scripts')))
        import west2json
        known_endpoints = west2json.main(os.path.abspath(os.path.join(project_folder)))

        failed_conditions = []
        # Verify we found all the endpoints
        for known_ep in known_endpoints:
            # Find matches in endpoints
            possible_matches = list(filter(lambda x: set(known_ep['endpoints']) == set(x['endpoints']), endpoints))
            if len(possible_matches) < 1:
                failed_conditions.append(" - Couldn't find the path: {}, desc: {}".format(known_ep['endpoints'], known_ep['description']))
            elif len(possible_matches) >= 1:
                if len(possible_matches) > 1:
                    possible_matches = list(filter(lambda x: set(known_ep['methods']) == set(x['methods']), possible_matches))
                    if len(possible_matches) != 1:
                        # Okay we found a match, lets check the other parameters
                        failed_conditions.append(" - Found multiple results for the path: {}, desc: {}".format(known_ep['endpoints'], known_ep['description']))
                        continue
                match = possible_matches[0]
                for param in known_ep['params']:
                    if param not in match['params']:
                        failed_conditions.append(" - Couldn't find the param: {} for {}, desc: {}".format(param, known_ep['endpoints'], known_ep['description']))
                for template in known_ep['templates']:
                    if template not in match['templates']:
                        failed_conditions.append(" - Couldn't find the template: {} for {}, desc: {}".format(template, known_ep['endpoints'], known_ep['description']))
                if known_ep['methods'] != match['methods']:
                    failed_conditions.append(" - Couldn't find the correct method for: {}, desc: {}".format(known_ep['endpoints'], known_ep['description']))
                # pprint(possible_matches)

        # pprint(known_endpoints)
        # pprint(endpoints)

        assert len(failed_conditions) < 1, "\n" + "\n".join(failed_conditions)
