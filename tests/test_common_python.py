import os
import sys
import pytest
from pprint import pprint
from wes.main import clone_update_repo
from wes.framework_plugins.common import PythonProcessor
from typed_ast import ast3, _ast3

@pytest.fixture(scope="module")
def processor(tmpdir_factory):
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

    return PythonProcessor(working_dir=project_folder)


def test_processor_init(processor):
    assert type(processor) is PythonProcessor
    assert hasattr(processor, 'working_dir')
    assert hasattr(processor, 'python_file_asts')

# Still need a python project in WEST before we can test the load_python_project method
# def test_load_python_project(processor):
#     pass

def test_filter_ast(processor):
    my_ast = ast3.parse(
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

    assert len(list(processor.filter_ast(my_ast, _ast3.Assign))) == 5
    assert len(list(processor.filter_ast(my_ast.body[0], _ast3.Assign))) == 4
    assert len(list(processor.filter_ast(my_ast.body[0], _ast3.Assign))) == 4
    assert len(list(processor.filter_ast(my_ast.body[0], _ast3.Assign))) == 4

def test_strip_work_dir(processor):
    path = "myawesomePath/Testing/working_dir/CANiMeSSItuP.TxT"
    full_path = os.path.join(processor.working_dir, path)
    assert processor.strip_work_dir(full_path) == path, "Check that it removes working dir"
    with pytest.raises(IndexError):
        processor.strip_work_dir("Testing")

def test_parse_python_method_args(processor):
    my_ast = ast3.parse(
    """
testing1(1, 2, 3)
testing2(name1=1, name2=2, name3="3")
testing3(1, 2, 3, name=4)
testing4(1, 2, 3, 4, 5, 6, 7)
testing5(1, 2, 3, name3=4)
    """
    )
    args = processor.parse_python_method_args(my_ast.body[0].value, ['arg1', 'arg2', 'arg3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3}

    args = processor.parse_python_method_args(my_ast.body[1].value, ['name1', 'name2', 'name3'])
    assert args == {'name1': 1, 'name2': 2, 'name3': '3'}

    args = processor.parse_python_method_args(my_ast.body[2].value, ['arg1', 'arg2', 'arg3', 'name'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3, 'name': 4}

    args = processor.parse_python_method_args(my_ast.body[3].value, ['arg1', 'arg2', 'arg3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3}

    args = processor.parse_python_method_args(my_ast.body[4].value, ['arg1', 'arg2', 'arg3', 'name1', 'name2', 'name3'])
    assert args == {'arg1': 1, 'arg2': 2, 'arg3': 3, 'name3': 4}