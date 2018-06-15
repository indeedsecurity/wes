import glob
import javalang
import codecs
import re
import logging
# Add to wes to the sys path
import sys
import os
wes_dir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wes_dir)
from wes.framework_plugins.common import Framework

try:
    import lxml.etree as ET

except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

# configure logging
logger = logging.getLogger("Spring")


class CustomFramework(Framework):
    def __init__(self, working_dir, processors):
        self.working_dir = working_dir
        self.element_tree = None
        self.endpoints = []
        self.processor = processors['java']

    def _load_xml(self, filepath):  # pragma: no cover
        """
        Used to load the web.xml file into the object for the identify method
        :param filepath: The path to the web.xml
        :return: None
        """
        try:
            parser = ET.XMLParser(resolve_entities=False)
            self.element_tree = ET.parse(filepath, parser)
            self.root_element = self.element_tree.getroot()
            if None in self.root_element.nsmap:
                self.namespace = self.root_element.nsmap[None]
            else:
                self.namespace = None
        except Exception as e:
            logger.warning("There was a problem parsing the xml: %s", e)
            self.element_tree = None
            self.root_element = None

    def identify(self):
        """
        Used to detect whether the project uses Spring. It does this by loading
        the WEB-INF/web.xml file and check if there's a element that references
        the spring DispatcherServlet.
        :return: Boolean of whether it's a spring project
        """
        glob_path = os.path.join(self.working_dir, '**', 'WEB-INF', 'web.xml')
        files = list(glob.glob(glob_path, recursive=True))

        # Loop through files looking for spring declaration
        for f in files:
            self._load_xml(f)
            if self.root_element is not None:
                if self.namespace is not None:
                    search_string = ".//{{{}}}servlet-class".format(self.namespace)
                else:
                    search_string = ".//servlet-class"
                for servlet in self.root_element.iterfind(search_string):
                    if 'org.springframework.web.servlet.DispatcherServlet' in servlet.text:
                        return True
                    # Dynamically check if the class is a subclass of
                    # DispatcherServlet
                    code_base_dir = self.processor.find_code_base_dir(f)

                    class_path = os.path.join(code_base_dir,
                                             servlet.text.replace('.', '/')) + '.java'

                    if os.path.isfile(class_path):  # pragma: no cover
                        file_contents = codecs.open(class_path, 'r', 'utf-8', 'ignore').read()
                        if 'extends DispatcherServlet' in file_contents:
                            return True
                        elif 'extends org.springframework.web.servlet.DispatcherServlet':
                            return True

        # If we couldn't construct the base code dir correctly let's just search
        # the class_lookup_table and see if it extends the DispatcherServlet
        for f in files:
            self._load_xml(f)
            if self.root_element is not None:
                if self.namespace is not None:
                    search_string = ".//{{{}}}servlet-class".format(self.namespace)
                else:
                    search_string = ".//servlet-class"
                for servlet in self.root_element.iterfind(search_string):
                    if servlet.text in self.processor.class_lookup_table:
                        # We found the file lets see if it extends DispatcherServlet
                        class_path = os.path.join(self.working_dir,
                                                 self.processor.class_lookup_table[servlet.text][2])

                        file_contents = codecs.open(class_path, 'r', 'utf-8', 'ignore').read()
                        if 'extends DispatcherServlet' in file_contents:
                            return True
                        elif 'extends org.springframework.web.servlet.DispatcherServlet':
                            return True

        # Let's see if the project is using the new method of implementing
        # spring. The new method deosn't require the web.xml file and just
        # implements WebApplicationInitializer or
        # extends AbstractAnnotationConfigDispatcherServletInitializer
        glob_path = os.path.join(self.working_dir, '**', '*.java')
        files = glob.glob(glob_path, recursive=True)

        for f in files:  # pragma: no cover
            with codecs.open(f, 'r', 'utf-8', 'ignore') as fh:
                contents = fh.read()
            if 'implements WebApplicationInitializer' in contents:
                return True
            elif 'extends AbstractAnnotationConfigDispatcherServletInitializer' in contents:
                return True
            elif 'extends WebMvcConfigurerAdapter' in contents:
                return True
            elif 'org.springframework.boot.SpringApplication' in contents:
                return True
            elif 'org.springframework.context.annotation.ComponentScan' in contents and '@ComponentScan' in contents:
                return True

        return False

    def find_endpoints(self):
        """
        This method is the overaching method that gets called from outside the
        Class and will return all of the Spring endpoints it found for the
        project along with the methods and attributes.
        :return: List of cleaned endpoint dictionaries
        """
        # Find all the @RequestMappings in the project and create endpoint
        # objects for each one
        for f in self.processor.java_compilation_units:
            self._find_request_mappings(f)

        # Loop through the list of endpoints and find the params for each based
        # on the path where the ReqMap was found.
        for i in range(len(self.endpoints)):
            self.endpoints[i] = self._find_parameters(self.endpoints[i])

        return self._clean_endpoints(self.endpoints)

    def _find_request_mappings(self, filepath):
        """
        This is a finds all @RequestMapping annotations in the code and then
        creates Endpoint dictionaries for each.
        :param filepath: The filepath to the script file
        :return: None
        """
        spring_annos = ["RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping"]
        tree = self.processor.java_compilation_units[filepath]

        # Use the Javalang filter method to find all annotations in that
        # specific file and loop through them checking if they're ReqMaps
        for path, anno in tree.filter(javalang.tree.Annotation):
            if anno.name in spring_annos:
                # Checks if the ReqMap is on a class
                if self.processor.check_annotation_type(path) == 'class':
                    continue  # the ReqMap is on a class we'll skip it for now

                # Check if the parent class is an abstract class
                parent_class = self._get_parent_class(path)
                if parent_class and hasattr(parent_class, 'modifiers') and 'abstract' in parent_class.modifiers:
                    # TODO: Handle abstract classes
                    continue  # ignoring abstract classes for now

                if not self._has_controller_anno(path):
                    # The parent class doesn't have a controller Anno skip for now
                    continue

                # Parse out ReqMap parameters
                ep = self._parse_req_map_annotation(anno, tree)

                ep['line_number'] = self.processor.get_parent_declaration(path).position[0]

                # Attempt to parse out parent class ReqMap anno params
                parent_req_map = self._get_parent_request_mapping(path)

                # If there's a parent ReqMap combine the child with the parent
                if parent_req_map is not None:
                    ep = self._combine_endpoint_sets(parent_req_map, ep)

                # Construct path to the Method Declaration
                # Pop last element off path until type is MethodDeclaration
                java_path = list(path)
                while type(java_path[-1]) is not javalang.tree.MethodDeclaration:
                    java_path.pop()
                java_path = tuple(java_path)

                if ep and ('endpoints' in ep) and ep['endpoints']:
                    self.endpoints.append({
                        'java_path': java_path,
                        'filepath': filepath,
                        **ep
                    })

    def _has_controller_anno(self, path):
        """
        This method takes a path and attempts to find a @Controller annotation
        on the class level.
        :param path: The javalang path to the element
        :return: Boolean (True if there's a @Controller or @RestController on the class)
        """
        parent_class = self._get_parent_class(path)

        # We found the parent class now let's loop through it's
        # annotations if it has any
        if hasattr(parent_class, 'annotations'):
            for anno in parent_class.annotations:
                # Check if the parent class is a controller
                if anno.name in ['Controller', 'RestController']:
                    return True
            # Return false if no controller anno found
            return False

    def _get_parent_class(self, path):
        """
        This method is used to find the parent class in a supplied path
        :param path: The javalang path to the element
        :return: The javalang.tree.ClassDeclaration element
        """
        for element in reversed(path):
            if type(element) is javalang.tree.ClassDeclaration:
                return element

    def _get_parent_request_mapping(self, path):
        """
        This method simply finds the parent class then attempts to parse the
        RequestMapping arguments and returns them.
        :param path: The javalang path to the element
        :return: None or the parsed params from the class level RequestMapping
        """
        parent_class = self._get_parent_class(path)
        tree = path[0]

        # We found the parent class now let's loop through it's
        # annotations if it has any
        if hasattr(parent_class, 'annotations'):
            for anno in parent_class.annotations:
                # Check if there's a parent ReqMap
                if anno.name == "RequestMapping":
                    # we have a parent endpoint
                    return self._parse_req_map_annotation(anno, tree)

    def _parse_req_map_annotation(self, annotation, tree):
        """
        This method is used to parse the data within the parenthesis of the
        request mapping annotation. ex. @RequestMapping(<here>)
        :param annotation: The javalang.tree.Annotation object
        :param tree: The Javalang tree
        :return: An endpoint dictionary for the ReqMap
        """
        params = annotation.element
        # Create an empty Dict that will later be returned
        endpoint_dict = {
            'endpoints': set(),
            'methods': set(),
            'params': [],
            'headers': []
        }

        # Process the parameter passed into the ReqMap into a Dictionary
        parameters = self._parse_anno_args_to_dict(params)

        # Resolve the values within the dictionary to python values
        resolved_parameters = self._resolve_values_in_dict(parameters, tree)

        # We've resolved the values now let's make an endpoint for it
        if 'value' in resolved_parameters:
            if type(resolved_parameters['value']) is list:
                endpoint_dict['endpoints'] = endpoint_dict['endpoints'] | set(resolved_parameters['value'])
            else:
                endpoint_dict['endpoints'].add(resolved_parameters['value'])
        if 'method' in resolved_parameters:
            if type(resolved_parameters['method']) is list:
                endpoint_dict['methods'] = endpoint_dict['methods'] | set(resolved_parameters['method'])
            else:
                endpoint_dict['methods'].add(resolved_parameters['method'])
        if 'params' in resolved_parameters:
            if type(resolved_parameters['params']) is not list:
                resolved_parameters['params'] = [resolved_parameters['params']]
                for param in resolved_parameters['params']:
                    param_dict = {}

                    if '=' in param:
                        param_dict['name'] = param.split('=')[0]
                        param_dict['value'] = param.split('=')[1]
                    else:
                        param_dict['name'] = param
                    
                    endpoint_dict['params'].append(param_dict)
        if 'headers' in resolved_parameters:
            if type(resolved_parameters['headers']) is not list:
                resolved_parameters['headers'] = [resolved_parameters['headers']]
                for header in resolved_parameters['headers']:
                    header_dict = {}

                    if '=' in header:
                        header_dict['name'] = header.split('=')[0]
                        header_dict['value'] = header.split('=')[1]
                    else:
                        header_dict['name'] = header
                    
                    endpoint_dict['headers'].append(header_dict)

        # Add methods for shorthand mappings
        if annotation.name.endswith('Mapping') and annotation.name != 'RequestMapping':
            method = annotation.name[:-len('Mapping')]
            endpoint_dict['methods'].add(method.upper())

        return endpoint_dict

    def _parse_anno_args_to_dict(self, params):
        """
        This method simply takes the arguments passed into a ReqMap and returns
        them within a Python Dictionary.
        :param params: Then Annotation.element object with all the arguments
        passed into the ReqMap
        :return: Python Dictionary
        """
        param_dict = {}

        # Make params into list if it isn't a list already
        if type(params) is not list:
            params = [params]

        # loop through the list of params
        for param in params:
            if type(param) is javalang.tree.ElementValuePair:
                if param.name == 'path':
                    param_dict['value'] = param.value
                else:
                    param_dict[param.name] = param.value
            else:
                param_dict['value'] = param

        return param_dict

    def _resolve_values_in_dict(self, my_dict, tree):
        """
        This method takes a dictionary with Javalang object within the values
        and attempts to resolve the values for each key.
        :param my_dict: The dictionary with javalang objects in the values
        :param tree: The javalang tree
        :return: The resolved python dictionary
        """
        resolved_dict = {}

        # Loop through the dictionary resolving the values
        for original_key, original_value in my_dict.items():
            resolved_value = None  # Placeholder for the final value

            # If the Dict value is a ElementArrayValue convert to list
            # Make all other lists with a single element
            if type(original_value) is javalang.tree.ElementArrayValue:
                original_value = original_value.values
            elif type(original_value) is not list:
                original_value = [original_value]

            # loop through the list we just created
            for val in original_value:
                temp_value = None  # Placeholder for when there are multiple elements in the list

                # Resolve if type is javalang.tree.Literal
                if type(val) is javalang.tree.Literal:
                    temp_value = val.value.strip('" \'')

                # Resolve if type is javalang.tree.MemberReference
                elif type(val) is javalang.tree.MemberReference:
                    if original_key != 'method':
                        temp_value = self.processor.resolve_member_reference(tree, val.member, val.qualifier)
                    else:
                        # The key is 'method' so we'll process those MemberReferences differently
                        if 'GET' in val.children:
                            temp_value = "GET"
                        elif 'POST' in val.children:
                            temp_value = "POST"
                        elif 'DELETE' in val.children:
                            temp_value = "DELETE"
                        elif 'HEAD' in val.children:
                            temp_value = "HEAD"
                        elif 'OPTIONS' in val.children:
                            temp_value = "OPTIONS"
                        elif 'PUT' in val.children:
                            temp_value = "PUT"
                        elif 'TRACE' in val.children:
                            temp_value = "TRACE"

                # Resolve if type is javalang.tree.BinaryOperation
                elif type(val) is javalang.tree.BinaryOperation:
                    path_to_element = self.processor.find_path_to_element(tree, val)
                    if type(path_to_element) is list:  # pragma: no cover
                        try:
                            path_to_element = list(filter(lambda x: 'Annotation' in str(x), path_to_element))[0]
                        except:
                            path_to_element = path_to_element[0]
                    temp_value = self.processor._resolve_binary_operation((path_to_element, val))

                # Copy temp_value over to value variable and make list if there's
                # already a value there
                if temp_value is not None:
                    if resolved_value is None:
                        resolved_value = temp_value
                    elif type(resolved_value) is list:
                        resolved_value.append(temp_value)
                    else:
                        resolved_value = [resolved_value, temp_value]

            if resolved_value is not None:
                resolved_dict[original_key] = resolved_value

        return resolved_dict

    def _combine_endpoint_sets(self, parent_ep, child_ep):
        """
        This method is used to combine a parent ReqMap with a child
        ReqMap.
        :param parent_ep: An endpoint dictionary representing a parent ReqMap
        :param child_ep: An endpoint dictionary representing a child ReqMap
        :return: A combined endpoint dictionary
        """
        combined_ep = {
            'endpoints': set(),
            'methods': set(),
            'params': [],
            'headers': [],
            'line_number': None
        }
        if 'endpoints' in parent_ep:
            for pep in parent_ep['endpoints']:
                if child_ep and 'endpoints' in child_ep and len(child_ep['endpoints']) > 0:

                    for cep in child_ep['endpoints']:
                        if cep and pep:
                            combined_ep['endpoints'].add(pep.rstrip('/') + '/' + cep.lstrip('/'))
                else:
                    combined_ep['endpoints'].add(pep)
        else:
            combined_ep['endpoints'] |= child_ep['endpoints']

        if child_ep and 'methods' in child_ep:
            combined_ep['methods'] |= child_ep['methods']
        if child_ep and 'params' in child_ep:
            combined_ep['params'] += child_ep['params']
        if parent_ep and 'params' in parent_ep:
            combined_ep['params'] += parent_ep['params']
        if parent_ep and 'headers' in parent_ep:
            combined_ep['headers'] += parent_ep['headers']

        if 'line_number' in child_ep:
            combined_ep['line_number'] = child_ep['line_number']

        return combined_ep

    def _find_parameters(self, endpoint):
        """
        This method is use to call all of the separate method for finding
        endpoint parameters.
        :param endpoint: An endpoint dictionary
        :return: The Enriched endpoint dictionary
        """
        endpoint = self._find_request_param(endpoint)
        endpoint = self._find_request_get_param(endpoint)

        # Find all referenced JSPs then parse them for params
        endpoint = self._find_referenced_jsps(endpoint)
        endpoint = self._find_params_in_jsps(endpoint)

        return endpoint

    def _find_request_param(self, endpoint):
        """
        Find all of the @RequestParam's for the given endpoint
        :param endpoint: An endpoint dictionary
        :return: The Enriched endpoint dictionary
        """
        tree = self.processor.get_compilation_unit(endpoint['java_path'])
        method = self.processor.get_parent_declaration(endpoint['java_path'])

        # Check parameters of method for @RequestParam or String
        for param in method.parameters:
            # Filter by spring annotations
            spring_annos = [x.name for x in param.annotations if self._is_spring_object(x.name, tree)]

            if spring_annos and 'RequestParam' in spring_annos:
                for anno in param.annotations:
                    if anno.name == 'RequestParam':
                        # Found a RequestParam now let's parse it
                        parameter = self._parse_req_param_anno(anno, tree)
                        if parameter is None or parameter == "":
                            parameter = param.name

                        param_dict = {
                            'name': parameter,
                            'filepath': endpoint['filepath'],
                            'line_number': anno.position[0]
                        }

                        endpoint['params'].append(param_dict)
            elif not spring_annos and param.type.name == 'String':
                param_dict = {
                    'name': param.name,
                    'filepath': endpoint['filepath'],
                    'line_number': param.position[0]
                }

                endpoint['params'].append(param_dict)

        return endpoint

    def _parse_req_param_anno(self, anno, tree):
        """
        Parses the parameters of the @RequestParam annotation. If there
        aren't any params this method will just return None.
        :param anno: A javalang.tree.Annotation object for a RequestParam
        :param tree: The javalang tree
        :return: The parameter name for the annotation
        """
        if hasattr(anno, 'element') and anno.element:
            params = anno.element
            parameters = self._parse_anno_args_to_dict(params)
            resolved_parameters = self._resolve_values_in_dict(parameters, tree)

            if 'value' in resolved_parameters:
                return resolved_parameters['value']

    def _find_request_get_param(self, endpoint):
        """
        Find all of the Request.getParameter() for this endpoint
        :param endpoint: An endpoint dictionary
        :return: The enriched endpoint dictionary
        """
        tree = self.processor.get_compilation_unit(endpoint['java_path'])
        search_node = self.processor.get_parent_declaration(endpoint['java_path'])

        # Find all method invocation within this method
        method_invocations = self.processor.filter_on_path(search_node, javalang.tree.MethodInvocation, tree)

        for path, mi in method_invocations:
            if mi.member == "getParameter":
                if type(mi.arguments) is list:
                    resolved_parameters = self._resolve_values_in_dict({'params': mi.arguments}, tree)
                    if 'params' in resolved_parameters and resolved_parameters['params']:
                        endpoint['params'].append({
                            'name': resolved_parameters['params'],
                            'filepath': endpoint['filepath'],
                            'line_number': mi.position[0]
                        })

        return endpoint

    def _find_referenced_jsps(self, endpoint):
        """
        Find all of the param.* within the JSP for this endpoint
        :param endpoint:
        :return:
        """
        # look for references to JSPs from within the endpoint's scope
        template_paths = set()

        tree = self.processor.get_compilation_unit(endpoint['java_path'])
        search_node = self.processor.get_parent_declaration(endpoint['java_path'])

        # look for return new ModelAndView()
        class_creators = self.processor.filter_on_path(search_node, javalang.tree.ClassCreator, tree)
        for path, cc in class_creators:
            if cc.type.name == "ModelAndView" and hasattr(cc, 'arguments') and len(cc.arguments) > 0:
                resolved_values = self._resolve_values_in_dict({'jsp': cc.arguments[0]}, tree)
                if 'jsp' in resolved_values and resolved_values['jsp'] and resolved_values['jsp'].endswith(".jsp"):
                    template_paths.add(resolved_values['jsp'].lstrip('/'))

        # look for return [String]
        return_statements = self.processor.filter_on_path(search_node, javalang.tree.ReturnStatement, tree)
        for path, rs in return_statements:
            resolved_values = self._resolve_values_in_dict({'jsp': rs.expression}, tree)
            if 'jsp' in resolved_values and resolved_values['jsp'] and resolved_values['jsp'].endswith(".jsp"):

                if ":" in resolved_values['jsp']:
                    resolved_values['jsp'] = resolved_values['jsp'].split(":")[1]

                template_paths.add(resolved_values['jsp'].lstrip('/'))


        # look for getRequestDispatcher()
        method_invocations = self.processor.filter_on_path(search_node, javalang.tree.MethodInvocation, tree)
        for path, mi in method_invocations:
            if mi.member == "getRequestDispatcher":
                resolved_values = self._resolve_values_in_dict({'jsp': mi.arguments[0]}, tree)
                if 'jsp' in resolved_values and resolved_values['jsp'] and resolved_values['jsp'].endswith(".jsp"):
                    template_paths.add(resolved_values['jsp'].lstrip('/'))

        # Add JSP references to endpoint
        full_template_paths = []
        for path in template_paths:
            full_template_paths.append(self.processor.web_context_dir + path)
        endpoint['templates'] = set(full_template_paths)

        return endpoint

    def _find_params_in_jsps(self, endpoint):
        """
        Take an endpoint dictionary with a templates key. It then attempts
        to parse the params from the template/jsp.
        :param endpoint: An endpoint dictionary
        :return: The enriched endpoint dictionary
        """
        # Process the JSPs found
        for template in endpoint['templates']:
            relative_path = template.split(self.processor.web_context_dir)[1]
            found_params = self.processor.get_jsp_params(relative_path)
            found_params = list(map(lambda x: {'name': x, 'filepath': template}, found_params))
            if found_params:
                endpoint['params'] += found_params

        return endpoint

    def _convert_endpoint_to_python_regex(self, endpoint):
        """
        Converts a java regex endpoint string to be in a python format
        :param endpoint: The endpoint string with regex
        :return: returns string with regex convert to a python recognized regex
        """
        if '*' in endpoint:
            endpoint = re.sub(r'(?<!\*)\*(?!\*)', '[^/]*', endpoint)
        if '**' in endpoint:
            endpoint = endpoint.replace('**', '.*')
        if '{' in endpoint and '}' in endpoint: # pragma: no cover
            # TODO: this is really messy I should really swap this with a tokenizing approach
            while re.match(r'.*{\w+:.+}.*', endpoint):
                if re.match(r'.*{\w+:.*({.*})+.*}.*', endpoint):
                    endpoint = re.sub(r'{(\w+):(.*({.*})+.*)}', r'(?P<\1>\2)', endpoint)
                else:
                    endpoint = re.sub(r'{(\w+):([^{}]+)}', r'(?P<\1>\2)', endpoint)
            while re.match(r'.*{[^\d{}]+}.*', endpoint):
                endpoint = re.sub(r'{([^\d{}]+)}', r'(?P<\1>[^/]*)', endpoint)

        return endpoint

    def _clean_endpoints(self, endpoints):
        """
        This method takes the list of endpoint dictionaries and removes un-needed keys
        :param endpoints: List of endpoint dictionaries
        :return: List of cleaned endpoints
        """
        clean_endpoints = []
        for ep in endpoints:
            clean_endpoint = {}
            for k, v in ep.items():
                if k == 'endpoints':
                    cleaned_eps = set()
                    for endpoint in v:
                        if '*' in endpoint or ('{' in endpoint and '}' in endpoint):
                            cleaned_eps.add(self._convert_endpoint_to_python_regex(endpoint))
                        else:
                            cleaned_eps.add(endpoint)
                    v = cleaned_eps
                if k in ['endpoints', 'params', 'methods', 'filepath', 'templates', 'headers', 'line_number']:
                    clean_endpoint[k] = v
            if 'endpoints' in clean_endpoint:
                clean_endpoints.append(clean_endpoint)
        return clean_endpoints

    def _is_spring_object(self, name, tree):
        """
        Check if it is a Spring object according to import resolution. Spring objects start with org.springframework.
        :param name: Name of object
        :param tree: Class tree
        :return: True if Spring, false otherwise
        """
        parent = '.' + name.split('.')[0]

        # Find import statement
        for imp in tree.imports:
            if imp.path.endswith(parent):

                # Check Spring
                if imp.path.startswith('org.springframework.'):
                    return True
                else:
                    return False

        # Default
        return False
