# Parent class for the framework modules
import javalang
import glob
import os
import codecs
import re
from typed_ast import ast27, ast3, conversions
import _ast3
import pickle

JAVA_PRIMITIVES = ["boolean", "byte", "char", "double", "int", "float", "long", "short"]

JAVA_DOT_LANG_IMPORTS = [
    "java.lang.Boolean", "java.lang.Byte", "java.lang.Character", "java.lang.Class", "java.lang.ClassLoader",
    "java.lang.ClassValue", "java.lang.Compiler", "java.lang.Double", "java.lang.Enum", "java.lang.Float",
    "java.lang.InheritableThreadLocal", "java.lang.Integer", "java.lang.Long", "java.lang.Math", "java.lang.Number",
    "java.lang.Object", "java.lang.Package", "java.lang.Process", "java.lang.ProcessBuilder", "java.lang.Runtime",
    "java.lang.RuntimePermission", "java.lang.SecurityManager", "java.lang.Short", "java.lang.StackTraceElement",
    "java.lang.StrictMath", "java.lang.String", "java.lang.StringBuffer", "java.lang.StringBuilder", "java.lang.System",
    "java.lang.Thread", "java.lang.ThreadGroup", "java.lang.ThreadLocal", "java.lang.Throwable", "java.lang.Void"
]


class Framework:
    """
    The Parent class for all of the framework modules.
    """
    def __init__(self):  # pragma: no cover
        pass


