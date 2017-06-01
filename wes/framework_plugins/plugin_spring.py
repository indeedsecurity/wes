import glob
import javalang
import codecs
import re
# Add to wes to the sys path
import sys
import os
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
        self.elementTree = None
        self.endpoints = []
        self.processor = processors['java']

    def _load_xml(self, filepath):  # pragma: no cover
        """
        Used to load the web.xml file into the object for the identify method
        :param filepath: The path to the web.xml
        :return: None
        """
        try:
            self.elementTree = ET.parse(filepath)
            self.rootElement = self.elementTree.getroot()
            if None in self.rootElement.nsmap:
                self.namespace = self.rootElement.nsmap[None]
            else:
                self.namespace = None
        except Exception as e:
            print("There was a problem parsing the xml", e)
            self.elementTree = None
            self.rootElement = None

    def identify(self):
        """
        Used to detect whether the project uses Spring. It does this by loading
        the WEB-INF/web.xml file and check if there's a element that references
        the spring DispatcherServlet.
        :return: Boolean of whether it's a spring project
        """
        globPath = os.path.join(self.workingDir, '**', 'WEB-INF', 'web.xml')
        files = list(glob.glob(globPath, recursive=True))

        # Loop through files looking for spring declaration
        for f in files:
            self._load_xml(f)
            if self.rootElement is not None:
                if self.namespace is not None:
                    searchString = ".//{{{}}}servlet-class".format(self.namespace)
                else:
                    searchString = ".//servlet-class"
                for servlet in self.rootElement.iterfind(searchString):
                    if 'org.springframework.web.servlet.DispatcherServlet' in servlet.text:
                        return True
                    # Dynamically check if the class is a subclass of
                    # DispatcherServlet
                    codeBaseDir = self.processor.find_code_base_dir(f)

                    classPath = os.path.join(codeBaseDir,
                                             servlet.text.replace('.', '/')) + '.java'

                    if os.path.isfile(classPath):  # pragma: no cover
                        fileContents = codecs.open(classPath, 'r', 'utf-8', 'ignore').read()
                        if 'extends DispatcherServlet' in fileContents:
                            return True
                        elif 'extends org.springframework.web.servlet.DispatcherServlet':
                            return True

        # If we couldn't construct the base code dir correctly let's just search
        # the classLookupTable and see if it extends the DispatcherServlet
        for f in files:
            self._load_xml(f)
            if self.rootElement is not None:
                if self.namespace is not None:
                    searchString = ".//{{{}}}servlet-class".format(self.namespace)
                else:
                    searchString = ".//servlet-class"
                for servlet in self.rootElement.iterfind(searchString):
                    if servlet.text in self.processor.classLookupTable:
                        # We found the file lets see if it extends DispatcherServlet
                        classPath = os.path.join(self.workingDir,
                                                 self.processor.classLookupTable[servlet.text][2])

                        fileContents = codecs.open(classPath, 'r', 'utf-8', 'ignore').read()
                        if 'extends DispatcherServlet' in fileContents:
                            return True
                        elif 'extends org.springframework.web.servlet.DispatcherServlet':
                            return True

        # Let's see if the project is using the new method of implementing
        # spring. The new method deosn't require the web.xml file and just
        # implements WebApplicationInitializer or
        # extends AbstractAnnotationConfigDispatcherServletInitializer
        globPath = os.path.join(self.workingDir, '**', '*.java')
        files = glob.glob(globPath, recursive=True)

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
        for f in self.processor.javaCompilationUnits:
            self._find_request_mappings(f)

        # Loop through the list of endpoints and find the params for each based
        # on the path where the ReqMap was found.
        for i in range(len(self.endpoints)):
            self.endpoints[i] = self._find_parameters(self.endpoints[i])

        # pprint(self.endpoints)
        return self._clean_endpoints(self.endpoints)

    def _find_request_mappings(self, filepath):
        """
        This is a finds all @RequestMapping annotations in the code and then
        creates Endpoint dictionaries for each.
        :param filepath: The filepath to the script file
        :return: None
        """
        tree = self.processor.javaCompilationUnits[filepath]

        # Use the Javalang filter method to find all annotations in that
        # specific file and loop through them checking if they're ReqMaps
        for path, anno in tree.filter(javalang.tree.Annotation):
            if anno.name == "RequestMapping":
                # Checks if the ReqMap is on a class
                if self.processor.check_annotation_type(path) == 'class':
                    continue  # the ReqMap is on a class we'll skip it for now

                # Check if the parent class is an abstract class
                if 'abstract' in self._get_parent_class(path).modifiers:
                    # TODO: Handle abstract classes
                    continue  # ignoring abstract classes for now

                if not self._has_controller_anno(path):
                    # The parent class doesn't have a controller Anno skip for now
                    continue

                # Parse out ReqMap parameters
                ep = self._parse_req_map_annotation(anno, tree)

                ep['lineNumber'] = self.processor.get_parent_declaration(path).position[0]

                # Attempt to parse out parent class ReqMap anno params
                parentReqMap = self._get_parent_request_mapping(path)

                # If there's a parent ReqMap combine the child with the parent
                if parentReqMap is not None:
                    ep = self._combine_endpoint_sets(parentReqMap, ep)

                # Construct path to the Method Declaration
                # Pop last element off path until type is MethodDeclaration
                javaPath = list(path)
                while type(javaPath[-1]) is not javalang.tree.MethodDeclaration:
                    javaPath.pop()
                javaPath = tuple(javaPath)

                if ep and ('endpoints' in ep) and ep['endpoints']:
                    self.endpoints.append({
                        'javaPath': javaPath,
                        'filepath': filepath,
                        **ep
                    })

    def _has_controller_anno(self, path):
        """
        This method takes a path and attempts to find a @Controller annotation
        on the class level.
        :param path: The javalang path to the element
        :return: Boolean (True if there's a @Controller on the class)
        """
        parentClass = self._get_parent_class(path)

        # We found the parent class now let's loop through it's
        # annotations if it has any
        if hasattr(parentClass, 'annotations'):
            for anno in parentClass.annotations:
                # Check if the parent class is a controller
                if anno.name == "Controller":
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
        parentClass = self._get_parent_class(path)
        tree = path[0]

        # We found the parent class now let's loop through it's
        # annotations if it has any
        if hasattr(parentClass, 'annotations'):
            for anno in parentClass.annotations:
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
        endpointDict = {
            'endpoints': set(),
            'methods': set(),
            'params': [],
            'headers': set()
        }

        # Process the parameter passed into the ReqMap into a Dictionary
        parameters = self._parse_anno_args_to_dict(params)

        # Resolve the values within the dictionary to python values
        resolvedParameters = self._resolve_values_in_dict(parameters, tree)

        # We've resolved the values now let's make an endpoint for it
        if 'value' in resolvedParameters:
            if type(resolvedParameters['value']) is list:
                endpointDict['endpoints'] = endpointDict['endpoints'] | set(resolvedParameters['value'])
            else:
                endpointDict['endpoints'].add(resolvedParameters['value'])
        if 'method' in resolvedParameters:
            if type(resolvedParameters['method']) is list:
                endpointDict['methods'] = endpointDict['methods'] | set(resolvedParameters['method'])
            else:
                endpointDict['methods'].add(resolvedParameters['method'])
        if 'params' in resolvedParameters:
            if type(resolvedParameters['params']) is list:
                endpointDict['params'] += resolvedParameters['params']
            else:
                endpointDict['params'].append(resolvedParameters['params'])
        if 'headers' in resolvedParameters:
            if type(resolvedParameters['headers']) is list:
                endpointDict['headers'] = endpointDict['headers'] | set(resolvedParameters['headers'])
            else:
                endpointDict['headers'].add(resolvedParameters['headers'].replace('=', ': '))

        return endpointDict

    def _parse_anno_args_to_dict(self, params):
        """
        This method simply takes the arguments passed into a ReqMap and returns
        them within a Python Dictionary.
        :param params: Then Annotation.element object with all the arguments
        passed into the ReqMap
        :return: Python Dictionary
        """
        paramDict = {}

        # Make params into list if it isn't a list already
        if type(params) is not list:
            params = [params]

        # loop through the list of params
        for param in params:
            if type(param) is javalang.tree.ElementValuePair:
                if param.name == 'path':
                    paramDict['value'] = param.value
                else:
                    paramDict[param.name] = param.value
            else:
                paramDict['value'] = param

        return paramDict

    def _resolve_values_in_dict(self, myDict, tree):
        """
        This method takes a dictionary with Javalang object within the values
        and attempts to resolve the values for each key.
        :param myDict: The dictionary with javalang objects in the values
        :param tree: The javalang tree
        :return: The resolved python dictionary
        """
        resolvedDict = {}

        # Loop through the dictionary resolving the values
        for originalKey, originalValue in myDict.items():
            resolvedValue = None  # Placeholder for the final value

            # If the Dict value is a ElementArrayValue convert to list
            # Make all other lists with a single element
            if type(originalValue) is javalang.tree.ElementArrayValue:
                originalValue = originalValue.values
            elif type(originalValue) is not list:
                originalValue = [originalValue]

            # loop through the list we just created
            for val in originalValue:
                tempValue = None  # Placeholder for when there are multiple elements in the list

                # Resolve if type is javalang.tree.Literal
                if type(val) is javalang.tree.Literal:
                    tempValue = val.value.strip('" \'')

                # Resolve if type is javalang.tree.MemberReference
                elif type(val) is javalang.tree.MemberReference:
                    if originalKey != 'method':
                        tempValue = self.processor.resolve_member_reference(tree, val.member, val.qualifier)
                    else:
                        # The key is 'method' so we'll process those MemberReferences differently
                        if 'GET' in val.children:
                            tempValue = "GET"
                        elif 'POST' in val.children:
                            tempValue = "POST"
                        elif 'DELETE' in val.children:
                            tempValue = "DELETE"
                        elif 'HEAD' in val.children:
                            tempValue = "HEAD"
                        elif 'OPTIONS' in val.children:
                            tempValue = "OPTIONS"
                        elif 'PUT' in val.children:
                            tempValue = "PUT"
                        elif 'TRACE' in val.children:
                            tempValue = "TRACE"

                # Resolve if type is javalang.tree.BinaryOperation
                elif type(val) is javalang.tree.BinaryOperation:
                    pathToElement = self.processor.find_path_to_element(tree, val)
                    if type(pathToElement) is list:  # pragma: no cover
                        try:
                            pathToElement = list(filter(lambda x: 'Annotation' in str(x), pathToElement))[0]
                        except:
                            pathToElement = pathToElement[0]
                    tempValue = self.processor._resolve_binary_operation((pathToElement, val))

                # Copy tempValue over to value variable and make list if there's
                # already a value there
                if tempValue is not None:
                    if resolvedValue is None:
                        resolvedValue = tempValue
                    elif type(resolvedValue) is list:
                        resolvedValue.append(tempValue)
                    else:
                        resolvedValue = [resolvedValue, tempValue]

            if resolvedValue is not None:
                resolvedDict[originalKey] = resolvedValue

        return resolvedDict

    def _combine_endpoint_sets(self, parentEp, childEp):
        """
        This method is used to combine a parent ReqMap with a child
        ReqMap.
        :param parentEp: An endpoint dictionary representing a parent ReqMap
        :param childEp: An endpoint dictionary representing a child ReqMap
        :return: A combined endpoint dictionary
        """
        combinedEp = {
            'endpoints': set(),
            'methods': set(),
            'params': [],
            'headers': set(),
            'lineNumber': None
        }
        if 'endpoints' in parentEp:
            for pep in parentEp['endpoints']:
                if childEp and 'endpoints' in childEp and len(childEp['endpoints']) > 0:

                    for cep in childEp['endpoints']:
                        if cep and pep:
                            combinedEp['endpoints'].add(pep.rstrip('/') + '/' + cep.lstrip('/'))
                else:
                    combinedEp['endpoints'].add(pep)
        else:
            combinedEp['endpoints'] |= childEp['endpoints']

        if childEp and 'methods' in childEp:
            combinedEp['methods'] |= childEp['methods']
        if childEp and 'params' in childEp:
            combinedEp['params'] += childEp['params']
        if parentEp and 'params' in parentEp:
            combinedEp['params'] += parentEp['params']
        if parentEp and 'headers' in parentEp:
            combinedEp['headers'] |= parentEp['headers']

        if 'lineNumber' in childEp:
            combinedEp['lineNumber'] = childEp['lineNumber']

        return combinedEp

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
        tree = self.processor.get_compilation_unit(endpoint['javaPath'])
        method = self.processor.get_parent_declaration(endpoint['javaPath'])

        # Check parameters of method for @RequestParam
        for param in method.parameters:
            if hasattr(param, 'annotations'):
                for anno in param.annotations:
                    if anno.name == 'RequestParam':
                        # Found a RequestParam now let's parse it
                        parameter = self._parse_req_param_anno(anno, tree)
                        if parameter is None or parameter == "":
                            parameter = param.name

                        paramDict = {
                            'name': parameter,
                            'filepath': endpoint['filepath'],
                            'lineNumber': anno.position[0]
                        }

                        endpoint['params'].append(paramDict)

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
            resolvedParameters = self._resolve_values_in_dict(parameters, tree)

            if 'value' in resolvedParameters:
                return resolvedParameters['value']

    def _find_request_get_param(self, endpoint):
        """
        Find all of the Request.getParameter() for this endpoint
        :param endpoint: An endpoint dictionary
        :return: The enriched endpoint dictionary
        """
        tree = self.processor.get_compilation_unit(endpoint['javaPath'])
        searchNode = self.processor.get_parent_declaration(endpoint['javaPath'])

        # Find all method invocation within this method
        methodInvocations = self.processor.filter_on_path(searchNode, javalang.tree.MethodInvocation, tree)

        for path, mi in methodInvocations:
            if mi.member == "getParameter":
                if type(mi.arguments) is list:
                    resolvedParameters = self._resolve_values_in_dict({'params': mi.arguments}, tree)
                    if 'params' in resolvedParameters and resolvedParameters['params']:
                        endpoint['params'].append({
                            'name': resolvedParameters['params'],
                            'filepath': endpoint['filepath'],
                            'lineNumber': mi.position[0]
                        })

        return endpoint

    def _find_referenced_jsps(self, endpoint):
        """
        Find all of the param.* within the JSP for this endpoint
        :param endpoint:
        :return:
        """
        # look for references to JSPs from within the endpoint's scope
        templatePaths = set()

        tree = self.processor.get_compilation_unit(endpoint['javaPath'])
        searchNode = self.processor.get_parent_declaration(endpoint['javaPath'])

        # look for return new ModelAndView()
        classCreators = self.processor.filter_on_path(searchNode, javalang.tree.ClassCreator, tree)
        for path, cc in classCreators:
            if cc.type.name == "ModelAndView" and hasattr(cc, 'arguments') and len(cc.arguments) > 0:
                resolvedValues = self._resolve_values_in_dict({'jsp': cc.arguments[0]}, tree)
                if 'jsp' in resolvedValues and resolvedValues['jsp'] and resolvedValues['jsp'].endswith(".jsp"):
                    templatePaths.add(resolvedValues['jsp'].lstrip('/'))

        # look for return [String]
        returnStatements = self.processor.filter_on_path(searchNode, javalang.tree.ReturnStatement, tree)
        for path, rs in returnStatements:
            resolvedValues = self._resolve_values_in_dict({'jsp': rs.expression}, tree)
            if 'jsp' in resolvedValues and resolvedValues['jsp'] and resolvedValues['jsp'].endswith(".jsp"):

                if ":" in resolvedValues['jsp']:
                    resolvedValues['jsp'] = resolvedValues['jsp'].split(":")[1]

                templatePaths.add(resolvedValues['jsp'].lstrip('/'))


        # look for getRequestDispatcher()
        methodInvocations = self.processor.filter_on_path(searchNode, javalang.tree.MethodInvocation, tree)
        for path, mi in methodInvocations:
            if mi.member == "getRequestDispatcher":
                resolvedValues = self._resolve_values_in_dict({'jsp': mi.arguments[0]}, tree)
                if 'jsp' in resolvedValues and resolvedValues['jsp'] and resolvedValues['jsp'].endswith(".jsp"):
                    templatePaths.add(resolvedValues['jsp'].lstrip('/'))

        # Add JSP references to endpoint
        fullTemplatePaths = []
        for path in templatePaths:
            fullTemplatePaths.append(self.processor.webContextDir + path)
        endpoint['templates'] = set(fullTemplatePaths)

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
            relativePath = template.split(self.processor.webContextDir)[1]
            foundParams = self.processor.get_jsp_params(relativePath)
            foundParams = list(map(lambda x: {'name': x, 'filepath': template}, foundParams))
            if foundParams:
                endpoint['params'] += foundParams

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
        cleanEndpoints = []
        for ep in endpoints:
            cleanEndpoint = {}
            for k, v in ep.items():
                if k == 'endpoints':
                    cleaned_eps = set()
                    for endpoint in v:
                        if '*' in endpoint or ('{' in endpoint and '}' in endpoint):
                            cleaned_eps.add(self._convert_endpoint_to_python_regex(endpoint))
                        else:
                            cleaned_eps.add(endpoint)
                    v = cleaned_eps
                if k in ['endpoints', 'params', 'methods', 'filepath', 'templates', 'headers', 'lineNumber']:
                    cleanEndpoint[k] = v
            if 'endpoints' in cleanEndpoint:
                cleanEndpoints.append(cleanEndpoint)
        return cleanEndpoints
