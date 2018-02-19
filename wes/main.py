import argparse
from git import Repo, GitCommandError
import re
import csv
import shutil
import codecs
import datetime
import json
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add to wes to the sys path
import sys
import os
wesDir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wesDir)
from wes.framework_plugins.common import JavaProcessor, PythonProcessor
from wes.database import (Base, Endpoint, Parameter, ProductGroup,
                          Product, Template, Header, get_or_create, delete_all_data)

# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("Main")


def load_db(databaseUri):
    engine = create_engine(databaseUri)

    # Enable foreign keys for sqlite
    if databaseUri.startswith('sqlite://'):
        engine.execute('PRAGMA foreign_keys=ON')

    session = sessionmaker()
    session.configure(bind=engine)

    # Creates all the tables if they don't exist
    Base.metadata.create_all(engine)

    return session


def load_projects_csv(csvFile):  # pragma: no cover
    projects = []
    with codecs.open(csvFile, 'r', 'utf-8', 'ignore') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            projects.append({'baseUrl': row['baseUrl'], 'gitRepo': row['gitRepo']})

    return projects


def clone_update_repo(projectFolder, gitRepo):
    success = True

    # Check if the project has a folder in the working Dir
    if os.path.isdir(projectFolder):
        try:
            # If so pull changes from the repo
            logger.info("Pulling project changes...")
            r = Repo(projectFolder)
            o = r.remotes.origin
            o.pull()
        except GitCommandError as e:
            logger.warning("Unable to pull project changes. Will try to re-clone.")
            shutil.rmtree(projectFolder)
            success = clone_update_repo(projectFolder, gitRepo)
    else:
        try:
            # Project doesn't exist in the working dir yet, let's clone it
            logger.info("Cloning the project...")
            os.makedirs(projectFolder)
            r = Repo.clone_from(gitRepo, projectFolder)
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


def extend_endpoints_with_metadata(endpoints, gitRepo, productGroup, projectName, pluginName, baseUrl):
    # Extend the endpoints found with information like the
    # location of the repo, repo name, plugin, and base url.
    for endpoint in endpoints:
        for k, v in endpoint.items():
            if type(v) is set:
                endpoint[k] = list(v)
        endpoint.update({
            'gitRepo': gitRepo,
            'productGroup': productGroup,
            'product': projectName,
            'plugin': pluginName,
            'baseUrl': baseUrl
        })
    return endpoints


def is_endpoint_regex(ep):
    if '*' in ep or '[' in ep or ']' in ep or '(' in ep or ')' in ep:
        return True
    else:
        return False