class JavaProcessor:
    """
    This class is used as a wrapper around the javalang module. It does some
    preprocessing of the project code to allow for mapping of MemberRef
    objects.
    """
    def __init__(self, workingDir):
        self.workingDir = workingDir
        self.webContextDir = self._find_java_web_context()
        self.javaCompilationUnits = {}  # Format: {'path/file.java': CompilationUnit}
        self.variableLookupTable = {}  # Format: {'VarFQN': value}
        self.classLookupTable = {}  # Format: {'pkg.class': (path, node, filepath)}
        # This table will only contain the MIs that we could resolve the FQNs for. This is something to keep in mind
        # when using the table because in it's current implementation it can't resolve trailed invocations or where it
        # can't find where a qualifier is defined.
        self.methodInvocationLookupTable = {}  # Format: {'MethodSig': [(path, MethodInvoation),...]}

    def load_project(self):
        """
        Loads the project from the current workingDir that was passed in at instantiation.
        This method loads all of the *.java files into ASTs and adds them to the self.javaCompilationUnits dict.
        It also then preprocesses the ASTs with _preprocess_java_literals() and _preprocess_java_variables()
        which build out the variableLookupTable dict.
        :return: None
        """
        # Find all of the java files
        globPath = os.path.join(self.workingDir, '**', '*.java')
        projectFiles = glob.glob(globPath, recursive=True)
        projectFiles = list(filter(lambda x: os.path.isfile(x), projectFiles))
        # Exclude Tests
        projectFiles = list(filter(lambda x: os.path.join(self.workingDir, 'test') not in x, projectFiles))

        # Loop through the files looking for endpoints
        for f in projectFiles:
            # print("FILE: {}".format(f))
            with codecs.open(f, 'r', 'utf-8', 'ignore') as fh:
                code = fh.read()
                # Used javalang library to parse the code for easier analysis
                try:
                    tree = javalang.parse.parse(code)
                    self.javaCompilationUnits[self.strip_work_dir(f)] = tree
                except javalang.parser.JavaSyntaxError as e:  # pragma: no cover
                    print("There was an error parsing this file with javalang: {}".format(self.strip_work_dir(f)), e)

        # Process the Literals and variables
        # These two methods are broken up so that we can gather all the Literals first then attempt to resolve some
        # MemberReferences from the Literals gathered with the first method
        for filepath, tree in self.javaCompilationUnits.items():
            # Resolve Literals
            self.variableLookupTable.update(self._preprocess_java_literals(tree))
        for filepath, tree in self.javaCompilationUnits.items():
            # Resolve MemberReferences
            self.variableLookupTable.update(self._preprocess_java_variables(tree))

            # Construct the class lookup table
            self.classLookupTable.update(self._preprocess_java_classes(tree, filepath))

            # Construct a MethodInvocation Lookup take so we can quickly recurse
            # through all uses of a MethodDeclaration later on
            mis = self._preprocess_java_method_invocations(tree)
            for k, v in mis.items():
                if k in self.methodInvocationLookupTable:
                    self.methodInvocationLookupTable[k] += v
                else:
                    self.methodInvocationLookupTable[k] = v

        print()

    def strip_work_dir(self, path):
        """
        Used to remove the workingDir from the path you specify
        :param path: The path you would like to remove self.workingDir from
        :return: The path minus self.workingDir and the leading slash
        """
        return path.split(self.workingDir, 1)[1][1:]

    def resolve_node_fqn(self, path, member, qualifier=None):
        """
        This method is used to create the fully qualified name for a variable
        :param path: This the path to the variable that's returned as the first element in the tuple from javalang.walk_tree
        :param member: This is the name of the variable
        :param qualifier: This is the qualifier to the variable if there is one. (Optional)
        :return: Returns the FQN of the member reference passed in ex. com.indeed.dradis.common.webapp.controller.Headers.RPC_REQ_HEADER
        """
        compilationUnit = self.get_compilation_unit(path)

        # Find the package
        for javaImport in compilationUnit.imports:
            importPkg = javaImport.path.rsplit('.', 1)

            if qualifier == "" or qualifier is None:
                if importPkg[1] == member:
                    return javaImport.path
            else:
                if importPkg[1] == qualifier:
                    return ".".join([javaImport.path, member])

        # Var might be declared locally check that too. We'll fall back to that.
        classes = list(filter(lambda x: type(x) is javalang.tree.ClassDeclaration, path))
        classNames = list(map(lambda x: x.name, classes))
        qualifier = ".".join(classNames) if len(classes) > 0 else None

        if qualifier is not None:
            if compilationUnit.package is None:
                return ".".join([qualifier, member])
            else:
                return ".".join([compilationUnit.package.name, qualifier, member])
        else:
            if compilationUnit.package is None:
                return member
            else:
                return ".".join([compilationUnit.package.name, member])

    def _resolve_binary_operation(self, var):
        """
        This method is used to resolve the value of a binary operators ex. "test" + "result"
        :param var: This is a tuple (path, node) that's returned by the javalang filter with the binary operation node
        :return: The result of the binary operation if we can solve it or it will return None
        """
        element = var[1]
        if hasattr(element, 'initializer'):
            operandl = element.initializer.operandl
            operandr = element.initializer.operandr
            operator = element.initializer.operator
        else:
            operandl = element.operandl
            operandr = element.operandr
            operator = element.operator

        # Resolve operations with a MemberReference
        if (type(operandl) in [javalang.tree.MemberReference, javalang.tree.Literal] and
            type(operandr) in [javalang.tree.MemberReference, javalang.tree.Literal]):
            left = None
            right = None

            # Let's get the value of each of the operands
            if type(operandl) is javalang.tree.Literal:
                # The left operand is a literal
                left = operandl.value.strip('"\'')
            elif type(operandl) is javalang.tree.MemberReference:
                # The left operand is a MemberReference
                fqn = self.resolve_node_fqn(var[0], operandl.member, operandl.qualifier)
                if fqn in self.variableLookupTable:
                    left = self.variableLookupTable[fqn]

            if type(operandr) is javalang.tree.Literal:
                # The right operand is a literal
                right = operandr.value.strip('"\'')
            elif type(operandr) is javalang.tree.MemberReference:
                # The right operand is a MemberReference
                fqn = self.resolve_node_fqn(var[0], operandr.member, operandr.qualifier)
                if fqn in self.variableLookupTable:
                    right = self.variableLookupTable[fqn]

            if left and right:
                # TODO: Add support for additional operators
                if operator is "+":
                    return left.strip('"\'') + right.strip('"\'')

            # We're only accounting for string concatenation for now
            # print("I got the following type of operation: {} {} {}".format(type(operandl), operator, type(operandr)))

    def _preprocess_java_literals(self, tree):
        """
        Finds all the Literals within the source code that will allow for us to build out our variableLookupTable dict
        that will allow for resolving of MemberReferences at a later point
        :param tree: The root compilation unit/tree of the source file
        :return: A dictionary of the values
        """
        results = {}
        # Filter on the tree looking for VariableDeclarators
        variables = tree.filter(javalang.tree.VariableDeclarator)

        for var in variables:
            element = var[1]

            # Process Literals
            if type(element.initializer) is javalang.tree.Literal:
                value = element.initializer.value

                if value[0] in ['"', "'"] and value[-1] in ['"', "'"] and len(value) > 2:
                    varFQN = self.resolve_node_fqn(var[0], element.name)
                    results[varFQN] = element.initializer.value.strip('"\'')

        return results

    def _preprocess_java_variables(self, tree):
        """
        Finds all the variables within the source code that will allow for us to build out our variableLookupTable dict
        that will allow for resolving of MemberReferences at a later point. This method attempts to resolve the simple
        MemberReferences and BinaryOperations and adds them to the variableLookupTable
        :param tree: The root compilation unit/tree of the source file
        :return: A dictionary of the values
        """
        results = {}
        variables = tree.filter(javalang.tree.VariableDeclarator)

        for var in variables:
            element = var[1]

            # Process MemberReferences
            if type(element.initializer) is javalang.tree.MemberReference:
                memberFQN = self.resolve_node_fqn(var[0], var[1].initializer.member, var[1].initializer.qualifier)
                if memberFQN in self.variableLookupTable:
                    varFQN = self.resolve_node_fqn(var[0], element.name)
                    results[varFQN] = self.variableLookupTable[memberFQN]

            # Process BinaryOperations
            elif type(element.initializer) is javalang.tree.BinaryOperation:
                value = self._resolve_binary_operation(var)

                # Make sure the value returned isn't None
                if value:
                    varFQN = self.resolve_node_fqn(var[0], element.name)
                    results[varFQN] = value

        return results

    def _preprocess_java_method_invocations(self, tree):
        """
        This method pulls all of the methodInvocations out of a tree. It then
        computes a signature for each instance and adds them to a corresponding
        key in the dictionary
        :param tree:
        :return:
        """
        methodInvocations = {}

        for path, mi in tree.filter(javalang.tree.MethodInvocation):
            # So we found some method invocations, now let's construct a signature
            # for it and add it to the dictionary
            fqn = self.resolve_method_fqn(mi, path)
            if fqn:
                fqn = "{}({})".format(fqn, len(mi.arguments))
                if fqn in methodInvocations:
                    methodInvocations[fqn] += [(path, mi)]
                else:
                    methodInvocations[fqn] = [(path, mi)]
        return methodInvocations

    def resolve_method_fqn(self, node, path):
        """
        This method reads a node and path and if the node is a methodInvocation it attempts to resolve the
        FQN for the method you are running.
        :param node: Should be a javalang.tree.MethodInvocation
        :param path: This is the path to the node
        :return: A FQN string
        """
        if type(node) is not javalang.tree.MethodInvocation:  # pragma: no cover
            return None

        compilationUnit = self.get_compilation_unit(path)
        imports = self.get_imports(path)
        varDecl = self.get_variable_declaration(node, path)

        if varDecl:
            if type(varDecl) is javalang.tree.Import:
                fqn = ".".join([varDecl.path, node.member])
            elif type(varDecl) is javalang.tree.MethodDeclaration:
                # The method invocation was of a method within the same class
                if compilationUnit.package is not None:
                    fqn = ".".join([compilationUnit.package.name, self.get_class_declaration(path).name, varDecl.name])
                else:
                    fqn = ".".join([self.get_class_declaration(path).name, varDecl.name])
            else:
                fqn = self.resolve_type(varDecl.type.name, compilationUnit.package, imports)
                fqn = ".".join([fqn, node.member])
        else:
            # check if it's in the
            return None
        return fqn

    def _preprocess_java_classes(self, tree, filepath):
        """
        This method pulls all of the ClassDeclarations out of a tree. It then
        computes a signature for each instance and adds them to a corresponding
        key in the dictionary
        :param tree:
        :return:
        """
        classes = {}

        for path, cd in tree.filter(javalang.tree.ClassDeclaration):
            classesInPath = list(filter(lambda x: type(x) is javalang.tree.ClassDeclaration, path))
            if classesInPath:
                if tree.package is not None:
                    fqn = ".".join([tree.package.name] + list(map(lambda x: x.name, classesInPath)) + [cd.name])
                else:
                    fqn = ".".join(list(map(lambda x: x.name, classesInPath)) + [cd.name])
            else:
                if tree.package is not None:
                    fqn = ".".join([tree.package.name, cd.name])
                else:
                    fqn = cd.name
            classes[fqn] = (path, cd, filepath)

        return classes

    def find_path_to_element(self, tree, node):
        """
        This method uses pickle to compare javalang objects and find the path
        to a node within the tree supplied. If it matches multiple which is very rare
        it will return a list of paths
        :param tree: The Root compilationUnit you would like to search
        :param node: The node you would like to search for
        :return: A javalang path or list of javalang paths
        """
        nodePickle = pickle.dumps(node)
        paths = []

        for path, node in tree.filter(type(node)):
            if pickle.dumps(node) == nodePickle:
                paths.append(path)

        if not paths:
            return None

        return paths[0] if len(paths) == 1 else paths

    def filter_on_path(self, searchNode, filterType, tree=None):
        """
        This method is like the javalang filter method but it allows you to specify a path to search under. To do this
        we use javalang's walk and then check the type of the nodes it encounters.
        :param searchNode: The path you would like to search under, This is the path that would be return within the
            tuple from the javalang filter method if you
        :param filterType: The javalang type you would like to filter on
        :param tree: The javalang compilationUnit, this should be provided if
            you want absolute paths to the node
        :return: List of tuples (path, node) of the filtered results
        """
        if type(searchNode) is list:
            raise AttributeError("searchNode shouldn't be a list. It should be a javalang node.")

        basePath = tuple()
        if tree:
            basePath = self.find_path_to_element(tree, searchNode)
            if basePath is None:
                raise LookupError("Error: Couldn't find node within tree, chances are we were given the incorrect tree.")
            basePath = tuple(basePath[:-1])  # remove last element which is the node

        filteredResults = []

        # walk down the scope and check type of all the nodes
        for path, node in searchNode:
            if type(node) is filterType:
                filteredResults.append((basePath + path, node))

        return filteredResults

    def get_jsp_params(self, jspPath):
        """
        Process a JSP to find all the params within it.
        :param jspPath: The path to a jsp, If given with a leading "/" the path is considered absolute. If it doesn't
            it's considered a relative path under the webContextDir
        :return: List of Params
        """
        # Remove slash if it's the first character
        if jspPath[0] != "/":
            # It's a relative path
            jspPath = os.path.join(self.workingDir, self.webContextDir, jspPath)
        elif jspPath.startswith(self.workingDir):
            # looks like it's a absolute path
            pass
        else:
            # looks they they might have added a leading "/" to a relative path, let's strip that.
            jspPath = jspPath.lstrip("/")
            jspPath = os.path.join(self.workingDir, self.webContextDir, jspPath)

        # We've constructed the filepath let's now open it and search for params within the JSP
        try:
            with codecs.open(jspPath, 'r', 'utf-8', 'ignore') as fh:
                jsp = fh.read()

            pattern = re.compile(r'param\.(\w+)')

            matches = pattern.findall(jsp)

            return matches

        except FileNotFoundError as e:
            print("Found a incorrectly referenced JSP", e)
            return []

    def resolve_member_reference(self, tree, member, qualifier=None):
        """
        This is a wrapper method around the variableLookupTable. It allows you to quickly find the value of a
        MemberReference.
        :param tree: The root compilation unit/tree of the source file
        :param member: This is the name of the variable
        :param qualifier: This is the qualifier to the variable if there is one. (Optional)
        :return: The value if we found it or None if we couldn't
        """
        # Search imports to see if this MemberReference was imported
        possiblePackageName = qualifier or member

        # Search imports for possiblePackageName
        for javaImport in tree.imports:
            if javaImport.path.rsplit('.', 1)[1] == possiblePackageName:
                # We found that it is an import
                varPath = "{}.{}".format(javaImport.path, member) if qualifier else javaImport.path  # Check if we found the qualifier or member in the imports
                if varPath in self.variableLookupTable:
                    return self.variableLookupTable[varPath]

        # Didn't find it in the imports let's see if it's a local MemberReference
        className = list(filter(lambda x: type(x) is javalang.tree.ClassDeclaration, tree.types))[0].name

        if tree.package is not None:
            varPath = ".".join([tree.package.name, className, member])
        else:
            varPath = ".".join([className, member])
        if varPath in self.variableLookupTable:
            return self.variableLookupTable[varPath]

        return None  # Couldn't find MemberReference value

    def _find_java_web_context(self):
        """
        This method is used to attempt to find the Java web context directory. It attempts to find a path that contains
        the WEB-INF directory. If that isn't found it defaults to the web dir at the root of the git repo.
        :return: The relative path to the web context directory
        """
        # Grab all file under the workingDir/gitRepo so we can search for a folder name
        globPath = os.path.join(self.workingDir, '**')
        results = glob.glob(globPath, recursive=True)
        webContextDir = None

        # loop through all the files and find a path that contains 'WEB-INF'
        for r in results:
            if '/WEB-INF/' in r:
                webContextDir = r
                break

        # If we can't find a directory with 'WEB-INF' then we default to "web/"
        if not webContextDir:
            return "web/"

        # Make the path a relative path to workingDir and return
        return webContextDir.split('WEB-INF')[0].replace(self.workingDir, '').lstrip('/')

    def resolve_full_type_path(self, name, packageDecl, imports):
        """
        This method returns the FQN to a java variable type. For example it
        would return a sting like "javax.servlet.http.HttpServletRequest"
        :param name: This is the name of the variable type ex. HttpServletRequest
        :param packageDecl: The package name javalang node for the project
        :param imports: The import for the current file from cu.imports
        :return:
        """
        parent = name.split(".")[0]
        # Check imports
        for i in imports:
            if i.path.endswith(parent):
                fqn = i.path.find(parent)
                fqn = i.path[:fqn] + name
                return fqn
        # Check java.lang
        if "java.lang." + parent in JAVA_DOT_LANG_IMPORTS:
            return ".".join(["java.lang", name])
        # Check primitives
        if name in JAVA_PRIMITIVES:
            return name
        # Check package
        if ".".join([packageDecl.name, parent]) in self.classLookupTable:
            return ".".join([packageDecl.name, name])
        # Assume it is fqn
        return name

    def get_compilation_unit(self, path):
        """
        This returns the compilation unit from a javalang path
        :param path: This the path to the variable that's returned as the first element in the tuple from javalang.walk_tree
        :return: A javalang.tree.CompilationUnit or None if not found
        """
        # First compilation unit
        for node in path:
            if type(node) is javalang.tree.CompilationUnit:
                return node
        return None

    def get_class_declaration(self, path):
        """
        This will return the parent class of a node when you pass in the path
        to the node
        :param path: This the path to the variable that's returned as the first element in the tuple from javalang.walk_tree
        :return: A javalang.tree.ClassDeclaration node or None if not found
        """
        # First method declaration
        for node in reversed(path):
            if type(node) is javalang.tree.ClassDeclaration:
                return node
        return None

    def get_parent_declaration(self, path):
        """
        This will return the parent method of a node when you pass in the path
        to the node
        :param path: This the path to the variable that's returned as the first element in the tuple from javalang.walk_tree
        :return: A javalang.tree.MethodDeclaration or javalang.tree.ConstructorDeclaration or none if not found
        """
        # First method or constructor declaration
        for node in reversed(path):
            if type(node) in [javalang.tree.MethodDeclaration,
                              javalang.tree.ConstructorDeclaration]:
                return node
        return None

    def get_imports(self, path=None, compilationUnit=None):
        """
        This method simply pulls out the compilationUnit from a path or takes in a compilationUnit and then pulls out
        the list of imports from it.
        :param path: The path to a node which contains a CompilationUnit within the tuple of the first element
        :param compilationUnit: A javalang.tree.CompilationUnit
        :return: A list of imports
        """
        if path:
            return path[0].imports
        elif compilationUnit:
            return compilationUnit.imports
        else:
            return None

    def get_variable_declaration(self, node, path):
        """
        This method is just a wrapper around the _get_variable_declaration
        method that just makes calling it much easier.
        :param node:
        :param path:
        :return:
        """

        parentMethod = self.get_parent_declaration(path)
        parentClass = self.get_class_declaration(path)
        imports = self.get_imports(path)
        if parentMethod and parentClass:
            if type(node) is javalang.tree.MemberReference:
                return self._get_variable_declaration(node.member, node.qualifier, parentMethod, parentClass, imports)

            elif type(node) is javalang.tree.MethodInvocation:
                if node.qualifier:
                    return self._get_variable_declaration(node.qualifier, None, parentMethod, parentClass, imports)
                else:
                    return self._get_variable_declaration(node.member, node.qualifier, parentMethod, parentClass, imports)

        return None

    def _get_variable_declaration(self, name, qualifier, parentDecl, classDecl, imports):
        """
        This method is used when trying to find where a variable is declared.
        We commonly use this to resolve where the variable 'request' is declared
        like in the following example code:
        ```java
        public static String smvcten_two_lone(HttpServletRequest request) {
            return request.getParameter("b");
        }
        ```
        This method will pull out the node to 'HttpServletRequest request' which
        we later use to resolve the type FQN of the variable.
        :param name: The name of the variable
        :param qualifier: The qualifier for the variable, can be None
        :param parentDecl: The parent that the variable nested under
        :param classDecl: The class everything is nested under
        :param imports: The list of import from the javalang compilation unit
        :return: The javalang node for the declaration or None if not found
        """
        # Check method for FormalParameters and LocalVariableDeclarations
        for p, n in parentDecl:
            if type(n) is javalang.tree.FormalParameter:
                if n.name == name:
                    return n
            elif type(n) is javalang.tree.LocalVariableDeclaration:
                for d in n.declarators:
                    if d.name == name:
                        return n
        # Check class for FieldDeclarations
        for f in classDecl.fields:
            for d in f.declarators:
                if d.name == name:
                    return f
        # Check imports
        for i in imports:
            if qualifier:
                if i.path.endswith(qualifier):
                    return i
            elif name:
                if i.path.endswith(name):
                    return i
        # Check the class for a MethodDeclaration
        for method in classDecl.methods:
            if method.name == name:
                return method

        # Default
        return None

    def resolve_type(self, name, packageDecl, imports):
        parent = name.split(".")[0]
        # Check imports
        for i in imports:
            if i.path.endswith(parent):
                fqn = i.path.find(parent)
                fqn = i.path[:fqn] + name
                return fqn
        # Check java.lang
        if "java.lang." + parent in JAVA_DOT_LANG_IMPORTS:
            return "java.lang." + name
        # Check primitives
        if name in JAVA_PRIMITIVES:
            return name
        # Check package
        if packageDecl is not None:
            if ".".join([packageDecl.name, parent]) in self.classLookupTable.keys():
                return ".".join([packageDecl.name, name])
        else:
            if parent in self.classLookupTable.keys():
                return name
        # Assume it is fqn
        return name

    def check_annotation_type(self, path):
        for element in reversed(path):
            if type(element) is javalang.tree.ClassDeclaration:
                return "class"
            elif type(element) is javalang.tree.MethodDeclaration:
                return "method"
            elif type(element) in [javalang.tree.VariableDeclaration, javalang.tree.LocalVariableDeclaration]:
                return "variable"
            elif type(element) is javalang.tree.FormalParameter:
                return "parameter"
            elif type(element) is javalang.tree.PackageDeclaration:
                return "package"

    def find_code_base_dir(self, relativePath=None):
        """
        Find the base code directory. This is used in conjunction with a package line to construct the
        path to a java file.
        :param relativePath: A reference path if there are multiple base code dirs.
        This is used to find the most likely base code path. Optional.
        :return: A string with the base directory path
        """
        globPath = os.path.join(self.workingDir, '**', '*.java')
        files = glob.glob(globPath, recursive=True)

        baseCodePaths = set()

        for srcFile in files:
            with codecs.open(srcFile, 'r', 'utf-8', 'ignore') as f:
                for line in f:
                    if line.startswith('package '):
                        # split on space and grab second element, replace . with /, and remove ;
                        # from: "package com.indeed.security.wes.west.servlets.JS001;"
                        # to: "com/indeed/security/wes/west/servlets"
                        package = line.split(' ')[1].replace('.', '/').replace(';', '')

                        baseCodePaths.add(srcFile.split(package.strip())[0])
                        break
                    else:
                        continue

        if len(baseCodePaths) == 1:
            # If just one path return it
            return baseCodePaths.pop()
        elif len(baseCodePaths) > 1 and relativePath:
            # Find the most likely base code path base on the relativePath
            mostLikelyPath = {'path': None, 'similarity': 0}
            splitRelativePath = relativePath.split('/')

            for path in baseCodePaths:
                similarity = 0
                for index, value in enumerate(path.split('/')):
                    if value == splitRelativePath[index]:
                        similarity += 1
                    else:
                        break

                if similarity > mostLikelyPath['similarity']:
                    mostLikelyPath = {
                        'similarity': similarity,
                        'path': path
                    }

            return mostLikelyPath['path']

        elif len(baseCodePaths) > 1:
            # If no relativePath just return first result.
            return baseCodePaths.pop()
        else:
            return None


