import os
import sys
import pytest
from pprint import pprint
from wes.main import clone_update_repo
from wes.framework_plugins.common import JavaProcessor
import javalang
import random

@pytest.fixture(scope="module")
def processor(tmpdir_factory):
    # Setup the object by cloning WEST and creating instance of JavaProcessor
    workingDir = str(tmpdir_factory.getbasetemp())
    project = {'baseUrl': 'http://west.example.com/', 'gitRepo': 'git@github.com:indeedsecurity/WEST.git'}
    projectRepoPath = project['gitRepo'].split(':')[-1][:-4]
    projectName = project['gitRepo'].split('/')[-1][:-4]
    productGroup = projectRepoPath.split('/')[0]

    groupFolder = os.path.join(workingDir, productGroup)
    projectFolder = os.path.join(groupFolder, projectName)

    # clone/update the repositories
    clone_update_repo(projectFolder, project['gitRepo'])

    return JavaProcessor(workingDir=projectFolder)


def test_processor_init(processor):
    assert type(processor) is JavaProcessor
    assert hasattr(processor, 'workingDir')
    assert hasattr(processor, 'webContextDir')
    assert hasattr(processor, 'javaCompilationUnits')
    assert hasattr(processor, 'variableLookupTable')


def test_load_project(processor, mocker):
    mocked_preprocess_java_literals = mocker.patch('wes.framework_plugins.common.JavaProcessor._preprocess_java_literals')
    mocked_preprocess_java_variables = mocker.patch('wes.framework_plugins.common.JavaProcessor._preprocess_java_variables')
    processor.load_project()
    assert len(processor.javaCompilationUnits.keys()) > 0, "Check that we loaded things into the dict"
    assert all('.java' in x for x in processor.javaCompilationUnits.keys()), "Check all keys in dict have .java in them"

def test_strip_work_dir(processor):
    path = "myawesomePath/Testing/workingDir/CANiMeSSItuP.TxT"
    fullPath = os.path.join(processor.workingDir, path)
    assert processor.strip_work_dir(fullPath) == path, "Check that it removes working dir"
    with pytest.raises(IndexError):
        processor.strip_work_dir("Testing")

def test_resolve_node_fqn_with_qualifier(processor):
    westFile = "java/src/main/java/com/indeed/security/wes/west/controllers/SMVC010.java"
    cu = processor.javaCompilationUnits[westFile]
    fqns = set()
    for path, node in cu.filter(javalang.tree.VariableDeclarator):
        if type(node.initializer) is javalang.tree.Literal:
            fqns.add(processor.resolve_node_fqn(path, node.name, node.initializer.qualifier))

    assert fqns == set([
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_03_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_07_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_09_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_11_VIEW",
    ])

def test_resolve_node_fqn_without_qualifier(processor):
    westFile = "java/src/main/java/com/indeed/security/wes/west/controllers/SMVC010.java"
    cu = processor.javaCompilationUnits[westFile]
    fqns = set()
    for path, node in cu.filter(javalang.tree.VariableDeclarator):
        if type(node.initializer) is javalang.tree.Literal:
            fqns.add(processor.resolve_node_fqn(path, node.name))

    assert fqns == set([
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_03_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_07_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_09_PARAM",
        "com.indeed.security.wes.west.controllers.SMVC010.SMVC010_11_VIEW",
    ])

def test_resolve_binary_operation_literals(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString" + "MySecondString";
}
    """
    )
    results = set()
    for path, node in tree.filter(javalang.tree.VariableDeclarator):
        if type(node.initializer) is javalang.tree.BinaryOperation:
            results.add(processor._resolve_binary_operation((path, node)))

    assert results == set(['MyStringMySecondString'])


def test_resolve_binary_operation_mixed(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";
    private final String TEST2 = TEST1 + "MySecondString";
}
    """
    )
    results = set()

    processor.variableLookupTable.update(processor._preprocess_java_literals(tree))

    for path, node in tree.filter(javalang.tree.VariableDeclarator):
        if type(node.initializer) is javalang.tree.BinaryOperation:
            results.add(processor._resolve_binary_operation((path, node)))

    assert results == set(['MyStringMySecondString'])