def update_db_with_endpoints(endpoints, db):
    # Now that we have the endpoints let's add new endpoints to the database
    # and update existing ones

    s = db()  # Create our session

    # Keep track of how many new records
    numRecords = 0
    numNewRecords = 0

    seperatedEndpoints = []

    # Seperate the list of endpoints to have unique methods and endpoints
    for endpoint in endpoints:
        for ep in endpoint['endpoints']:
            if not endpoint['methods']:
                endpoint['methods'] = ['None']
            for method in endpoint['methods']:
                tempDict = {
                    'baseUrl': endpoint['baseUrl'],
                    'endpoint': ep,
                    'method': method,
                    'gitRepo': endpoint['gitRepo'],
                    'productGroup': endpoint['productGroup'],
                    'product': endpoint['product'],
                    'plugin': endpoint['plugin'],
                    'params': endpoint['params'] or [],
                    'templates': set(endpoint['templates']) or set(),
                    'headers': set(endpoint['headers']) if 'headers' in endpoint else set(),
                    'filepath': endpoint['filepath'] or None,
                    'lineNumber': endpoint['lineNumber'] if 'lineNumber' in endpoint else None
                }
                seperatedEndpoints.append(tempDict)

    # Loop through each endpoint
    for endpointDict in seperatedEndpoints:
        numRecords += 1
        # Attempt to pull out an existing endpoint db entry
        epRecord = s.query(Endpoint)
        epRecord = epRecord.filter(Endpoint.baseUrl == endpointDict['baseUrl'])
        epRecord = epRecord.filter(Endpoint.endpoint == endpointDict['endpoint'])
        epRecord = epRecord.filter(Endpoint.method == endpointDict['method'])
        epRecord = epRecord.filter(Endpoint.filepath == endpointDict['filepath'])
        if 'headers' in endpointDict:
            for header in endpointDict['headers']:
                epRecord = epRecord.filter(Endpoint.headers.any(Header.value == header))
        results = epRecord.all()

        # If there's are still more than one conflicting results, add in lineNumber
        if len(results) > 1:
            epRecord = epRecord.filter(Endpoint.lineNumber == endpointDict['lineNumber'])

            results = epRecord.all()

        # If the record is not None take the first element
        if results:
            epRecord = results[0]
        else:
            epRecord = None

        if epRecord is None:
            numNewRecords += 1
            # Create new endpoint if one didn't exist
            epRecord = Endpoint()

        # Add references to other objects to endpoint
        productGroup = get_or_create(s,
                                     ProductGroup,
                                     name=endpointDict['productGroup'])
        product = get_or_create(s,
                                Product,
                                name=endpointDict['product'],
                                gitRepo=endpointDict['gitRepo'],
                                productGroupId=productGroup.id)
        # Add simple parameters to the Endpoint object
        epRecord.baseUrl = endpointDict['baseUrl']
        epRecord.endpoint = endpointDict['endpoint']
        epRecord.method = endpointDict['method']
        epRecord.productId = product.id
        epRecord.plugin = endpointDict['plugin']
        epRecord.filepath = endpointDict['filepath']
        epRecord.regex = is_endpoint_regex(endpointDict['endpoint'])
        epRecord.lineNumber = endpointDict['lineNumber'] if 'lineNumber' in endpointDict else None

        # Loop through adding object for each parameter in list
        epRecord.parameters = []
        for param in endpointDict['params']:
            name = param['name'] if type(param) is dict else param
            filepath = param['filepath'] if type(param) is dict else None
            lineNumber = param['lineNumber'] if type(param) is dict and 'lineNumber' in param else None
            paramObject = get_or_create(s,
                                        Parameter,
                                        name=name,
                                        filepath=filepath,
                                        lineNumber=lineNumber,
                                        productId=product.id)
            epRecord.parameters.append(paramObject)
        # Loop through adding object for each template in list
        epRecord.templates = []
        for template in endpointDict['templates']:
            templateObject = get_or_create(s,
                                           Template,
                                           filepath=template,
                                           productId=product.id)
            epRecord.templates.append(templateObject)
        # Loop through adding object for each header in list
        epRecord.headers = []
        if 'headers' in endpointDict:
            for header in endpointDict['headers']:
                headerObject = get_or_create(s,
                                             Header,
                                             value=header)
                epRecord.headers.append(headerObject)
        # Update touchedDate for each endpoint we touch
        epRecord.touchedDate = datetime.datetime.utcnow()
        # Add the new/editted endpoint to the database and commit
        s.add(epRecord)
        s.commit()
    # Close our session
    s.close()
    # Print Stats
    logger.info("Found %s endpoints with %s new endpoints in this project.", numRecords, numNewRecords)


def remove_stale_db_records(db):
    # Removes all Endpoints in the Database that have touchedDate more more than
    # 3 days old
    s = db()  # Create our session

    currentTime = datetime.datetime.utcnow()
    threeDayAgo = currentTime - datetime.timedelta(days=3)

    staleRecords = s.query(Endpoint).filter(Endpoint.touchedDate < threeDayAgo)

    for staleRecord in staleRecords:
        s.delete(staleRecord)

    s.commit()
    s.close()

    # Print Stats
    logger.info("Removed %s stale endpoints.", staleRecords.count())


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


