import glob
import codecs
import javalang
# Add to wes to the sys path
import sys
import os
from copy import copy
wesDir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wesDir)
from wes.framework_plugins.common import Framework

try:
    import lxml.etree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET


class CustomFramework(Framework):
    def __init__(self, workingDir, processors):
        self.workingDir = workingDir
        self.endpoints = []
        self.processor = processors['java']

    def identify(self):
        """
        This method is used to determine if the project is a Java Servlets
        application and whether it should be processed by this plugin.
        :return: Boolean
        """
        globPath = os.path.join(self.workingDir, '**', 'WEB-INF', 'web.xml')
        files = glob.glob(globPath, recursive=True)

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
        webXmlLocation = self._find_web_xml()

        # find all servlets in web.xml
        servlets = self._find_servlet_classes(webXmlLocation)

        # If no servlets were found we can just return an empty list
        if not servlets:
            return []

        # filter out external classes and dispatcher servlets for list
        self.endpoints = list(filter(lambda x: ('class' in x and not self._is_spring_servlet_dipatcher_or_external(x['class'])) or 'templates' in x, servlets))

        # find the paths for the remaining servlets
        for i in range(len(self.endpoints)):
            self.endpoints[i]['endpoints'] = self._find_path_for_servlet(webXmlLocation, self.endpoints[i]['name'])

        # Remove endpoints that we couldn't find an endpoint/path for
        self.endpoints = list(filter(lambda x: 'endpoints' in x and x['endpoints'], self.endpoints))

        # find file for each servlet
        for i in range(len(self.endpoints)):
            if 'class' in self.endpoints[i]:
                self.endpoints[i]['filepath'] = self.processor.strip_work_dir(self._find_class_file_path(self.endpoints[i]['class']))
            elif 'templates' in self.endpoints[i]:
                self.endpoints[i]['filepath'] = self.processor.strip_work_dir(webXmlLocation)
                self.endpoints[i]['templates'] = [
                    self.processor.webContextDir.rstrip('/') + '/' + self.endpoints[i]['templates'].lstrip('/')
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
        newEndpoints = []
        for ep in self.endpoints:
            if ep['methods']:
                for method in ep['methods']:
                    newEndpoint = copy(ep)
                    newEndpoint['methods'] = [method]

                    if newEndpoint['filepath'] in self.processor.javaCompilationUnits:
                        compilationUnit = self.processor.javaCompilationUnits[newEndpoint['filepath']]
                        methodDeclarations = compilationUnit.filter(javalang.tree.MethodDeclaration)

                        for path, md in methodDeclarations:
                            if md.name == "do" + method.title():
                                newEndpoint['lineNumber'] = md.position[0]
                                newEndpoints.append(newEndpoint)
                                break

            else:
                newEndpoints.append(ep)

        self.endpoints = newEndpoints

        # print(self.endpoints)
        return self._clean_endpoints(self.endpoints)

    def _find_web_xml(self):
        """
        This method simply tries to find the web.xml file within the project.
        It does this by looking for file that match the following path pattern:
        **/WEB-INF/web.xml
        :return: String with the path to the file
        """
        globPath = os.path.join(self.workingDir, '**', 'WEB-INF', 'web.xml')
        files = glob.glob(globPath, recursive=True)

        # We should only ever find one. We're just going to choose the first if
        # Theres more than one
        try:
            return files[0]
        except IndexError as e:
            return None

    def _find_servlet_classes(self, webXmlLocation):
        """
        This method finds all the referenced classes along with the name assigned to them within a web.xml
        :param webXmlLocation: The path to the web.xml file
        :return: A list of dictionaries structured like so {'name': ..., 'class': ...}
        """
        # Parse the XML file
        self._load_xml(webXmlLocation)
        if self.rootElement is not None:
            # loop through all the servlets
            servlets = []
            if self.namespace is not None:
                searchString = ".//{{{}}}servlet".format(self.namespace)
            else:
                searchString = ".//servlet"
            for servletElement in self.rootElement.iterfind(searchString):
                servlet = {}
                for child in servletElement:
                    if self.namespace is not None:
                        classSearchString = "{{{}}}servlet-class".format(self.namespace)
                        nameSearchString = "{{{}}}servlet-name".format(self.namespace)
                        jspSearchString = "{{{}}}jsp-file".format(self.namespace)
                    else:
                        classSearchString = "servlet-class"
                        nameSearchString = "servlet-name"
                        jspSearchString = "jsp-file"

                    if str(child.tag).strip() == classSearchString:
                        servlet['class'] = str(child.text).strip()
                    elif str(child.tag).strip() == nameSearchString:
                        servlet['name'] = str(child.text).strip()
                    elif str(child.tag).strip() == jspSearchString:
                        servlet['templates'] = str(child.text).strip()

                if servlet:
                    servlets.append(servlet)
            return servlets

    def _find_path_for_servlet(self, webXmlLocation, servletName):
        """
        This method finds the uri path assigned to a servlet name
        :param webXmlLocation: The path to the web.xml file
        :param servletName: the name of the servlet
        :return: The path to a servlet or None if not found
        """
        # Parse the XML file
        self._load_xml(webXmlLocation)
        if self.namespace is not None:
            # loop through all the servlet-mappings
            if None in self.rootElement.nsmap:
                searchString = ".//{{{}}}servlet-mapping".format(self.namespace)
            else:
                searchString = ".//servlet-mapping"
            for servletElement in self.rootElement.iterfind(searchString):
                servlet = {
                    'path': set(),
                    'name': None
                }
                for child in servletElement:
                    if self.namespace is not None:
                        urlSearchString = "{{{}}}url-pattern".format(self.namespace)
                        nameSearchString = "{{{}}}servlet-name".format(self.namespace)
                    else:
                        urlSearchString = "url-pattern"
                        nameSearchString = "servlet-name"

                    if str(child.tag).strip() == urlSearchString:
                        servlet['path'].add(str(child.text).strip())
                    elif str(child.tag).strip() == nameSearchString:
                        servlet['name'] = str(child.text).strip()

                if servlet and 'name' in servlet and servlet['name'] == servletName:
                    return servlet['path']

    def _is_spring_servlet_dipatcher_or_external(self, servletClass):
        """
        This method returns true or false for whether the supplied class
        is a spring servlet or an external class
        :param servletClass: The fully qualified name for a class. Ex: 'com.indeed.security.wes.west.servlets.JS001'
        :return: Boolean of whether a class is a within the current project
        """
        # Dynamically check if the class is a subclass of DispatcherServlet
        classPath = self._find_class_file_path(servletClass)
        if classPath and os.path.isfile(classPath):
            test = codecs.open(classPath, 'r', 'utf-8', 'ignore').read()
            if 'extends DispatcherServlet' in test:
                return True
            else:
                return False
        else:
            return True

    def _find_class_file_path(self, className):
        """
        This method attempts to find the actual filepath for the class fqn
        :param className: The fully qualified name for a class. Ex: 'com.indeed.security.wes.west.servlets.JS001'
        :return: The constructed file path
        """
        try:
            codeBaseDir = self.processor.find_code_base_dir()

            classPath = os.path.join(codeBaseDir,
                                     className.replace('.', '/')) + '.java'

            if os.path.isfile(classPath):
                return classPath
            else:
                # Let's attempt to find with classLookupTable
                if className in self.processor.classLookupTable:
                    # We found the file
                    classPath = os.path.join(self.workingDir,
                                             self.processor.classLookupTable[className][2])

                    return classPath

        except TypeError:
            return None

    def _find_request_get_param(self, endpoint):
        """
        Find all of the Request.getParameter() for this endpoint. This looks
        under the whole file because it's a java servlet.
        :param endpoint: The endpoint dictionary which contains the 'filepath' key
        :return: The enriched endpoint dictionary
        """
        if endpoint['filepath'] in self.processor.javaCompilationUnits:
            compilationUnit = self.processor.javaCompilationUnits[endpoint['filepath']]
            methodInvocations = compilationUnit.filter(javalang.tree.MethodInvocation)

            for path, mi in methodInvocations:
                if mi.member == "getParameter":
                    if type(mi.arguments) is list:
                        for arg in mi.arguments:
                            if type(arg) is javalang.tree.Literal:
                                value = arg.value.strip("\"'")
                                paramDict = {
                                    'name': value,
                                    'filepath': endpoint['filepath'],
                                    'lineNumber': arg.position[0]
                                }
                                endpoint['params'].append(paramDict)
                            elif type(arg) is javalang.tree.MemberReference:
                                value = self.processor.resolve_member_reference(compilationUnit, arg.member, arg.qualifier)
                                if value:
                                    paramDict = {
                                        'name': value,
                                        'filepath': endpoint['filepath'],
                                        'lineNumber': arg.position[0]
                                    }
                                    endpoint['params'].append(paramDict)

        return endpoint

    def _find_referenced_jsps(self, endpoint):
        """
        Find all of the referenced JSPs
        :param endpoint: The endpoint dictionary which can contain an existing 'templates' key
        :return: The enriched endpoint dictionary
        """
        # look for references to JSPs from within the endpoint's scope
        templatePaths = set()

        # if jsp was found in web.xml we'll want to process that too
        if 'templates' in endpoint:
            templatePaths |= set(endpoint['templates'])

        if endpoint['filepath'] in self.processor.javaCompilationUnits:
            # look for getRequestDispatcher()
            compilationUnit = self.processor.javaCompilationUnits[endpoint['filepath']]
            methodInvocations = compilationUnit.filter(javalang.tree.MethodInvocation)
            for path, mi in methodInvocations:
                if mi.member == "getRequestDispatcher":
                    if type(mi.arguments[0]) is javalang.tree.Literal:
                        value = mi.arguments[0].value.strip("\"'")
                        if value.endswith(".jsp"):
                            templatePaths.add(value.lstrip("/"))
                    elif type(mi.arguments[0]) is javalang.tree.MemberReference:
                        value = self.processor.resolve_member_reference(path[0], mi.arguments[0].member,
                                                                        mi.arguments[0].qualifier)
                        if value:
                            if value.endswith(".jsp"):
                                templatePaths.add(value.lstrip("/"))

        # Add JSP references to endpoint
        fullTemplatePaths = []
        for path in templatePaths:
            if self.processor.webContextDir not in path:
                fullTemplatePaths.append(self.processor.webContextDir + path)
            else:
                fullTemplatePaths.append(path)
        endpoint['templates'] = set(fullTemplatePaths)

        return endpoint

    def _find_jsp_params(self, endpoint):
        """
        Find all of the referenced JSPs
        :param endpoint: The endpoint dictionary which contains a 'templates' key
        :return: The enriched endpoint dictionary
        """
        templatePaths = endpoint['templates']
        templatePaths = list(map(lambda x: x.replace(self.processor.webContextDir, ''), templatePaths))

        # Process the JSPs found
        for template in templatePaths:
            foundParams = self.processor.get_jsp_params(template)
            foundParams = list(map(lambda x: {'name': x, 'filepath': template}, foundParams))
            if foundParams:
                endpoint['params'] += foundParams

        return endpoint

    def _find_methods_for_endpoint(self, endpoint):
        """
        This method find all of the methods that can be used with the endpoint
        :param endpoint: The endpoint dictionary which contains a 'filepath' key
        :return: The enriched endpoint dictionary
        """
        if endpoint['filepath'] in self.processor.javaCompilationUnits:
            compilationUnit = self.processor.javaCompilationUnits[endpoint['filepath']]
            methodDeclarations = compilationUnit.filter(javalang.tree.MethodDeclaration)

            for path, md in methodDeclarations:
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
            self.elementTree = ET.parse(filepath, parser)
            self.rootElement = self.elementTree.getroot()
            if None in self.rootElement.nsmap:
                self.namespace = self.rootElement.nsmap[None]
            else:
                self.namespace = None
        except Exception as e:
            print("There was a problem parsing the xml", e)
            self.elementTree = None
            self.rootElement = None

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
        cleanEndpoints = []
        for ep in endpoints:
            cleanEndpoint = {}
            for k, v in ep.items():
                if k == 'endpoints':
                    cleaned_eps = set()
                    for ep in v:
                        if '*' in ep or ('{' in ep and '}' in ep):
                            cleaned_eps.add(self._convert_endpoint_to_python_regex(ep))
                        else:
                            cleaned_eps.add(ep)
                    v = cleaned_eps
                if k in ['endpoints', 'params', 'methods', 'filepath', 'templates', 'lineNumber']:
                    cleanEndpoint[k] = v
            if 'endpoints' in cleanEndpoint:
                cleanEndpoints.append(cleanEndpoint)
        return cleanEndpoints
