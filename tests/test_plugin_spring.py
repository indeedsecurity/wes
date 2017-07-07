import pytest
from wes.main import clone_update_repo
from wes.framework_plugins.common import JavaProcessor
from wes.framework_plugins.plugin_spring import CustomFramework
import os
import javalang

@pytest.fixture(scope="module")
def plugin(tmpdir_factory):
    # Setup the object by cloning WEST and creating instance of JavaProcessor
    workingDir = str(tmpdir_factory.getbasetemp())
    project = {'baseUrl': 'http://west.indeed.com/', 'gitRepo': 'git@github.com:indeedsecurity/WEST.git'}
    projectRepoPath = project['gitRepo'].split(':')[-1][:-4]
    projectName = project['gitRepo'].split('/')[-1][:-4]
    productGroup = projectRepoPath.split('/')[0]

    groupFolder = os.path.join(workingDir, productGroup)
    projectFolder = os.path.join(groupFolder, projectName)

    # clone/update the repositories
    clone_update_repo(projectFolder, project['gitRepo'])

    processors = {
        'java': JavaProcessor(workingDir=projectFolder)
    }
    processors['java'].load_project()

    return CustomFramework(workingDir=os.path.abspath(projectFolder), processors=processors)

def test_identify(plugin, mocker):
    # This test will be tricky... I'm gonna put this off till later
    assert plugin.identify() == True

    mocker.patch('glob.glob', return_value=[])
    assert plugin.identify() == False

def test_find_endpoints(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_request_mappings',
                 return_value=['1', '2'])

    plugin.endpoints = [1, 2]
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_parameters')

    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._clean_endpoints',
                 return_value="Success!")

    assert plugin.find_endpoints() == 'Success!'

def test_find_request_mappings(plugin):
    plugin.processor.javaCompilationUnits['TestFile1'] = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    plugin._find_request_mappings('TestFile1')

    endpointDict = plugin.endpoints[-1]

    assert endpointDict['endpoints'] == set(['/SMVC001'])
    assert endpointDict['filepath'] == 'TestFile1'
    assert endpointDict['methods'] == set(['GET'])
    assert endpointDict['params'] == []
    assert str(endpointDict['javaPath']) == '(CompilationUnit, [ClassDeclaration], ClassDeclaration, [MethodDeclaration], MethodDeclaration)'

def test_find_request_mappings_class(plugin):
    plugin.processor.javaCompilationUnits['TestFile2'] = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
@RequestMapping(value = "/test", method = RequestMethod.GET)
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    beginningLength = len(plugin.endpoints)
    plugin._find_request_mappings('TestFile2')
    finalLength = len(plugin.endpoints)

    assert beginningLength + 1 == finalLength

    endpointDict = plugin.endpoints[-1]

    assert endpointDict['endpoints'] == set(['/test/SMVC001'])

def test_find_request_mappings_abstract(plugin):
    plugin.processor.javaCompilationUnits['TestFile3'] = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public abstract class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    beginningLength = len(plugin.endpoints)
    plugin._find_request_mappings('TestFile3')
    finalLength = len(plugin.endpoints)

    assert beginningLength == finalLength

def test_find_request_mappings_no_controller(plugin):
    plugin.processor.javaCompilationUnits['TestFile4'] = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    beginningLength = len(plugin.endpoints)
    plugin._find_request_mappings('TestFile4')
    finalLength = len(plugin.endpoints)

    assert beginningLength == finalLength