class PythonProcessor:
    """
    This class is used as a wrapper around the typed_ast module.
    """
    def __init__(self, workingDir):
        """
        Initializes the Python Processor object which is used to load a python project and shares some commonly used
        methods
        :param workingDir: The directory the git repo was cloned to
        """
        self.workingDir = workingDir
        self.pythonFileAsts = {}

    def load_project(self):
        """
        This method simply finds all the *.py files and loads them into ASTs and adds them all to the pythonFileAsts
        dictionary for processing.
        :return: None
        """
        # Find all of the python files
        globPath = os.path.join(self.workingDir, '**', '*.py')
        projectFiles = glob.glob(globPath, recursive=True)
        projectFiles = list(filter(lambda x: os.path.isfile(x), projectFiles))

        # Loop through the files looking for endpoints
        for f in projectFiles:
            # print("FILE: {}".format(f))
            try:
                with codecs.open(f, 'r', 'utf-8', 'ignore') as fh:
                    code = fh.read()
            except UnicodeDecodeError as e:
                print(e)
                continue
            # Use typed_ast library to parse the code for easier analysis
            try:
                # Try parsing as python 3.5 code
                tree = ast3.parse(code)
            except SyntaxError:
                tree = self._load_27_code(code)

            if tree:
                self.pythonFileAsts[self.strip_work_dir(f)] = tree

    def _load_27_code(self, code):
        """
        Loads code from a python 27 project and returns the AST once converted to a python 3 AST
        :param code: The string containing the python code
        :return: Python 3 AST
        """
        try:
            # Try parsing as python 2.7 code
            tree = ast27.parse(code)
            # convert ast to v3
            return conversions.py2to3(tree)
        except SyntaxError as e:
            print("There was a problem parsing the syntax in this code.", e)

    def filter_ast(self, startingNode, objectType):
        """
        This method is just a auxiliary method that is used to filter from a starting node and then looks at all the
        children.
        :param startingNode: The node you want to start from. Should be an AST object.
        :param objectType: The type you want to look for. Ex. _ast3.Dict
        :return: An Iterable with all the object of type you specified
        """
        return filter(lambda x: type(x) is objectType, ast3.walk(startingNode))

    def strip_work_dir(self, path):
        """
        Used to remove the workingDir from the path you specify
        :param path: The path you would like to remove self.workingDir from
        :return: The path minus self.workingDir and the leading slash
        """
        return path.split(self.workingDir, 1)[1][1:]

    def parse_python_method_args(self, astCallObject, orderedArgs):
        """
        This method is used to parse out a python method/function call arguments into a dictionary. It takes an ast call
        object and an ordered list of args that it will try to pull out.
        :param astCallObject: The object whose parameters you're trying to parse
        :param orderedArgs: A list with the names of the arguments. ex. ["request", "parameter", "otherParam"]
        :return: A dictionary with the keys being the argument names and the values being the values passed in
        """
        results = {}
        # loop through all the positional arguments
        for i in range(len(astCallObject.args)):
            # Let's make our life easier and resolve the literals
            arg = astCallObject.args[i]
            if type(arg) in [_ast3.Str, _ast3.Bytes, _ast3.Tuple, _ast3.Num,
                             _ast3.List, _ast3.Set, _ast3.Dict]:
                try:
                    results[orderedArgs[i]] = ast3.literal_eval(arg)
                except IndexError:
                    pass
                except ValueError:
                    results[orderedArgs[i]] = arg
            else:
                results[orderedArgs[i]] = arg

        # Now let's do that same for the keyword args
        for k in astCallObject.keywords:
            if type(k.value) in [_ast3.Str, _ast3.Bytes, _ast3.Tuple,
                                 _ast3.Num, _ast3.List, _ast3.Set,
                                 _ast3.Dict]:
                results[k.arg] = ast3.literal_eval(k.value)
            else:
                results[k.arg] = k.value

        return results
