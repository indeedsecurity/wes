import glob
import codecs
import logging
import _ast3
from typed_ast import ast3
# Add to wes to the sys path
import sys
import os
from copy import copy
wesDir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wesDir)
from wes.framework_plugins.common import Framework

# configure logging
logger = logging.getLogger("Django")


class CustomFramework(Framework):
    def __init__(self, workingDir, processors):
        self.workingDir = workingDir
        self.tempRecursedEndpoints = []
        self.endpoints = []
        self.processor = processors['python']
        self.projectRootDir = self._find_project_root()

    def identify(self):
        """
        This method is used to determine if the project is a django
        application and whether it should be processed by this plugin.
        """
        # Find all *.py files in the project
        globPath = os.path.join(self.workingDir, '**', '*.py')
        files = glob.glob(globPath, recursive=True)

        # if there aren't any *.py files then it's not a django project
        if not files:
            return False

        # Check if any of those *.py contain the string django or Django
        for f in files:
            if 'django' in codecs.open(f, 'r', 'utf-8', 'ignore').read():
                return True
            elif 'Django' in codecs.open(f, 'r', 'utf-8', 'ignore').read():
                return True

        return False

    def find_endpoints(self):
        # Look for the root urls.py file
        rootUrlsFilePath = self._find_root_urls_file()

        # Find all url() calls in the file
        urlCalls = self._find_all_url_calls(rootUrlsFilePath)

        # Loop through url calls and find all the referenced calls
        for call in urlCalls:
            self._resolve_url_call_to_views(call, rootUrlsFilePath)

        # Flatten the self.tempRecursedEndpoints list
        self.endpoints = self._flatten_recursed_endpoints(self.tempRecursedEndpoints)

        # Find view file location and context
        self.endpoints = self._find_view_context(self.endpoints)

        # Remove endpoints we couldn't locate the view to
        self.endpoints = list(filter(lambda x: x['viewFilepath'], self.endpoints))

        # Find parameters
        self.endpoints = self._find_parameters(self.endpoints)

        # Find methods
        self.endpoints = self._find_methods(self.endpoints)

        # Split endpoints into single methods and add line numbers
        self.endpoints = self._add_line_numbers(self.endpoints)

        # clean endpoint fields
        return self._clean_endpoints(self.endpoints)

    def _resolve_url_call_to_views(self, urlCall, filepath, parent=None):
        if type(urlCall) is _ast3.Call and urlCall.func.id == 'url':
            # Lets parse the args out of the url(args) call
            endpoint = self.processor.parse_python_method_args(urlCall, ['regex', 'view', 'kwargs', 'name'])

            # Add parent to list
            endpoint['parent'] = parent

            # Add file location the url was found so that the view path can be resolved
            endpoint['locationFound'] = filepath

            # Make sure we get the required arguments
            if 'regex' in endpoint and 'view' in endpoint:
                # Check if we need to recurse
                if (type(endpoint['view']) is _ast3.Call and
                        hasattr(endpoint['view'].func, 'id') and
                        endpoint['view'].func.id == 'include'):

                    # if the url() method contains a include() then lets find the url() calls within that file
                    # Construct path to referenced module
                    includeParams = self.processor.parse_python_method_args(endpoint['view'], ['module', 'namespace', 'app_name'])

                    # this accounts for the following: include("module.view")
                    if type(includeParams['module']) not in [_ast3.Attribute, _ast3.List, _ast3.Name]:
                        moduleLocalPath = includeParams['module'].replace('.', '/') + '.py'
                        fp = os.path.join(self.workingDir,         self.projectRootDir, moduleLocalPath)

                        # Find all urls in referenced module
                        calls = self._find_all_url_calls(self.processor.strip_work_dir(fp))
                        for call in calls:
                            # recurse over all the url() calls
                            self._resolve_url_call_to_views(call, self.processor.strip_work_dir(fp), endpoint)

                    # this accounts for the following: include([url(),url()])
                    elif type(includeParams['module']) is _ast3.List:
                        for elem in includeParams['module'].elts:
                            if type(elem) is _ast3.Call and elem.func.id == "url":
                                filepath = filepath if self.workingDir not in filepath else self.processor.strip_work_dir(filepath)
                                self._resolve_url_call_to_views(elem, filepath, endpoint)

                    # this accounts for the following: include(module.view) Notice no ""
                    elif type(includeParams['module']) is _ast3.Attribute:
                        # TODO
                        pass

                    # this accounts for the following: include(name) when imported as "from x import y as name"
                    elif type(includeParams['module']) is _ast3.Name:
                        # TODO
                        pass
                else:
                    # This url() call doesn't contain an include() so we can
                    # add endpoint mapping to list for more processing later
                    self.tempRecursedEndpoints.append(endpoint)

            else:
                logger.warning("It looks like there was a faulty url() call")

    def _find_project_root(self):
        # locate where manage.py is located in the project and assume that's the root of the project's code
        try:
            managePath = list(filter(lambda x: 'manage.py' in x[0], self.processor.pythonFileAsts.items()))[0]
        except IndexError:
            # This project isn't a python project
            return ''

        return managePath[0].replace('manage.py', '')

    def _find_root_urls_file(self):
        # Attempt to find setting folder or settings.py
        managePath = os.path.join(self.projectRootDir, 'manage.py')
        manageAST = self.processor.pythonFileAsts[managePath]
        settingsModule = None
        for call in self.processor.filter_ast(manageAST, _ast3.Call):
            if len(call.args) == 2 and ast3.literal_eval(call.args[0]) == 'DJANGO_SETTINGS_MODULE':
                settingsModule = ast3.literal_eval(call.args[1])
                break

        if settingsModule:
            settingModule = os.path.join(self.projectRootDir, settingsModule.replace('.', '/'))
            if settingModule + '.py' in self.processor.pythonFileAsts:
                myAst = self.processor.pythonFileAsts[settingModule + '.py']
                for assign in self.processor.filter_ast(myAst, _ast3.Assign):
                    # parse through AST of settings.py
                    if len(assign.targets) == 1 and assign.targets[0].id == 'ROOT_URLCONF':
                        rootUrls = os.path.join(self.projectRootDir, ast3.literal_eval(assign.value).replace('.', '/')) + '.py'
                        if rootUrls in self.processor.pythonFileAsts:
                            return rootUrls

            elif os.path.isdir(settingModule):
                settingsFiles = list(filter(lambda x: settingModule in x, self.processor.pythonFileAsts.keys()))
                for sf in settingsFiles:
                    myAst = self.processor.pythonFileAsts[sf]
                    for assign in self.processor.filter_ast(myAst, _ast3.Assign):
                        # parse through AST of settings.py
                        if len(assign.targets) == 1 and assign.targets[0].id == 'ROOT_URLCONF':
                            rootUrls = os.path.join(self.projectRootDir,
                                                    ast3.literal_eval(assign.value).replace('.', '/')) + '.py'
                            if rootUrls in self.processor.pythonFileAsts:
                                return rootUrls

        urlFile = None
        urlFiles = list(filter(lambda x: 'urls.py' in x, self.processor.pythonFileAsts.keys()))
        for uf in urlFiles:
            if urlFile is None or uf.count('/') < urlFile.count('/'):
                urlFile = uf

        return urlFile

    def _find_all_url_calls(self, filepath):
        try:
            root = self.processor.pythonFileAsts[filepath]
        except KeyError as e:
            logger.warning("Couldn't find this file. Possibly an external library: %s", e)
            return []

        # Find all the method Calls
        calls = self.processor.filter_ast(root, _ast3.Call)

        # Only care about url() calls
        urlCalls = list(filter(lambda x: hasattr(x.func, 'id') and x.func.id == "url", calls))

        return urlCalls

    def _flatten_recursed_endpoints(self, endpointsList):
        resultingEps = []
        for ep in endpointsList:
            view = ep['view']
            path = []
            nonStringEncountered = False

            # TODO: Process BinaryOperators and MemberReferences in regex
            if type(ep['regex']) is not str:
                nonStringEncountered = True
            path.append(ep['regex'])

            currentParent = None if not ep['parent'] else ep['parent']

            while currentParent:
                # TODO: Process BinaryOperators and MemberReferences in regex
                if type(currentParent['regex']) is not str:
                    nonStringEncountered = True

                # Add to front of list because it's the parent
                path.insert(0, currentParent['regex'])

                currentParent = currentParent['parent']

            # Don't continue processing this ep if nonStringEncountered in regex
            # TODO: This will eventually be removed because we will be able to process them
            if nonStringEncountered:
                continue

            path = self._combine_regex_url_patterns(path)

            # Find paths with \ in them and remove if they're not regex
            if '\\' in path:
                if '{' not in path and '<' not in path and '(?P' not in path:
                    path = path.replace('\\', '')
            # Account for paths ending with ?
            if path.endswith('?'):
                path = path[:-1]

            resultingEps.append({
                'endpoints': set([path]),
                'viewCall': view,
                'locationFound': ep['locationFound']
            })

        return resultingEps

    def _combine_regex_url_patterns(self, listOfRegex):
        return ("/" + "/".join(listOfRegex).replace('^', '').replace('$', '')).replace('//', '/')

    def _find_view_context(self, endpoints):
        for ep in range(len(endpoints)):
            viewCall = endpoints[ep]['viewCall']
            locationFound = endpoints[ep]['locationFound']
            baseModulePath = locationFound.split('/', 1)[0] + '/'
            view = {
                'name': None,
                'module': [],
                'moduleFilepath': None,
                'declarationLoc': locationFound
            }

            # Let's resolve views that just strings
            if type(viewCall) is str:
                view['name'] = viewCall.split('.')[-1]
                view['module'] += [var for var in baseModulePath.split('/') if var]
                view['module'] += viewCall.split('.')[:-1]
                possiblePath = '/'.join(view['module']) + '/' + view['name'] + '.py'
                if possiblePath in self.processor.pythonFileAsts:
                    view['moduleFilepath'] = possiblePath
                else:
                    possiblePath = '/'.join(view['module']) + '.py'
                    if possiblePath in self.processor.pythonFileAsts:
                        view['moduleFilepath'] = possiblePath
            # Now let's handle everything that's not a string
            else:
                tempViewName = []
                for x in ast3.walk(viewCall):
                    if hasattr(x, 'id'):
                        tempViewName.append(x.id)
                    elif hasattr(x, 'attr'):
                        tempViewName.append(x.attr)

                # Remove as_view() from name
                if 'as_view' in tempViewName:
                    tempViewName.remove('as_view')

                # Lets reverse the view name to be in the right order
                tempViewName = list(reversed(tempViewName))

                # load the value into our dictionary
                view['name'] = tempViewName[1:] if len(tempViewName) > 1 else tempViewName[0]
                view['module'] = tempViewName[0]

                # Find the module that contains the view
                myAst = self.processor.pythonFileAsts[locationFound]  # load the ast of where it was found

                # Search all the imports for view module
                imports = self.processor.filter_ast(myAst, _ast3.Import)
                for i in imports:
                    for n in i.names:
                        if n.name == view['module']:
                            view['moduleFilepath'] = self._find_module_path_from_import(locationFound,
                                                                                        i,
                                                                                        view['module'])

                        elif n.asname == view['module']:
                            view['module'] = n.name
                            view['name'][0] = n.name  # rename to real name
                            view['moduleFilepath'] = self._find_module_path_from_import(locationFound,
                                                                                        i,
                                                                                        view['module'])

                # Search all import froms for view module
                importFroms = self.processor.filter_ast(myAst, _ast3.ImportFrom)
                asteriskImports = []
                for i in importFroms:
                    for n in i.names:
                        if n.name == view['module']:
                            # we found the import let's see if we can find the file path to the module
                            view['moduleFilepath'] = self._find_module_path_from_import(locationFound,
                                                                                        i,
                                                                                        view['module'])
                        elif n.asname == view['module']:
                            # we found the import let's see if we can find the file path to the module
                            view['module'] = n.name
                            view['name'][0] = n.name  # rename to real name
                            view['moduleFilepath'] = self._find_module_path_from_import(locationFound,
                                                                                        i,
                                                                                        view['module'])
                        elif n.name == "*":
                            # Keep track of the from x import *
                            asteriskImports.append(i)

                # Check if the module is imported with an *
                if view['moduleFilepath'] is None:
                    # check if we can find the modules in the asteriskImports
                    for i in asteriskImports:
                        path = self._find_module_path_from_import(locationFound, i, view['module'])
                        if path:
                            view['moduleFilepath'] = path
                            break
            endpoints[ep]['viewFilepath'] = view['moduleFilepath']
            endpoints[ep]['viewName'] = view['name'] if type(view['name']) is str else '.'.join(view['name'])
        return endpoints

    def _find_module_path_from_import(self, locationFound, importObject, name):
        """
        This method resolves an import to a file path
        :param locationFound: The path to the file that contains the import
        :param importObject: The import object
        :param name: The name of the object/method/class you want to import
        :return: The file path to the import or None if it couldn't be found
        """
        # First we have to check if we're dealing with a * import
        if importObject.names[0] != '*':
            if isinstance(importObject, _ast3.Import):
                # Root path is current directory
                rootPath = locationFound[:locationFound.rfind('/') + 1]
                possiblePath = rootPath + name.replace('.', '/') + '.py'
                if possiblePath in self.processor.pythonFileAsts:
                    return possiblePath
            elif isinstance(importObject, _ast3.ImportFrom):
                # Root path is module directory or current directory depending on level
                modulePath = importObject.module.replace('.', '/') + '/' if importObject.module else ''
                if importObject.level > 0:
                    rootPath = locationFound[:locationFound.rfind('/') + 1]
                elif importObject.level == 0 and modulePath not in locationFound:
                    rootPath = locationFound[:locationFound.rfind('/') + 1]
                elif importObject.level == 0 and modulePath in locationFound:
                    rootPath = locationFound[:locationFound.find(modulePath)]
                else:
                    logger.warning("This is most likely a view from an external library: %s", name)
                    return None

                # Try module/name.py, then module.py
                possiblePath = rootPath + modulePath + name + '.py'
                if possiblePath in self.processor.pythonFileAsts:
                    return possiblePath
                else:
                    possiblePath = rootPath + modulePath.rstrip('/') + '.py'
                    if possiblePath in self.processor.pythonFileAsts:
                        return possiblePath
            else:
                logger.warning("This is most likely a view from an external library: %s", name)
                return None
        else:
            # This is an asterisks import so we'll have to search the module we find
            if isinstance(importObject, _ast3.ImportFrom) and importObject.level > 0:
                possiblePath = "/".join(locationFound.split('/')[:-importObject.level]) + "/"
                possiblePath += importObject.module.replace('.', '/') + "/"
                possiblePath += name + ".py"
                if possiblePath in self.processor.pythonFileAsts:
                    # We found the file for the module, let's see if it contains our import
                    tempAst = self.processor.pythonFileAsts[possiblePath]
                    for x in ast3.walk(tempAst):
                        if hasattr(x, 'name') and x.name == x['name'][0]:
                            return possiblePath
                    return None
                else:
                    possiblePath = "/".join(locationFound.split('/')[:-importObject.level]) + "/"
                    possiblePath += importObject.module.replace('.', '/') + ".py"
                    if possiblePath in self.processor.pythonFileAsts:
                        # We found the file for the module, let's see if it contains our import
                        tempAst = self.processor.pythonFileAsts[possiblePath]
                        for x in ast3.walk(tempAst):
                            if hasattr(x, 'name') and x.name == x['name'][0]:
                                return possiblePath
                        return None
            else:
                logger.warning("This is most likely an import from an external library: %s", importObject.module)
                return None

    def _find_parameters(self, endpoints):
        for i in range(len(endpoints)):
            # Find out if the view is a class or a method/function
            myAst = self.processor.pythonFileAsts[endpoints[i]['viewFilepath']]
            viewContext = None
            for x in ast3.walk(myAst):
                if hasattr(x, 'name') and x.name == endpoints[i]['viewName']:
                    viewContext = x
                    break

            # Let's add the viewContext to our endpoints dictionary
            endpoints[i]['viewContext'] = viewContext

            renderMethods = []

            method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace', 'form_valid']

            # Find all the methods/function we have to process
            if type(viewContext) is _ast3.ClassDef:
                for b in viewContext.body:
                    if type(b) is _ast3.FunctionDef and b.name in method_names:
                        renderMethods.append(b)
            elif type(viewContext) is _ast3.FunctionDef:
                renderMethods.append(viewContext)

            params = []

            for method in renderMethods:
                # Find the name of the request object within the method
                reqName = None
                if method.args.args[0].arg != 'self':
                    reqName = method.args.args[0].arg
                else:
                    if len(method.args.args) > 1:
                        reqName = method.args.args[1].arg
                    else:
                        pass

                http_methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE']

                # Now lets parse out the params

                # This section processes the following:
                # <reqName>.cleaned_data['first_name']
                # <reqName>.<method_in_caps>["id"]
                # self.request.<method_in_caps>["id"]
                subscripts = self.processor.filter_ast(method, _ast3.Subscript)
                for subscript in subscripts:
                    if (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr == 'cleaned_data' and
                            type(subscript.value.value) is _ast3.Name and
                            subscript.value.value.id):
                        # This processes the following:
                        # <reqName>.cleaned_data['first_name']
                        value = ast3.literal_eval(subscript.slice.value)
                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        paramDict = {
                            'name': value,
                            'filepath': endpoints[i]['viewFilepath'],
                            'lineNumber': subscript.lineno
                        }
                        params.append(paramDict)
                    elif (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr in http_methods and
                            type(subscript.value.value) is _ast3.Name and
                            subscript.value.value.id == reqName):
                        # This processes the following:
                        # <reqName>.<method_in_caps>["id"]
                        value = ast3.literal_eval(subscript.slice.value)
                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        paramDict = {
                            'name': value,
                            'filepath': endpoints[i]['viewFilepath'],
                            'lineNumber': subscript.lineno
                        }
                        params.append(paramDict)
                    elif (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr in http_methods and
                            type(subscript.value.value) is _ast3.Attribute and
                            subscript.value.value.attr == 'request' and
                            type(subscript.value.value.value) is _ast3.Name and
                            subscript.value.value.value.id == 'self'):
                        # This processes the following:
                        # self.request.<method_in_caps>["id"]
                        value = ast3.literal_eval(subscript.slice.value)
                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        paramDict = {
                            'name': value,
                            'filepath': endpoints[i]['viewFilepath'],
                            'lineNumber': subscript.lineno
                        }
                        params.append(paramDict)

                # This section processes the following:
                # <reqName>.<method_in_caps>.get("paramName", None)
                # self.request.<method_in_caps>.get("paramName", None)
                calls = self.processor.filter_ast(method, _ast3.Call)
                for call in calls:
                    if (type(call.func) is _ast3.Attribute and
                            call.func.attr == 'get'):
                        if (type(call.func.value) is _ast3.Attribute and
                                call.func.value.attr in http_methods):
                            if (type(call.func.value.value) is _ast3.Name and
                                    call.func.value.value.id == reqName):
                                # This processes the following:
                                # <reqName>.<method_in_caps>.get("paramName", None)
                                args = self.processor.parse_python_method_args(call, ['key', 'default'])
                                if isinstance(args['key'], (bytes, str)):
                                    value = args['key'].decode('utf-8') if type(args['key']) is bytes else args['key']
                                    paramDict = {
                                        'name': value,
                                        'filepath': endpoints[i]['viewFilepath'],
                                        'lineNumber': call.lineno
                                    }
                                    params.append(paramDict)
                            elif (type(call.func.value.value) is _ast3.Attribute and
                                    call.func.value.value.attr == 'request' and
                                    type(call.func.value.value.value) is _ast3.Name and
                                    call.func.value.value.value.id == 'self'):
                                # This processes the following:
                                # self.request.<method_in_caps>.get("paramName", None)
                                args = self.processor.parse_python_method_args(call, ['key', 'default'])
                                if isinstance(args['key'], (bytes, str)):
                                    value = args['key'].decode('utf-8') if type(args['key']) is bytes else args['key']
                                    paramDict = {
                                        'name': value,
                                        'filepath': endpoints[i]['viewFilepath'],
                                        'lineNumber': call.lineno
                                    }
                                    params.append(paramDict)

                # TODO: find the templates and see if they pull params out of the request object within the template

            endpoints[i]['params'] = params
        return endpoints

    def _find_methods(self, endpoints):
        for i in range(len(endpoints)):
            viewContext = endpoints[i]['viewContext']
            methods = set()

            # Find out if the view is a class or a method/function
            if type(viewContext) is _ast3.ClassDef:
                # find all class functions/methods
                functions = list(filter(lambda x: type(x) is _ast3.FunctionDef, viewContext.body))
                for func in functions:
                    if func.name == 'get':
                        methods.add('GET')
                    elif func.name == 'post':
                        methods.add('POST')
                    elif func.name == 'put':
                        methods.add('PUT')
                    elif func.name == 'patch':
                        methods.add('PATCH')
                    elif func.name == 'delete':
                        methods.add('DELETE')
                    elif func.name == 'head':
                        methods.add('HEAD')
                    elif func.name == 'options':
                        methods.add('OPTIONS')
                    elif func.name == 'trace':
                        methods.add('TRACE')
                    elif func.name == 'form_valid':
                        methods.add('POST')

            elif type(viewContext) is _ast3.FunctionDef:
                # Try to find comparators within the function
                # ex: if request.method == 'METHOD':
                compares = self.processor.filter_ast(viewContext, _ast3.Compare)
                for compare in compares:
                    if (type(compare.left) is _ast3.Attribute and
                            compare.left.attr == 'method' and
                            type(compare.left.value) is _ast3.Name and
                            compare.left.value.id == 'request' and
                            type(compare.comparators[0]) is _ast3.Str):
                        methods.add(ast3.literal_eval(compare.comparators[0]))

            endpoints[i]['methods'] = methods
        return endpoints

    def _add_line_numbers(self, endpoints):
        newEndpoints = []

        for ep in endpoints:
            if 'methods' in ep and ep['methods']:
                for method in ep['methods']:
                    tempEp = copy(ep)
                    tempEp['methods'] = [method]
                    tempEp['lineNumber'] = ep['viewContext'].lineno
                    newEndpoints.append(tempEp)
            else:
                tempEp = copy(ep)
                try:
                    tempEp['lineNumber'] = ep['viewContext'].lineno
                except AttributeError:
                    tempEp['lineNumber'] = None

                newEndpoints.append(tempEp)

        return newEndpoints

    def _clean_endpoints(self, endpoints):
        cleanEndpoints = []
        for ep in endpoints:
            cleanEndpoint = {}
            for k, v in ep.items():
                if k == 'viewFilepath':
                    cleanEndpoint['filepath'] = v
                if k in ['endpoints', 'params', 'methods', 'templates', 'lineNumber']:
                    cleanEndpoint[k] = v
            # TODO: This is just a simple fix to get integration tests to run correctly without pulling out the template right now
            cleanEndpoint['templates'] = set()
            if 'endpoints' in cleanEndpoint:
                cleanEndpoints.append(cleanEndpoint)
        return cleanEndpoints