def test_has_controller_anno_false(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    rs = list(tree.filter(javalang.tree.ReturnStatement))[0]
    assert plugin._has_controller_anno(rs[0]) == False

def test_has_controller_anno_true(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    rs = list(tree.filter(javalang.tree.ReturnStatement))[0]
    assert plugin._has_controller_anno(rs[0]) == True

def test_get_parent_class(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    rs = list(tree.filter(javalang.tree.ReturnStatement))[0]
    assert type(plugin._get_parent_class(rs[0])) is javalang.tree.ClassDeclaration

def test_get_parent_request_mapping(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
@RequestMapping(value = "/test", method = RequestMethod.GET)
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    md = list(tree.filter(javalang.tree.MethodDeclaration))[0]

    assert plugin._get_parent_request_mapping(md[0]) == {
        'endpoints': {'/test'},
        'methods': {'GET'},
        'params': [],
        'headers': set()
    }

def test_parse_req_map_annotation(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._parse_anno_args_to_dict')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._resolve_values_in_dict',
                 return_value={
                    'value': '/test',
                    'method': 'GET',
                    'params': 'myParam'
                 })

    class Object(object):
        pass

    fakeAnnotation = Object()
    fakeAnnotation.element = ''

    assert plugin._parse_req_map_annotation(fakeAnnotation, '') == {
        'endpoints': {'/test'},
        'methods': {'GET'},
        'params': ['myParam'],
        'headers': set()
    }

def test_parse_req_map_annotation_lists(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._parse_anno_args_to_dict')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._resolve_values_in_dict',
                 return_value={
                    'value': ['/test', '/test2'],
                    'method': ['GET', 'POST'],
                    'params': ['myParam', 'test']
                 })

    class Object(object):
        pass

    fakeAnnotation = Object()
    fakeAnnotation.element = ''

    assert plugin._parse_req_map_annotation(fakeAnnotation, '') == {
        'endpoints': {'/test', '/test2'},
        'methods': {'GET', 'POST'},
        'params': ['myParam', 'test'],
        'headers': set()
    }

def test_parse_anno_args_to_dict(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public class SMVC001 {
    @RequestMapping(path = "/SMVC001", method = RequestMethod.GET)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)
    anno = list(tree.filter(javalang.tree.Annotation))[1][1]

    annoDictionary = plugin._parse_anno_args_to_dict(anno.element)

    assert type(annoDictionary['value']) is javalang.tree.Literal
    assert type(annoDictionary['method']) is javalang.tree.MemberReference

def test_parse_anno_args_to_dict_not_list(plugin):
    assert plugin._parse_anno_args_to_dict('test') == {'value': 'test'}

def test_resolve_values_in_dict(plugin, mocker):
    mocker.patch('wes.framework_plugins.common.JavaProcessor.resolve_member_reference',
                 return_value='c')

    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
@Controller
public class SMVC001 {
    private final String HEADER_VALUE = "c";
    @RequestMapping(value = "/SMVC00" + "1", method = {
        RequestMethod.GET,
        RequestMethod.POST,
        RequestMethod.DELETE,
        RequestMethod.HEAD,
        RequestMethod.OPTIONS,
        RequestMethod.PUT,
        RequestMethod.TRACE
        }, header = HEADER_VALUE)
    public String get() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)
    anno = list(tree.filter(javalang.tree.Annotation))[1][1]

    annoDictionary = plugin._parse_anno_args_to_dict(anno.element)
    resolvedDictionary = plugin._resolve_values_in_dict(annoDictionary, tree)

    assert resolvedDictionary == {
        'value': '/SMVC001',
        'method': ['GET', 'POST', 'DELETE', 'HEAD', 'OPTIONS', 'PUT', 'TRACE'],
        'header': 'c'
    }

def test_combine_endpoint_sets(plugin):
    parent1 = {
        'endpoints': {'/test1', '/test2'},
        'methods': {'GET'},
        'params': {'testParam1', 'testParam2'}
    }
    parent2 = {
        'methods': {'GET'},
        'params': {'testParam1', 'testParam2'}
    }
    child1 = {
        'endpoints': {'/test3', '/test4'},
        'methods': {'GET'},
        'params': {'testParam3', 'testParam4'}
    }
    child2 = {
        'methods': {'GET'},
        'params': {'testParam3', 'testParam4'}
    }

    firstTest = plugin._combine_endpoint_sets(parent1, child1)
    assert ('endpoints', {'/test1/test3', '/test1/test4', '/test2/test3', '/test2/test4'}) in firstTest.items()
    assert ('methods', {'GET'}) in firstTest.items()
    assert ('headers', set()) in firstTest.items()
    assert ('lineNumber', None) in firstTest.items()
    assert set(firstTest['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}

    secondTest = plugin._combine_endpoint_sets(parent1, child2)
    assert ('endpoints', {'/test1', '/test2'}) in secondTest.items()
    assert ('methods', {'GET'}) in secondTest.items()
    assert ('headers', set()) in secondTest.items()
    assert ('lineNumber', None) in secondTest.items()
    assert set(secondTest['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}

    thirdTest = plugin._combine_endpoint_sets(parent2, child1)
    assert ('endpoints', {'/test3', '/test4'}) in thirdTest.items()
    assert ('methods', {'GET'}) in thirdTest.items()
    assert ('headers', set()) in thirdTest.items()
    assert ('lineNumber', None) in thirdTest.items()
    assert set(thirdTest['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}


def test_find_parameters(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_request_param')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_request_get_param')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_referenced_jsps')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._find_params_in_jsps',
                 return_value=True)

    assert plugin._find_parameters("")

def test_find_request_param(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
@Controller
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get(@RequestParam(name="a", required=false) String a) {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    anno = list(tree.filter(javalang.tree.Annotation))[1]

    endpoint = {
        'javaPath': anno[0],
        'params': [],
        'filepath': 'TestFile1'
    }

    assert plugin._find_request_param(endpoint)['params'] == [{'name': 'a', 'filepath': 'TestFile1', 'lineNumber': 10}]

def test_parse_req_param_anno(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._parse_anno_args_to_dict')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._resolve_values_in_dict',
                 return_value={'value': 'testParam'})

    class Object(object):
        pass

    fakeAnnotation = Object()
    fakeAnnotation.element = 'test'

    assert plugin._parse_req_param_anno(fakeAnnotation, '') == 'testParam'

def test_find_request_get_param(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
@Controller
public class SMVC001 {
    @RequestMapping(value = "/SMVC001", method = RequestMethod.GET)
    public String get(@RequestParam(name="a", required=false) String a) {
        final String b = request.getParameter("b");
        request.setAttribute("b", b);
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
}
    """)

    anno = list(tree.filter(javalang.tree.Annotation))[1]

    endpoint = {
        'javaPath': anno[0],
        'params': [],
        'filepath': 'TestFile1'
    }

    assert plugin._find_request_get_param(endpoint)['params'] == [{'name': 'b', 'filepath': 'TestFile1', 'lineNumber': 11}]

def test_find_referenced_jsps(plugin):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.west.controllers;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.servlet.ModelAndView;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.ServletException;

@Controller
public class SMVC001 {
    @RequestMapping("/01")
    public String one() {
        return "/WEB-INF/jsp/controllers/smvc001.jsp";
    }
    @RequestMapping("/02")
    public String two() {
        return "somethingHere:/WEB-INF/jsp/controllers/smvc002.jsp";
    }
    @RequestMapping("/03")
    public ModelAndView three() {
        return new ModelAndView("/WEB-INF/jsp/controllers/smvc003.jsp");
    }
    @RequestMapping("/04")
    public void four(HttpServletRequest request, HttpServletResponse response) throws ServletException, IOException {
        request.getRequestDispatcher("/WEB-INF/jsp/controllers/smvc004.jsp").forward(request, response);
    }
}
    """)

    anno1 = list(tree.filter(javalang.tree.Annotation))[1]
    anno2 = list(tree.filter(javalang.tree.Annotation))[2]
    anno3 = list(tree.filter(javalang.tree.Annotation))[3]
    anno4 = list(tree.filter(javalang.tree.Annotation))[4]

    endpoint1 = {'javaPath': anno1[0]}
    endpoint2 = {'javaPath': anno2[0]}
    endpoint3 = {'javaPath': anno3[0]}
    endpoint4 = {'javaPath': anno4[0]}

    assert plugin._find_referenced_jsps(endpoint1)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc001.jsp'}
    assert plugin._find_referenced_jsps(endpoint2)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc002.jsp'}
    assert plugin._find_referenced_jsps(endpoint3)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc003.jsp'}
    assert plugin._find_referenced_jsps(endpoint4)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc004.jsp'}

def test_find_params_in_jsps(plugin, mocker):
    mocker.patch('wes.framework_plugins.common.JavaProcessor.get_jsp_params',
                 return_value=['c'])

    endpoint = {
        'templates': {plugin.processor.webContextDir + 'myTemplate'},
        'params': []
    }

    assert plugin._find_params_in_jsps(endpoint)['params'] == [{'name': 'c', 'filepath': 'java/src/main/webapp/myTemplate'}]

def test_convert_endpoint_to_python_regex(plugin):
    assert plugin._convert_endpoint_to_python_regex('mypath/*') == 'mypath/[^/]*'
    assert plugin._convert_endpoint_to_python_regex('mypath/path') == 'mypath/path'
    assert plugin._convert_endpoint_to_python_regex('mypath/*/testing') == 'mypath/[^/]*/testing'
    assert plugin._convert_endpoint_to_python_regex('mypath/**/testing') == 'mypath/.*/testing'
    assert plugin._convert_endpoint_to_python_regex('/03/{one:[a-zA-Z0-9]+}') == '/03/(?P<one>[a-zA-Z0-9]+)'
    assert plugin._convert_endpoint_to_python_regex('/04/{one:[a-zA-Z]+}/{two:[0-9]+}') == '/04/(?P<one>[a-zA-Z]+)/(?P<two>[0-9]+)'

def test_clean_endpoints(plugin):
    endpoints = [
        {
            'endpoints': set(['test/path/*', 'profile']),
            'params': set(['test1', 'test2']),
            'methods': set(['POST', 'GET']),
            'testKey': None
        },
        {
            'params': set(['test1', 'test2'])
        }
    ]
    expectedEndpoints = [
        {
            'endpoints': set(['test/path/[^/]*', 'profile']),
            'params': set(['test1', 'test2']),
            'methods': set(['POST', 'GET'])
        }
    ]
    assert plugin._clean_endpoints(endpoints) == expectedEndpoints
