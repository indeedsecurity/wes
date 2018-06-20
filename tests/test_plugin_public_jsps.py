import pytest
from wes.main import clone_update_repo
from wes.framework_plugins.common import JavaProcessor
from wes.framework_plugins.plugin_public_jsps import CustomFramework
import os

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
    assert plugin.identify() == True
    mocker.patch('glob.glob', return_value=['test1', 'test2'])
    assert plugin.identify() == False

def test_find_endpoints(plugin, mocker):
    mocked_find_public_jsps = mocker.patch('wes.framework_plugins.plugin_public_jsps.CustomFramework.find_public_jsps')
    plugin.find_endpoints()
    mocked_find_public_jsps.assert_called_once_with()

def test_find_public_jsps(plugin):
    public_jsps = plugin.find_public_jsps()
    assert {
        'endpoints': set(['index.jsp']),
        'filepath': 'java/src/main/webapp/index.jsp',
        'methods': set(['GET']),
        'params': [],
        'templates': set(['java/src/main/webapp/index.jsp'])
    } in public_jsps

def test_find_java_web_context(plugin, mocker):
    mocker.patch('glob.glob', return_value=['test1', 'ThisShouldBeTheRightPath/WEB-INF/test.jsp', 'index.jsp'])
    web_context_dir = plugin._find_java_web_context()
    assert web_context_dir == 'ThisShouldBeTheRightPath/'

def test_find_java_web_context_bad(plugin, mocker):
    mocker.patch('glob.glob', return_value=['test1', 'ThisShouldBeTheRightPath/test.jsp', 'index.jsp'])
    web_context_dir = plugin._find_java_web_context()
    assert web_context_dir == 'web/'
