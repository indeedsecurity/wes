import glob
import codecs
import javalang
import logging
# Add to wes to the sys path
import sys
import os
from copy import copy
wes_dir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wes_dir)
from wes.framework_plugins.common import Framework

try:
    import lxml.etree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

# configure logging
logger = logging.getLogger("JavaServlet")


class CustomFramework(Framework):
    def __init__(self, working_dir, processors):
        self.working_dir = working_dir
        self.endpoints = []
        self.processor = processors['java']

    def identify(self):
        """
        This method is used to determine if the project is a Java Servlets
        application and whether it should be processed by this plugin.
        :return: Boolean
        """
        glob_path = os.path.join(self.working_dir, '**', 'WEB-INF', 'web.xml')
        files = glob.glob(glob_path, recursive=True)

        if len(files) > 0:
            return True
        else:
            return False

    def find_endpoints(self):
        """
        This method is the main method that get's called from outside this class. It works by finding the web.xml
        within the project and then attempts to parse out endpoints from it.
        :return: A list of dictionaries of Endpoints
        """
        # find the web.xml file
        web_xml_location = self._find_web_xml()

        # find all servlets in web.xml
        servlets = self._find_servlet_classes(web_xml_location)

        # If no servlets were found we can just return an empty list
        if not servlets:
            return []

        # filter out external classes and dispatcher servlets for list
        self.endpoints = list(filter(lambda x: ('class' in x and not self._is_spring_servlet_dipatcher_or_external(x['class'])) or 'templates' in x, servlets))

        # find the paths for the remaining servlets
        for i in range(len(self.endpoints)):
            self.endpoints[i]['endpoints'] = self._find_path_for_servlet(web_xml_location, self.endpoints[i]['name'])

        # Remove endpoints that we couldn't find an endpoint/path for
        self.endpoints = list(filter(lambda x: 'endpoints' in x and x['endpoints'], self.endpoints))

        # find file for each servlet
        for i in range(len(self.endpoints)):
            if 'class' in self.endpoints[i]:
                self.endpoints[i]['filepath'] = self.processor.strip_work_dir(self._find_class_file_path(self.endpoints[i]['class']))
            elif 'templates' in self.endpoints[i]:
                self.endpoints[i]['filepath'] = self.processor.strip_work_dir(web_xml_location)
                self.endpoints[i]['templates'] = [
                    self.processor.web_context_dir.rstrip('/') + '/' + self.endpoints[i]['templates'].lstrip('/')
                ]

        # look for JSPs and parameters for each endpoint
        for i in range(len(self.endpoints)):
            self.endpoints[i]['params'] = []
            self.endpoints[i]['methods'] = set()
            # The if statement is to account for servlets within the web.xml that link directly to a jsp without a class
            if 'filepath' in self.endpoints[i] and not self.endpoints[i]['filepath'].endswith('.jsp'):
                self.endpoints[i] = self._find_request_get_param(self.endpoints[i])
                self.endpoints[i] = self._find_methods_for_endpoint(self.endpoints[i])
            elif 'filepath' in self.endpoints[i] and self.endpoints[i]['filepath'].endswith('.jsp'):
                self.endpoints[i]['methods'].add("GET")  # Add GET method to JSP in web.xml

            # Find referenced jsps
            self.endpoints[i] = self._find_referenced_jsps(self.endpoints[i])
            # find params in the jsps
            if 'templates' in self.endpoints[i] and self.endpoints[i]['templates']:
                self.endpoints[i] = self._find_jsp_params(self.endpoints[i])

        # Restructure the endpoints to only have one method and add line number
        # for each method to the endpoint
        new_endpoints = []
        for ep in self.endpoints:
            if ep['methods']:
                for method in ep['methods']:
                    new_endpoint = copy(ep)
                    new_endpoint['methods'] = [method]

                    if new_endpoint['filepath'] in self.processor.java_compilation_units:
                        compilation_unit = self.processor.java_compilation_units[new_endpoint['filepath']]
                        method_declarations = compilation_unit.filter(javalang.tree.MethodDeclaration)

                        for path, md in method_declarations:
                            if md.name == "do" + method.title():
                                new_endpoint['line_number'] = md.position[0]
                                new_endpoints.append(new_endpoint)
                                break

            else:
                new_endpoints.append(ep)

        self.endpoints = new_endpoints

        return self._clean_endpoints(self.endpoints)

    def _find_web_xml(self):
        """
        This method simply tries to find the web.xml file within the project.
        It does this by looking for file that match the following path pattern:
        **/WEB-INF/web.xml
        :return: String with the path to the file
        """
        globPath = os.path.join(self.working_dir, '**', 'WEB-INF', 'web.xml')
        files = glob.glob(globPath, recursive=True)

        # We should only ever find one. We're just going to choose the first if
        # Theres more than one
        try:
            return files[0]
        except IndexError as e:
            return None

    def _find_servlet_classes(self, web_xml_location):
        """
        This method finds all the referenced classes along with the name assigned to them within a web.xml
        :param web_xml_location: The path to the web.xml file
        :return: A list of dictionaries structured like so {'name': ..., 'class': ...}
        """
        # Parse the XML file
        self._load_xml(web_xml_location)
        if self.root_element is not None:
            # loop through all the servlets
            servlets = []
            if self.namespace is not None:
                search_string = ".//{{{}}}servlet".format(self.namespace)
            else:
                search_string = ".//servlet"
            for servlet_element in self.root_element.iterfind(search_string):
                servlet = {}
                for child in servlet_element:
                    if self.namespace is not None:
                        class_search_string = "{{{}}}servlet-class".format(self.namespace)
                        name_search_string = "{{{}}}servlet-name".format(self.namespace)
                        jsp_search_string = "{{{}}}jsp-file".format(self.namespace)
                    else:
                        class_search_string = "servlet-class"
                        name_search_string = "servlet-name"
                        jsp_search_string = "jsp-file"

                    if str(child.tag).strip() == class_search_string:
                        servlet['class'] = str(child.text).strip()
                    elif str(child.tag).strip() == name_search_string:
                        servlet['name'] = str(child.text).strip()
                    elif str(child.tag).strip() == jsp_search_string:
                        servlet['templates'] = str(child.text).strip()

                if servlet:
                    servlets.append(servlet)
            return servlets

    def _find_path_for_servlet(self, web_xml_location, servlet_name):
        """
        This method finds the uri path assigned to a servlet name
        :param web_xml_location: The path to the web.xml file
        :param servlet_name: the name of the servlet
        :return: The path to a servlet or None if not found
        """
        # Parse the XML file
        self._load_xml(web_xml_location)
        if self.namespace is not None and self.root_element is not None:
            # loop through all the servlet-mappings
            if None in self.root_element.nsmap:
                search_string = ".//{{{}}}servlet-mapping".format(self.namespace)
            else:
                search_string = ".//servlet-mapping"
            for servlet_element in self.root_element.iterfind(search_string):
                servlet = {
                    'path': set(),
                    'name': None
                }
                for child in servlet_element:
                    if self.namespace is not None:
                        url_search_string = "{{{}}}url-pattern".format(self.namespace)
                        name_search_string = "{{{}}}servlet-name".format(self.namespace)
                    else:
                        url_search_string = "url-pattern"
                        name_search_string = "servlet-name"

                    if str(child.tag).strip() == url_search_string:
                        servlet['path'].add(str(child.text).strip())
                    elif str(child.tag).strip() == name_search_string:
                        servlet['name'] = str(child.text).strip()

                if servlet and 'name' in servlet and servlet['name'] == servlet_name:
                    return servlet['path']

    def _is_spring_servlet_dipatcher_or_external(self, servlet_class):
        """
        This method returns true or false for whether the supplied class
        is a spring servlet or an external class
        :param servlet_class: The fully qualified name for a class. Ex: 'com.indeed.security.wes.west.servlets.JS001'
        :return: Boolean of whether a class is a within the current project
        """
        # Dynamically check if the class is a subclass of DispatcherServlet
        class_path = self._find_class_file_path(servlet_class)
        if class_path and os.path.isfile(class_path):
            test = codecs.open(class_path, 'r', 'utf-8', 'ignore').read()
            if 'extends DispatcherServlet' in test:
                return True
            else:
                return False
        else:
            return True

    def _find_class_file_path(self, class_name):
        """
        This method attempts to find the actual filepath for the class fqn
        :param class_name: The fully qualified name for a class. Ex: 'com.indeed.security.wes.west.servlets.JS001'
        :return: The constructed file path
        """
        try:
            code_base_dir = self.processor.find_code_base_dir()

            class_path = os.path.join(code_base_dir,
                                     class_name.replace('.', '/')) + '.java'

            if os.path.isfile(class_path):
                return class_path
            else:
                # Let's attempt to find with class_lookup_table
                if class_name in self.processor.class_lookup_table:
                    # We found the file
                    class_path = os.path.join(self.working_dir,
                                             self.processor.class_lookup_table[class_name][2])

                    return class_path

        except TypeError:
            return None

    def _find_request_get_param(self, endpoint):
        """
        Find all of the Request.getParameter() for this endpoint. This looks
        under the whole file because it's a java servlet.
        :param endpoint: The endpoint dictionary which contains the 'filepath' key
        :return: The enriched endpoint dictionary
        """
        if endpoint['filepath'] in self.processor.java_compilation_units:
            compilation_unit = self.processor.java_compilation_units[endpoint['filepath']]
            method_invocations = compilation_unit.filter(javalang.tree.MethodInvocation)

            for path, mi in method_invocations:
                if mi.member == "getParameter":
                    if type(mi.arguments) is list:
                        for arg in mi.arguments:
                            if type(arg) is javalang.tree.Literal:
                                value = arg.value.strip("\"'")
                                param_dict = {
                                    'name': value,
                                    'filepath': endpoint['filepath'],
                                    'line_number': arg.position[0]
                                }
                                endpoint['params'].append(param_dict)
                            elif type(arg) is javalang.tree.MemberReference:
                                value = self.processor.resolve_member_reference(compilation_unit, arg.member, arg.qualifier)
                                if value:
                                    param_dict = {
                                        'name': value,
                                        'filepath': endpoint['filepath'],
                                        'line_number': arg.position[0]
                                    }
                                    endpoint['params'].append(param_dict)

        return endpoint

    def _find_referenced_jsps(self, endpoint):
        """
        Find all of the referenced JSPs
        :param endpoint: The endpoint dictionary which can contain an existing 'templates' key
        :return: The enriched endpoint dictionary
        """
        # look for references to JSPs from within the endpoint's scope
        template_paths = set()

        # if jsp was found in web.xml we'll want to process that too
        if 'templates' in endpoint:
            template_paths |= set(endpoint['templates'])

        if endpoint['filepath'] in self.processor.java_compilation_units:
            # look for getRequestDispatcher()
            compilation_unit = self.processor.java_compilation_units[endpoint['filepath']]
            method_invocations = compilation_unit.filter(javalang.tree.MethodInvocation)
            for path, mi in method_invocations:
                if mi.member == "getRequestDispatcher":
                    if type(mi.arguments[0]) is javalang.tree.Literal:
                        value = mi.arguments[0].value.strip("\"'")
                        if value.endswith(".jsp"):
                            template_paths.add(value.lstrip("/"))
                    elif type(mi.arguments[0]) is javalang.tree.MemberReference:
                        value = self.processor.resolve_member_reference(path[0], mi.arguments[0].member,
                                                                        mi.arguments[0].qualifier)
                        if value:
                            if value.endswith(".jsp"):
                                template_paths.add(value.lstrip("/"))

        # Add JSP references to endpoint
        full_template_paths = []
        for path in template_paths:
            if self.processor.web_context_dir not in path:
                full_template_paths.append(self.processor.web_context_dir + path)
            else:
                full_template_paths.append(path)
        endpoint['templates'] = set(full_template_paths)

        return endpoint

    def _find_jsp_params(self, endpoint):
        """
        Find all of the referenced JSPs
        :param endpoint: The endpoint dictionary which contains a 'templates' key
        :return: The enriched endpoint dictionary
        """
        template_paths = endpoint['templates']
        template_paths = list(map(lambda x: x.replace(self.processor.web_context_dir, ''), template_paths))

        # Process the JSPs found
        for template in template_paths:
            found_params = self.processor.get_jsp_params(template)
            found_params = list(map(lambda x: {'name': x, 'filepath': template}, found_params))
            if found_params:
                endpoint['params'] += found_params

        return endpoint

    def _find_methods_for_endpoint(self, endpoint):
        """
        This method find all of the methods that can be used with the endpoint
        :param endpoint: The endpoint dictionary which contains a 'filepath' key
        :return: The enriched endpoint dictionary
        """
        if endpoint['filepath'] in self.processor.java_compilation_units:
            compilation_unit = self.processor.java_compilation_units[endpoint['filepath']]
            method_declarations = compilation_unit.filter(javalang.tree.MethodDeclaration)

            for path, md in method_declarations:
                if md.name == "doGet":
                    endpoint['methods'].add("GET")
                elif md.name == "doPost":
                    endpoint['methods'].add("POST")
                elif md.name == "doDelete":
                    endpoint['methods'].add("DELETE")
                elif md.name == "doHead":
                    endpoint['methods'].add("HEAD")
                elif md.name == "doOptions":
                    endpoint['methods'].add("OPTIONS")
                elif md.name == "doPut":
                    endpoint['methods'].add("PUT")
                elif md.name == "doTrace":
                    endpoint['methods'].add("TRACE")

        return endpoint

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

    def _convert_endpoint_to_python_regex(self, endpoint):
        """
        Converts a java regex endpoint string to be in a python format
        :param endpoint: The endpoint string with regex
        :return: returns string with regex convert to a python recognized regex
        """
        if '*' in endpoint:
            endpoint = endpoint.replace('*', '[^/]*')

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
                    for ep in v:
                        if '*' in ep or ('{' in ep and '}' in ep):
                            cleaned_eps.add(self._convert_endpoint_to_python_regex(ep))
                        else:
                            cleaned_eps.add(ep)
                    v = cleaned_eps
                if k in ['endpoints', 'params', 'methods', 'filepath', 'templates', 'line_number']:
                    clean_endpoint[k] = v
            if 'endpoints' in clean_endpoint:
                clean_endpoints.append(clean_endpoint)
        return clean_endpoints