def main(sysargs=sys.argv[1:]):
    # parse through command line arguments
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', '--repo', action='store',
                       help='The url to to the git repo to be tested')
    group.add_argument('-f', '--folder', action='store',
                       help='The project folder to scan. This can be provided '
                       'instead of a git repo.')
    group.add_argument('-rcsv', '--repoCsv', action='store',
                       help='The path to a list of repos in csv')
    parser.add_argument('-u', '--baseUrl', action='store',
                        help='The base url for the endpoints found. Only '
                        'required when not supplying a csv.')
    parser.add_argument('-d', '--workDir', action='store',
                        help='The directory to clone the repo into',
                        default='workingDir')
    parser.add_argument('-s', '--database', action='store',
                        help='The database URI ex. sqlite:///test.sqlite',
                        default=None)
    parser.add_argument('-o', '--output', action='store',
                        help='The file to output endpoints in json format',
                        default=None)
    parser.add_argument('-c', '--clear', action='store_true',
                        help='The flag to clear the database before running')

    args = parser.parse_args(sysargs)

    # Determine our working directory
    workingDir = None
    if args.workDir != 'workingDir':
        workingDir = args.workDir
    elif 'WES_WORKING_DIR' in os.environ:
        workingDir = os.environ['WES_WORKING_DIR']
    else:
        workingDir = os.path.join(os.getcwd(), args.workDir)

    if not os.path.isdir(workingDir):
        os.makedirs(workingDir)

    # Load the database
    databaseUri = None
    if args.database is not None:
        databaseUri = args.database
    elif 'WES_DATABASE_URI' in os.environ:
        databaseUri = os.environ['WES_DATABASE_URI']
    else:
        sqlite_file = os.path.join(workingDir, 'endpoints.sqlite')
        databaseUri = 'sqlite:///' + sqlite_file)
        if not os.path.exists(sqlite_file):
            os.mknod(sqlite_file)

    db = load_db(databaseUri=databaseUri)

    # Clear the database, if requested
    if args.clear:
        s = db()
        delete_all_data(s)
        s.close()

    projects = []
    if args.repoCsv:
        projects = load_projects_csv(args.repoCsv)
    else:
        # check args for issues
        if not hasattr(args, 'baseUrl') and args.baseUrl:
            raise argparse.ArgumentTypeError("If supplying a git repo you must "
                                             "include a base url.")
        if ((not hasattr(args, 'repo') and args.repo) or
             (not hasattr(args, 'folder') and args.folder)):
            raise argparse.ArgumentTypeError("If not supplying a csv you must "
                                             "supply a repo or folder.")

        if hasattr(args, 'repo') and args.repo:
            projects.append({'baseUrl': args.baseUrl, 'gitRepo': args.repo})
        elif hasattr(args, 'folder') and args.folder:
            projects.append({'baseUrl': args.baseUrl, 'folder': os.path.realpath(args.folder)})

    for project in projects:
        projectRepoPath = None
        projectName = None
        productGroup = None

        if 'gitRepo' in project:
            # Create commonly used variables for each Repo
            projectRepoPath = project['gitRepo'].split(':')[-1][:-4]
            projectName = project['gitRepo'].split('/')[-1][:-4]
            productGroup = projectRepoPath.split('/')[0]

        elif 'folder' in project:
            gitConfigPath = os.path.realpath(os.path.join(project['folder'], '.git', 'config'))

            try:
                if os.path.isfile(gitConfigPath):
                    import configparser
                    gitConfig = configparser.ConfigParser()
                    gitConfig.read_file(open(gitConfigPath))
                    project['gitRepo'] = gitConfig['remote "origin"']['url']

                    # Create commonly used variables for each Repo
                    projectRepoPath = project['gitRepo'].split(':')[-1][:-4]
                    projectName = project['gitRepo'].split('/')[-1][:-4]
                    productGroup = projectRepoPath.split('/')[0]
                else:
                    raise Exception('Not a git repo...')

            except:
                project['gitRepo'] = None
                projectRepoPath = None
                projectName = None
                productGroup = None

        logger.info("----------Processing the %s project----------", projectRepoPath)

        if 'folder' in project:
            projectFolder = os.path.realpath(project['folder'])
        elif 'gitRepo' in project:
            groupFolder = os.path.join(workingDir, productGroup)
            projectFolder = os.path.join(groupFolder, projectName)

            # clone/update the repositories
            cloned = clone_update_repo(projectFolder, project['gitRepo'])
            if not cloned:
                logger.debug("Unable to clone or update the project. Trying next project.")
                continue

        # Find and import all framework plugins
        framework_plugins = find_framework_plugins()
        plugins = import_all_framework_plugins(framework_plugins)

        # Load up the processors so they only preprocess once per project
        processors = {
            'java': JavaProcessor(projectFolder),
            'python': PythonProcessor(projectFolder)
        }
        logger.info('Preprocessing the project...')
        for name, processor in processors.items():
            processor.load_project()

        # Loop through all the plugins
        for plugin in plugins:
            pluginObj = plugin.CustomFramework(workingDir=os.path.abspath(projectFolder), processors=processors)

            # If the project is identified by the plugin try to find the endpoints
            # for the project with the find_endpoints() method
            if pluginObj.identify():
                logger.info("Identified the project as a %s project.", plugin.__name__[29:])

                endpoints = pluginObj.find_endpoints()

                if endpoints:
                    endpoints = extend_endpoints_with_metadata(endpoints,
                                                               project['gitRepo'],
                                                               productGroup,
                                                               projectName,
                                                               plugin.__name__[29:],
                                                               project['baseUrl'])

                    update_db_with_endpoints(endpoints, db)

    # Remove stale records from the database
    remove_stale_db_records(db)

    # Query the db to count records
    s = db()
    dbEndpoints = s.query(Endpoint)
    dbParams = s.query(Parameter).filter(Parameter.endpoints is not None)
    s.close()

    # Tally up all of the endpoints in the database
    logger.info("Total of %s endpoints in the database.", dbEndpoints.count())
    logger.info("Total of %s parameters in the database.", dbParams.count())

    # Output endpoints to JSON file
    if args.output:
        with open(args.output, 'w') as f:
            results = list(map(lambda x: x.to_dict(), dbEndpoints))
            json.dump({'endpoints': results}, f, indent=1, default=str)

if __name__ == '__main__':
    main()
