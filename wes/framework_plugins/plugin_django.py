import glob
import codecs
import logging
from typed_ast import ast3, _ast3
# Add to wes to the sys path
import sys
import os
from copy import copy
wes_dir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wes_dir)
from wes.framework_plugins.common import Framework

# configure logging
logger = logging.getLogger(__name__)


class CustomFramework(Framework):
    def __init__(self, working_dir, processors):
        self.working_dir = working_dir
        self.temp_recursed_endpoints = []
        self.endpoints = []
        self.processor = processors['python']
        self.project_root_dir = self._find_project_root()

    def identify(self):
        """
        This method is used to determine if the project is a django
        application and whether it should be processed by this plugin.
        """
        # Find all *.py files in the project
        glob_path = os.path.join(self.working_dir, '**', '*.py')
        files = glob.glob(glob_path, recursive=True)

        files = list(filter(lambda x: os.path.isfile(x), files))

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
        root_urls_file_path = self._find_root_urls_file()

        # Find all url() calls in the file
        url_calls = self._find_all_url_calls(root_urls_file_path)

        # Loop through url calls and find all the referenced calls
        for call in url_calls:
            self._resolve_url_call_to_views(call, root_urls_file_path)

        # Flatten the self.temp_recursed_endpoints list
        self.endpoints = self._flatten_recursed_endpoints(self.temp_recursed_endpoints)

        # Find view file location and context
        self.endpoints = self._find_view_context(self.endpoints)

        # Remove endpoints we couldn't locate the view to
        self.endpoints = list(filter(lambda x: x['view_filepath'], self.endpoints))

        # Find parameters
        self.endpoints = self._find_parameters(self.endpoints)

        # Find methods
        self.endpoints = self._find_methods(self.endpoints)

        # Split endpoints into single methods and add line numbers
        self.endpoints = self._add_line_numbers(self.endpoints)

        # clean endpoint fields
        return self._clean_endpoints(self.endpoints)

    def _resolve_url_call_to_views(self, url_call, filepath, parent=None):
        if type(url_call) is _ast3.Call and url_call.func.id == 'url':
            # Lets parse the args out of the url(args) call
            endpoint = self.processor.parse_python_method_args(url_call, ['regex', 'view', 'kwargs', 'name'])

            # Add parent to list
            endpoint['parent'] = parent

            # Add file location the url was found so that the view path can be resolved
            endpoint['location_found'] = filepath

            # Make sure we get the required arguments
            if 'regex' in endpoint and 'view' in endpoint:
                # Check if we need to recurse
                if (type(endpoint['view']) is _ast3.Call and
                        hasattr(endpoint['view'].func, 'id') and
                        endpoint['view'].func.id == 'include'):

                    # if the url() method contains a include() then lets find the url() calls within that file
                    # Construct path to referenced module
                    include_params = self.processor.parse_python_method_args(endpoint['view'], ['module', 'namespace', 'app_name'])

                    # this accounts for the following: include("module.view")
                    if type(include_params['module']) not in [_ast3.Attribute, _ast3.List, _ast3.Name]:
                        module_local_path = include_params['module'].replace('.', '/') + '.py'
                        fp = os.path.join(self.working_dir, self.project_root_dir, module_local_path)

                        # Find all urls in referenced module
                        calls = self._find_all_url_calls(self.processor.strip_work_dir(fp))
                        for call in calls:
                            # recurse over all the url() calls
                            self._resolve_url_call_to_views(call, self.processor.strip_work_dir(fp), endpoint)

                    # this accounts for the following: include([url(),url()])
                    elif type(include_params['module']) is _ast3.List:
                        for elem in include_params['module'].elts:
                            if type(elem) is _ast3.Call and elem.func.id == "url":
                                filepath = filepath if self.working_dir not in filepath else self.processor.strip_work_dir(filepath)
                                self._resolve_url_call_to_views(elem, filepath, endpoint)

                    # this accounts for the following: include(module.view) Notice no ""
                    elif type(include_params['module']) is _ast3.Attribute:
                        # TODO
                        pass

                    # this accounts for the following: include(name) when imported as "from x import y as name"
                    elif type(include_params['module']) is _ast3.Name:
                        # TODO
                        pass
                else:
                    # This url() call doesn't contain an include() so we can
                    # add endpoint mapping to list for more processing later
                    self.temp_recursed_endpoints.append(endpoint)

            else:
                logger.warning("It looks like there was a faulty url() call")

    def _find_project_root(self):
        # locate where manage.py is located in the project and assume that's the root of the project's code
        try:
            manage_path = list(filter(lambda x: 'manage.py' in x[0], self.processor.python_file_asts.items()))[0]
        except IndexError:
            # This project isn't a python project
            return ''

        return manage_path[0].replace('manage.py', '')

    def _find_root_urls_file(self):
        # Attempt to find setting folder or settings.py
        manage_path = os.path.join(self.project_root_dir, 'manage.py')
        manage_ast = self.processor.python_file_asts[manage_path]
        settings_module = None
        for call in self.processor.filter_ast(manage_ast, _ast3.Call):
            if len(call.args) == 2 and ast3.literal_eval(call.args[0]) == 'DJANGO_SETTINGS_MODULE':
                settings_module = ast3.literal_eval(call.args[1])
                break

        if settings_module:
            setting_module = os.path.join(self.project_root_dir, settings_module.replace('.', '/'))
            if setting_module + '.py' in self.processor.python_file_asts:
                my_ast = self.processor.python_file_asts[setting_module + '.py']
                for assign in self.processor.filter_ast(my_ast, _ast3.Assign):
                    # parse through AST of settings.py
                    if len(assign.targets) == 1 and assign.targets[0].id == 'ROOT_URLCONF':
                        root_urls = os.path.join(self.project_root_dir, ast3.literal_eval(assign.value).replace('.', '/')) + '.py'
                        if root_urls in self.processor.pythonFileAsts:
                            return root_urls

            elif os.path.isdir(setting_module):
                settings_files = list(filter(lambda x: setting_module in x, self.processor.pythonFileAsts.keys()))
                for sf in settings_files:
                    my_ast = self.processor.python_file_asts[sf]
                    for assign in self.processor.filter_ast(my_ast, _ast3.Assign):
                        # parse through AST of settings.py
                        if len(assign.targets) == 1 and assign.targets[0].id == 'ROOT_URLCONF':
                            root_urls = os.path.join(self.project_root_dir,
                                                    ast3.literal_eval(assign.value).replace('.', '/')) + '.py'
                            if root_urls in self.processor.python_file_asts:
                                return root_urls

        url_file = None
        url_files = list(filter(lambda x: 'urls.py' in x, self.processor.python_file_asts.keys()))
        for uf in url_files:
            if url_file is None or uf.count('/') < url_file.count('/'):
                url_file = uf

        return url_file

    def _find_all_url_calls(self, filepath):
        try:
            root = self.processor.python_file_asts[filepath]
        except KeyError as e:
            logger.warning("Couldn't find this file. Possibly an external library: %s", e)
            return []

        # Find all the method Calls
        calls = self.processor.filter_ast(root, _ast3.Call)

        # Only care about url() calls
        url_calls = list(filter(lambda x: hasattr(x.func, 'id') and x.func.id == "url", calls))

        return url_calls

    def _flatten_recursed_endpoints(self, endpoints_list):
        resulting_eps = []
        for ep in endpoints_list:
            view = ep['view']
            path = []
            non_string_encountered = False

            # TODO: Process BinaryOperators and MemberReferences in regex
            if type(ep['regex']) is not str:
                non_string_encountered = True
            path.append(ep['regex'])

            current_parent = None if not ep['parent'] else ep['parent']

            while current_parent:
                # TODO: Process BinaryOperators and MemberReferences in regex
                if type(current_parent['regex']) is not str:
                    non_string_encountered = True

                # Add to front of list because it's the parent
                path.insert(0, current_parent['regex'])

                current_parent = current_parent['parent']

            # Don't continue processing this ep if non_string_encountered in regex
            # TODO: This will eventually be removed because we will be able to process them
            if non_string_encountered:
                continue

            path = self._combine_regex_url_patterns(path)

            # Find paths with \ in them and remove if they're not regex
            if '\\' in path:
                if '{' not in path and '<' not in path and '(?P' not in path:
                    path = path.replace('\\', '')
            # Account for paths ending with ?
            if path.endswith('?'):
                path = path[:-1]

            resulting_eps.append({
                'endpoints': set([path]),
                'view_call': view,
                'location_found': ep['location_found']
            })

        return resulting_eps

    def _combine_regex_url_patterns(self, list_of_regex):
        return ("/" + "/".join(list_of_regex).replace('^', '').replace('$', '')).replace('//', '/')

    def _find_view_context(self, endpoints):
        for ep in range(len(endpoints)):
            view_call = endpoints[ep]['view_call']
            location_found = endpoints[ep]['location_found']
            base_module_path = location_found.split('/', 1)[0] + '/'
            view = {
                'name': None,
                'module': [],
                'module_filepath': None,
                'declaration_loc': location_found
            }

            # Let's resolve views that just strings
            if type(view_call) is str:
                view['name'] = view_call.split('.')[-1]
                view['module'] += [var for var in base_module_path.split('/') if var]
                view['module'] += view_call.split('.')[:-1]
                possible_path = '/'.join(view['module']) + '/' + view['name'] + '.py'
                if possible_path in self.processor.python_file_asts:
                    view['module_filepath'] = possible_path
                else:
                    possible_path = '/'.join(view['module']) + '.py'
                    if possible_path in self.processor.python_file_asts:
                        view['module_filepath'] = possible_path
            # Now let's handle everything that's not a string
            else:
                temp_view_name = []
                for x in ast3.walk(view_call):
                    if hasattr(x, 'id'):
                        temp_view_name.append(x.id)
                    elif hasattr(x, 'attr'):
                        temp_view_name.append(x.attr)

                # Remove as_view() from name
                if 'as_view' in temp_view_name:
                    temp_view_name.remove('as_view')

                # Lets reverse the view name to be in the right order
                temp_view_name = list(reversed(temp_view_name))

                # load the value into our dictionary
                view['name'] = temp_view_name[1:] if len(temp_view_name) > 1 else temp_view_name[0]
                view['module'] = temp_view_name[0]

                # Find the module that contains the view
                my_ast = self.processor.python_file_asts[location_found]  # load the ast of where it was found

                # Search all the imports for view module
                imports = self.processor.filter_ast(my_ast, _ast3.Import)
                for i in imports:
                    for n in i.names:
                        if n.name == view['module']:
                            view['module_filepath'] = self._find_module_path_from_import(location_found,
                                                                                         i,
                                                                                         view['module'])

                        elif n.asname == view['module']:
                            view['module'] = n.name
                            view['name'][0] = n.name  # rename to real name
                            view['module_filepath'] = self._find_module_path_from_import(location_found,
                                                                                         i,
                                                                                         view['module'])

                # Search all import froms for view module
                import_froms = self.processor.filter_ast(my_ast, _ast3.ImportFrom)
                asterisk_imports = []
                for i in import_froms:
                    for n in i.names:
                        if n.name == view['module']:
                            # we found the import let's see if we can find the file path to the module
                            view['module_filepath'] = self._find_module_path_from_import(location_found,
                                                                                         i,
                                                                                         view['module'])
                        elif n.asname == view['module']:
                            # we found the import let's see if we can find the file path to the module
                            view['module'] = n.name
                            view['name'][0] = n.name  # rename to real name
                            view['module_filepath'] = self._find_module_path_from_import(location_found,
                                                                                         i,
                                                                                         view['module'])
                        elif n.name == "*":
                            # Keep track of the from x import *
                            asterisk_imports.append(i)

                # Check if the module is imported with an *
                if view['module_filepath'] is None:
                    # check if we can find the modules in the asterisk_imports
                    for i in asterisk_imports:
                        path = self._find_module_path_from_import(location_found, i, view['module'])
                        if path:
                            view['module_filepath'] = path
                            break
            endpoints[ep]['view_filepath'] = view['module_filepath']
            endpoints[ep]['view_name'] = view['name'] if type(view['name']) is str else '.'.join(view['name'])
        return endpoints

    def _find_module_path_from_import(self, location_found, import_object, name):
        """
        This method resolves an import to a file path
        :param location_found: The path to the file that contains the import
        :param import_object: The import object
        :param name: The name of the object/method/class you want to import
        :return: The file path to the import or None if it couldn't be found
        """
        # First we have to check if we're dealing with a * import
        if import_object.names[0] != '*':
            if isinstance(import_object, _ast3.Import):
                # Root path is current directory
                root_path = location_found[:location_found.rfind('/') + 1]
                possible_path = root_path + name.replace('.', '/') + '.py'
                if possible_path in self.processor.python_file_asts:
                    return possible_path
            elif isinstance(import_object, _ast3.ImportFrom):
                # Root path is module directory or current directory depending on level
                module_path = import_object.module.replace('.', '/') + '/' if import_object.module else ''
                if import_object.level > 0:
                    root_path = location_found[:location_found.rfind('/') + 1]
                elif import_object.level == 0 and module_path not in location_found:
                    root_path = location_found[:location_found.rfind('/') + 1]
                elif import_object.level == 0 and module_path in location_found:
                    root_path = location_found[:location_found.find(module_path)]
                else:
                    logger.warning("This is most likely a view from an external library: %s", name)
                    return None

                # Try module/name.py, then module.py
                possible_path = root_path + module_path + name + '.py'
                if possible_path in self.processor.python_file_asts:
                    return possible_path
                else:
                    possible_path = root_path + module_path.rstrip('/') + '.py'
                    if possible_path in self.processor.python_file_asts:
                        return possible_path
            else:
                logger.warning("This is most likely a view from an external library: %s", name)
                return None
        else:
            # This is an asterisks import so we'll have to search the module we find
            if isinstance(import_object, _ast3.ImportFrom) and import_object.level > 0:
                possible_path = "/".join(location_found.split('/')[:-import_object.level]) + "/"
                possible_path += import_object.module.replace('.', '/') + "/"
                possible_path += name + ".py"
                if possible_path in self.processor.python_file_asts:
                    # We found the file for the module, let's see if it contains our import
                    temp_ast = self.processor.python_file_asts[possible_path]
                    for x in ast3.walk(temp_ast):
                        if hasattr(x, 'name') and x.name == x['name'][0]:
                            return possible_path
                    return None
                else:
                    possible_path = "/".join(location_found.split('/')[:-import_object.level]) + "/"
                    possible_path += import_object.module.replace('.', '/') + ".py"
                    if possible_path in self.processor.python_file_asts:
                        # We found the file for the module, let's see if it contains our import
                        temp_ast = self.processor.python_file_asts[possible_path]
                        for x in ast3.walk(temp_ast):
                            if hasattr(x, 'name') and x.name == x['name'][0]:
                                return possible_path
                        return None
            else:
                logger.warning("This is most likely an import from an external library: %s", import_object.module)
                return None

    def _find_parameters(self, endpoints):
        for i in range(len(endpoints)):
            # Find out if the view is a class or a method/function
            my_ast = self.processor.python_file_asts[endpoints[i]['view_filepath']]
            view_context = None
            for x in ast3.walk(my_ast):
                if hasattr(x, 'name') and x.name == endpoints[i]['view_name']:
                    view_context = x
                    break

            # Let's add the view_context to our endpoints dictionary
            endpoints[i]['view_context'] = view_context

            render_methods = []

            method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace', 'form_valid']

            # Find all the methods/function we have to process
            if type(view_context) is _ast3.ClassDef:
                for b in view_context.body:
                    if type(b) is _ast3.FunctionDef and b.name in method_names:
                        render_methods.append(b)
            elif type(view_context) is _ast3.FunctionDef:
                render_methods.append(view_context)

            params = []

            for method in render_methods:
                # Find the name of the request object within the method
                req_name = None
                if method.args.args[0].arg != 'self':
                    req_name = method.args.args[0].arg
                else:
                    if len(method.args.args) > 1:
                        req_name = method.args.args[1].arg
                    else:
                        pass

                http_methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE']

                # Now lets parse out the params

                # This section processes the following:
                # <req_name>.cleaned_data['first_name']
                # <req_name>.<method_in_caps>["id"]
                # self.request.<method_in_caps>["id"]
                subscripts = self.processor.filter_ast(method, _ast3.Subscript)
                for subscript in subscripts:
                    if (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr == 'cleaned_data' and
                            type(subscript.value.value) is _ast3.Name and
                            subscript.value.value.id):
                        # This processes the following:
                        # <reqName>.cleaned_data['first_name']
                        try:
                            value = ast3.literal_eval(subscript.slice.value)
                        except ValueError:
                            # Happens when the parameter name is dynamically generated
                            # <reqName>.cleaned_data['first_name' + i]
                            msg = "Couldn't resolve parameter name. File '%s' line '%d'"
                            logger.warning(msg, endpoints[i]['view_filepath'], subscript.lineno)
                            continue

                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        param_dict = {
                            'name': value,
                            'filepath': endpoints[i]['view_filepath'],
                            'line_number': subscript.lineno
                        }
                        params.append(param_dict)
                    elif (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr in http_methods and
                            type(subscript.value.value) is _ast3.Name and
                            subscript.value.value.id == req_name):
                        # This processes the following:

                        # <reqName>.<method_in_caps>["id"]
                        try:
                            value = ast3.literal_eval(subscript.slice.value)
                        except ValueError:
                            # Happens when the parameter name is dynamically generated
                            # <reqName>.<method_in_caps>["id" + i]
                            msg = "Couldn't resolve parameter name. File '%s' line '%d'"
                            logger.warning(msg, endpoints[i]['view_filepath'], subscript.lineno)
                            continue

                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        param_dict = {
                            'name': value,
                            'filepath': endpoints[i]['view_filepath'],
                            'line_number': subscript.lineno
                        }
                        params.append(param_dict)
                    elif (type(subscript.value) is _ast3.Attribute and
                            subscript.value.attr in http_methods and
                            type(subscript.value.value) is _ast3.Attribute and
                            subscript.value.value.attr == 'request' and
                            type(subscript.value.value.value) is _ast3.Name and
                            subscript.value.value.value.id == 'self'):
                        # This processes the following:
                        # self.request.<method_in_caps>["id"]
                        try:
                            value = ast3.literal_eval(subscript.slice.value)
                        except ValueError:
                            # Happens when the parameter name is dynamically generated
                            # self.request.<method_in_caps>["id" + i]
                            msg = "Couldn't resolve parameter name. File '%s' line '%d'"
                            logger.warning(msg, endpoints[i]['view_filepath'], subscript.lineno)
                            continue

                        if type(value) is bytes:
                            value = value.decode("utf-8")  # Accounting for weird bug in typed-ast library
                        param_dict = {
                            'name': value,
                            'filepath': endpoints[i]['view_filepath'],
                            'line_number': subscript.lineno
                        }
                        params.append(param_dict)

                # This section processes the following:
                # <req_name>.<method_in_caps>.get("param_name", None)
                # self.request.<method_in_caps>.get("param_name", None)
                calls = self.processor.filter_ast(method, _ast3.Call)
                for call in calls:
                    if (type(call.func) is _ast3.Attribute and
                            call.func.attr == 'get'):
                        if (type(call.func.value) is _ast3.Attribute and
                                call.func.value.attr in http_methods):
                            if (type(call.func.value.value) is _ast3.Name and
                                    call.func.value.value.id == req_name):
                                # This processes the following:
                                # <req_name>.<method_in_caps>.get("param_name", None)
                                args = self.processor.parse_python_method_args(call, ['key', 'default'])
                                if isinstance(args['key'], (bytes, str)):
                                    value = args['key'].decode('utf-8') if type(args['key']) is bytes else args['key']
                                    param_dict = {
                                        'name': value,
                                        'filepath': endpoints[i]['view_filepath'],
                                        'line_number': call.lineno
                                    }
                                    params.append(param_dict)
                            elif (type(call.func.value.value) is _ast3.Attribute and
                                    call.func.value.value.attr == 'request' and
                                    type(call.func.value.value.value) is _ast3.Name and
                                    call.func.value.value.value.id == 'self'):
                                # This processes the following:
                                # self.request.<method_in_caps>.get("param_name", None)
                                args = self.processor.parse_python_method_args(call, ['key', 'default'])
                                if isinstance(args['key'], (bytes, str)):
                                    value = args['key'].decode('utf-8') if type(args['key']) is bytes else args['key']
                                    param_dict = {
                                        'name': value,
                                        'filepath': endpoints[i]['view_filepath'],
                                        'line_number': call.lineno
                                    }
                                    params.append(param_dict)

                # TODO: find the templates and see if they pull params out of the request object within the template

            endpoints[i]['params'] = params
        return endpoints

    def _find_methods(self, endpoints):
        for i in range(len(endpoints)):
            view_context = endpoints[i]['view_context']
            methods = set()

            # Find out if the view is a class or a method/function
            if type(view_context) is _ast3.ClassDef:
                # find all class functions/methods
                functions = list(filter(lambda x: type(x) is _ast3.FunctionDef, view_context.body))
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

            elif type(view_context) is _ast3.FunctionDef:
                # Try to find comparators within the function
                # ex: if request.method == 'METHOD':
                compares = self.processor.filter_ast(view_context, _ast3.Compare)
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
        new_endpoints = []

        for ep in endpoints:
            if 'methods' in ep and ep['methods']:
                for method in ep['methods']:
                    temp_ep = copy(ep)
                    temp_ep['methods'] = [method]
                    temp_ep['line_number'] = ep['view_context'].lineno
                    new_endpoints.append(temp_ep)
            else:
                temp_ep = copy(ep)
                try:
                    temp_ep['line_number'] = ep['view_context'].lineno
                except AttributeError:
                    temp_ep['line_number'] = None

                new_endpoints.append(temp_ep)

        return new_endpoints

    def _clean_endpoints(self, endpoints):
        clean_endpoints = []
        for ep in endpoints:
            clean_endpoint = {}
            for k, v in ep.items():
                if k == 'view_filepath':
                    clean_endpoint['filepath'] = v
                if k in ['endpoints', 'params', 'methods', 'templates', 'line_number']:
                    clean_endpoint[k] = v
            # TODO: This is just a simple fix to get integration tests to run correctly without pulling out the template right now
            clean_endpoint['templates'] = set()
            if 'endpoints' in clean_endpoint:
                clean_endpoints.append(clean_endpoint)
        return clean_endpoints
