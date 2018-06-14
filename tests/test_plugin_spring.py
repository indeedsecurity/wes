import pytest
from wes.main import clone_update_repo
from wes.framework_plugins.common import JavaProcessor
from wes.framework_plugins.plugin_spring import CustomFramework
import os
import javalang

@pytest.fixture(scope="module")
def plugin(tmpdir_factory):
    # Setup the object by cloning WEST and creating instance of JavaProcessor
    working_dir = str(tmpdir_factory.getbasetemp())
    project = {'base_url': 'http://west.example.com/', 'git_repo': 'git@github.com:indeedsecurity/WEST.git'}
    project_repo_path = project['git_repo'].split(':')[-1][:-4]
    project_name = project['git_repo'].split('/')[-1][:-4]
    product_group = project_repo_path.split('/')[0]

    group_folder = os.path.join(working_dir, product_group)
    project_folder = os.path.join(group_folder, project_name)

    # clone/update the repositories
    clone_update_repo(project_folder, project['git_repo'])

    processors = {
        'java': JavaProcessor(working_dir=project_folder)
    }
    processors['java'].load_project()

    return CustomFramework(working_dir=os.path.abspath(project_folder), processors=processors)

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
    plugin.processor.java_compilation_units['test_file1'] = javalang.parse.parse(
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

    plugin._find_request_mappings('test_file1')

    endpoint_dict = plugin.endpoints[-1]

    assert endpoint_dict['endpoints'] == set(['/SMVC001'])
    assert endpoint_dict['filepath'] == 'test_file1'
    assert endpoint_dict['methods'] == set(['GET'])
    assert endpoint_dict['params'] == []
    assert str(endpoint_dict['java_path']) == '(CompilationUnit, [ClassDeclaration], ClassDeclaration, [MethodDeclaration], MethodDeclaration)'

def test_find_request_mappings_class(plugin):
    plugin.processor.java_compilation_units['test_file2'] = javalang.parse.parse(
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

    beginning_length = len(plugin.endpoints)
    plugin._find_request_mappings('test_file2')
    final_length = len(plugin.endpoints)

    assert beginning_length + 1 == final_length

    endpoint_dict = plugin.endpoints[-1]

    assert endpoint_dict['endpoints'] == set(['/test/SMVC001'])

def test_find_request_mappings_abstract(plugin):
    plugin.processor.java_compilation_units['test_file3'] = javalang.parse.parse(
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

    beginning_length = len(plugin.endpoints)
    plugin._find_request_mappings('test_file3')
    final_length = len(plugin.endpoints)

    assert beginning_length == final_length

def test_find_request_mappings_no_controller(plugin):
    plugin.processor.java_compilation_units['test_file4'] = javalang.parse.parse(
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

    beginning_length = len(plugin.endpoints)
    plugin._find_request_mappings('test_file4')
    final_length = len(plugin.endpoints)

    assert beginning_length == final_length

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

    fake_annotation = Object()
    fake_annotation.element = ''

    assert plugin._parse_req_map_annotation(fake_annotation, '') == {
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

    fake_annotation = Object()
    fake_annotation.element = ''

    assert plugin._parse_req_map_annotation(fake_annotation, '') == {
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

    anno_dictionary = plugin._parse_anno_args_to_dict(anno.element)

    assert type(anno_dictionary['value']) is javalang.tree.Literal
    assert type(anno_dictionary['method']) is javalang.tree.MemberReference

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

    anno_dictionary = plugin._parse_anno_args_to_dict(anno.element)
    resolved_dictionary = plugin._resolve_values_in_dict(anno_dictionary, tree)

    assert resolved_dictionary == {
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

    first_test = plugin._combine_endpoint_sets(parent1, child1)
    assert ('endpoints', {'/test1/test3', '/test1/test4', '/test2/test3', '/test2/test4'}) in first_test.items()
    assert ('methods', {'GET'}) in first_test.items()
    assert ('headers', set()) in first_test.items()
    assert ('line_number', None) in first_test.items()
    assert set(first_test['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}

    second_test = plugin._combine_endpoint_sets(parent1, child2)
    assert ('endpoints', {'/test1', '/test2'}) in second_test.items()
    assert ('methods', {'GET'}) in second_test.items()
    assert ('headers', set()) in second_test.items()
    assert ('line_number', None) in second_test.items()
    assert set(second_test['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}

    third_test = plugin._combine_endpoint_sets(parent2, child1)
    assert ('endpoints', {'/test3', '/test4'}) in third_test.items()
    assert ('methods', {'GET'}) in third_test.items()
    assert ('headers', set()) in third_test.items()
    assert ('line_number', None) in third_test.items()
    assert set(third_test['params']) == {'testParam1', 'testParam2', 'testParam3', 'testParam4'}


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
        'java_path': anno[0],
        'params': [],
        'filepath': 'test_file1'
    }

    assert plugin._find_request_param(endpoint)['params'] == [{'name': 'a', 'filepath': 'test_file1', 'line_number': 10}]

def test_parse_req_param_anno(plugin, mocker):
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._parse_anno_args_to_dict')
    mocker.patch('wes.framework_plugins.plugin_spring.CustomFramework._resolve_values_in_dict',
                 return_value={'value': 'testParam'})

    class Object(object):
        pass

    fake_annotation = Object()
    fake_annotation.element = 'test'

    assert plugin._parse_req_param_anno(fake_annotation, '') == 'testParam'

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
        'java_path': anno[0],
        'params': [],
        'filepath': 'test_file1'
    }

    assert plugin._find_request_get_param(endpoint)['params'] == [{'name': 'b', 'filepath': 'test_file1', 'line_number': 11}]

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

    endpoint1 = {'java_path': anno1[0]}
    endpoint2 = {'java_path': anno2[0]}
    endpoint3 = {'java_path': anno3[0]}
    endpoint4 = {'java_path': anno4[0]}

    assert plugin._find_referenced_jsps(endpoint1)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc001.jsp'}
    assert plugin._find_referenced_jsps(endpoint2)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc002.jsp'}
    assert plugin._find_referenced_jsps(endpoint3)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc003.jsp'}
    assert plugin._find_referenced_jsps(endpoint4)['templates'] == {'java/src/main/webapp/WEB-INF/jsp/controllers/smvc004.jsp'}

def test_find_params_in_jsps(plugin, mocker):
    mocker.patch('wes.framework_plugins.common.JavaProcessor.get_jsp_params',
                 return_value=['c'])

    endpoint = {
        'templates': {plugin.processor.web_context_dir + 'myTemplate'},
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
    expected_endpoints = [
        {
            'endpoints': set(['test/path/[^/]*', 'profile']),
            'params': set(['test1', 'test2']),
            'methods': set(['POST', 'GET'])
        }
    ]
    assert plugin._clean_endpoints(endpoints) == expected_endpoints