def test_resolve_binary_operation_member_references(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";
    private final String TEST2 = "MySecondString";
    private final String TEST3 = TEST1 + TEST2;
}
    """
    )
    results = set()

    processor.variableLookupTable.update(processor._preprocess_java_literals(tree))

    for path, node in tree.filter(javalang.tree.VariableDeclarator):
        if type(node.initializer) is javalang.tree.BinaryOperation:
            results.add(processor._resolve_binary_operation((path, node)))

    assert results == set(['MyStringMySecondString'])

def test_preprocess_java_literals(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";
    private final String TEST2 = "MySecondString";
    private final Integer TEST3 = 12;
    private final Boolean TEST4 = true;
}
    """
    )
    results = processor._preprocess_java_literals(tree)

    assert (
    'com.indeed.security.wes.tester.Test.TEST1',
    'MyString'
    ) in results.items()
    assert (
    'com.indeed.security.wes.tester.Test.TEST2',
    'MySecondString'
    ) in results.items()

    # TODO: We currently are only processing Strings. In the future we might add more.
    # assert (
    # 'com.indeed.security.wes.tester.Test.TEST3',
    # 12
    # ) in results.items()
    # assert (
    # 'com.indeed.security.wes.tester.Test.TEST4',
    # True
    # ) in results.items()

def test_preprocess_java_variables(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";
    private final String TEST2 = "MySecondString";
    private final String TEST3 = TEST1 + TEST2;
    private final String TEST4 = TEST3 + TEST1;
    private final String TEST5 = TEST4 + "This is gonna be tricky...";
}
    """
    )
    processor.variableLookupTable.update(processor._preprocess_java_literals(tree))
    results = processor._preprocess_java_variables(tree)

    assert (
    'com.indeed.security.wes.tester.Test.TEST3',
    'MyStringMySecondString'
    ) in results.items()
    # TODO: We currently are only processing through the variables once. In the
    # future we'll make it recursive and we'll be able to find the following
    # assertions
    # assert (
    # 'com.indeed.security.wes.tester.Test.TEST4',
    # 'MyStringMySecondStringMyString'
    # ) in results.items()
    # assert (
    # 'com.indeed.security.wes.tester.Test.TEST5',
    # 'MyStringMySecondStringMyStringThis is gonna be tricky...'
    # ) in results.items()

def test_find_path_to_element(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";

    public String test() {
        final String TEST2 = "MySecondString";
        return "Got it!";
    }
}
    """
    )

    paths = []
    for x in range(0, 5):
        node = random.choice(list(tree))[-1]
        paths.append(processor.find_path_to_element(tree, node))

    assert len(paths) == 5

def test_filter_on_path(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";

    public String test() {
        final String TEST2 = "MySecondString";
        return "Got it!";
    }
}
    """
    )
    # Grab the method and filter from there
    methodPath, methodNode = list(tree.filter(javalang.tree.MethodDeclaration))[0]

    # Test if it works with tree
    results = processor.filter_on_path(methodNode, javalang.tree.VariableDeclarator, tree)
    assert len(results) == 1

    # Test if it works without tree with relative paths
    results = processor.filter_on_path(methodNode, javalang.tree.VariableDeclarator)
    assert len(results) == 1

def test_get_jsp_params(processor):
    westFile = "WEB-INF/jsp/controllers/smvc004-05.jsp"
    params = processor.get_jsp_params(westFile)
    assert params == ['k']

def test_resolve_member_reference(processor):
    tree = javalang.parse.parse(
    """
package com.indeed.security.wes.tester;
class Test {
    private final String TEST1 = "MyString";
    private final String TEST2 = "MySecondString";
    private final String TEST3 = TEST1 + TEST2;
    private final String TEST4 = TEST3 + TEST1;
    private final String TEST5 = TEST4 + "This is gonna be tricky...";
}
    """
    )
    processor.variableLookupTable.update(processor._preprocess_java_literals(tree))

    member = list(filter(lambda x: type(x[1]) is javalang.tree.MemberReference, tree))[0][1]

    value = processor.resolve_member_reference(tree, member.member, qualifier=None)
    assert member.member == "TEST1"
    assert value == "MyString"

def test_find_java_web_context_found(processor):
    webContextDir = processor._find_java_web_context()
    assert webContextDir == "java/src/main/webapp/"

def test_find_java_web_context_not_found(processor, mocker):
    mocked_glob = mocker.patch('glob.glob', return_value=['test1', 'test2'])
    webContextDir = processor._find_java_web_context()
    assert webContextDir == "web/"

def test_find_code_base_dir(processor, mocker):
    mocker.patch('glob.glob', return_value=['java/src/main/java/com/indeed/security/wes/MyClass.java'])
    mocker.patch('codecs.open', mocker.mock_open(read_data="package com.indeed.security.wes;"))

    assert processor.find_code_base_dir() == 'java/src/main/java/'

def test_find_code_base_dir_bad(processor, mocker):
    mocker.patch('glob.glob', return_value=['java/src/main/java/com/indeed/security/wes/MyClass.java'])
    mocker.patch('codecs.open', mocker.mock_open(read_data="Just a random string"))

    assert processor.find_code_base_dir() == None
