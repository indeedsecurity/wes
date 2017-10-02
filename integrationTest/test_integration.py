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
    workingDir = str(tmpdir_factory.getbasetemp())

    projects = [{'baseUrl': 'http://west.example.com/', 'gitRepo': 'git@github.com:indeedsecurity/WEST.git'}]

    for project in projects:
        # Create commonly used variables for each Repo
        projectRepoPath = project['gitRepo'].split(':')[-1][:-4]
        projectName = project['gitRepo'].split('/')[-1][:-4]
        productGroup = projectRepoPath.split('/')[0]

        print("{}Processing the {} project{}".format(10*"-", projectRepoPath, 10*"-"))

        groupFolder = os.path.join(workingDir, productGroup)
        projectFolder = os.path.join(workingDir, productGroup, projectName)

        # clone/update the repositories
        clone_update_repo(projectFolder, project['gitRepo'])

        # Find and import all framework plugins
        framework_plugins = find_framework_plugins()
        plugins = import_all_framework_plugins(framework_plugins)

        # Find all the endpoints
        endpoints = []

        # Load up the processors so they only preprocess once per project
        processors = {
            'java': JavaProcessor(projectFolder),
            'python': PythonProcessor(projectFolder)
        }
        print('Pre-processing the project...')
        for name, processor in processors.items():
            processor.load_project()

        # Loop through all the plugins
        for plugin in plugins:
            pluginObj = plugin.CustomFramework(workingDir=os.path.abspath(projectFolder), processors=processors)

            # If the project is identified by the plugin try to find the endpoints
            # for the project with the find_endpoints() method
            if pluginObj.identify():
                print("** Identified the project as a {} project.".format(plugin.__name__[29:]))

                pluginEndpoints = pluginObj.find_endpoints()

                if pluginEndpoints:
                    pluginEndpoints = extend_endpoints_with_metadata(pluginEndpoints,
                                                                     project['gitRepo'],
                                                                     productGroup,
                                                                     projectName,
                                                                     plugin.__name__[29:],
                                                                     project['baseUrl'])

                    endpoints += pluginEndpoints

        # Load the list of all endpoints from the west project
        sys.path.append(os.path.abspath(os.path.join(projectFolder, 'scripts')))
        import west2json
        knownEndpoints = west2json.main(os.path.abspath(os.path.join(projectFolder)))

        failed_conditions = []
        # Verify we found all the endpoints
        for knownEp in knownEndpoints:
            # Find matches in endpoints
            possibleMatches = list(filter(lambda x: set(knownEp['endpoints']) == set(x['endpoints']), endpoints))
            if len(possibleMatches) < 1:
                failed_conditions.append(" - Couldn't find the path: {}, desc: {}".format(knownEp['endpoints'], knownEp['description']))
            elif len(possibleMatches) >= 1:
                if len(possibleMatches) > 1:
                    possibleMatches = list(filter(lambda x: set(knownEp['methods']) == set(x['methods']), possibleMatches))
                    if len(possibleMatches) != 1:
                        # Okay we found a match, lets check the other parameters
                        failed_conditions.append(" - Found multiple results for the path: {}, desc: {}".format(knownEp['endpoints'], knownEp['description']))
                        continue
                match = possibleMatches[0]
                for param in knownEp['params']:
                    if param not in match['params']:
                        failed_conditions.append(" - Couldn't find the param: {} for {}, desc: {}".format(param, knownEp['endpoints'], knownEp['description']))
                for template in knownEp['templates']:
                    if template not in match['templates']:
                        failed_conditions.append(" - Couldn't find the template: {} for {}, desc: {}".format(template, knownEp['endpoints'], knownEp['description']))
                if knownEp['methods'] != match['methods']:
                    failed_conditions.append(" - Couldn't find the correct method for: {}, desc: {}".format(knownEp['endpoints'], knownEp['description']))
                # pprint(possibleMatches)

        # pprint(knownEndpoints)
        # pprint(endpoints)

        assert len(failed_conditions) < 1, "\n" + "\n".join(failed_conditions)
