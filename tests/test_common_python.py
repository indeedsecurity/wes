import os
import sys
import pytest
from pprint import pprint
from wes.main import clone_update_repo
from wes.framework_plugins.common import PythonProcessor
from typed_ast import ast3
import _ast3

@pytest.fixture(scope="module")
def processor(tmpdir_factory):
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

    return PythonProcessor(workingDir=projectFolder)


def test_processor_init(processor):
    assert type(processor) is PythonProcessor
    assert hasattr(processor, 'workingDir')
    assert hasattr(processor, 'pythonFileAsts')

# Still need a python project in WEST before we can test the load_python_project method
# def test_load_python_project(processor):
#     pass

def test_filter_ast(processor):
    myAst = ast3.parse(
    """
def testing(request):
    TEST1 = True
    if TEST1:
        print("Got here first!")
        TEST2 = "Eat my dust"
        print(TEST2 + "!")
    else:
        print("No I got here first!")
        TEST3 = "Oh yeah I won"
        TEST4 = "Okay well yeah this is a string"
        print(TEST3 + "!")
TEST5 = "YOU CAN'T SEE ME"
    """
    )

    assert len(list(processor.filter_ast(myAst, _ast3.Assign))) == 5
    assert len(list(processor.filter_ast(myAst.body[0], _ast3.Assign))) == 4
    assert len(list(processor.filter_ast(myAst.body[0], _ast3.Assign))) == 4
    assert len(list(processor.filter_ast(myAst.body[0], _ast3.Assign))) == 4

def test_strip_work_dir(processor):
    path = "myawesomePath/Testing/workingDir/CANiMeSSItuP.TxT"
    fullPath = os.path.join(processor.workingDir, path)
    assert processor.strip_work_dir(fullPath) == path, "Check that it removes working dir"
    with pytest.raises(IndexError):
        processor.strip_work_dir("Testing")

def test_parse_python_method_args(processor):
    myAst = ast3.parse(
    """
testing1(1, 2, 3)
testing2(name1=1, name2=2, name3="3")
testing3(1, 2, 3, name=4)
testing4(1, 2, 3, 4, 5, 6, 7)
testing5(1, 2, 3, name3=4)
    """
    )
    args = processor.parse_python_method_args(myAst.body[0].value, ['arg1', 'arg2', 'arg3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3}

    args = processor.parse_python_method_args(myAst.body[1].value, ['name1', 'name2', 'name3'])
    assert args == {'name1': 1, 'name2': 2, 'name3': '3'}

    args = processor.parse_python_method_args(myAst.body[2].value, ['arg1', 'arg2', 'arg3', 'name'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3, 'name': 4}

    args = processor.parse_python_method_args(myAst.body[3].value, ['arg1', 'arg2', 'arg3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3}

    args = processor.parse_python_method_args(myAst.body[4].value, ['arg1', 'arg2', 'arg3', 'name1', 'name2', 'name3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3, 'name3': 4}