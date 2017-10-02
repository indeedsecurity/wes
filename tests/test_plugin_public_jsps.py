import pytest
from wes.main import clone_update_repo
from wes.framework_plugins.common import JavaProcessor
from wes.framework_plugins.plugin_public_jsps import CustomFramework
import os

@pytest.fixture(scope="module")
def plugin(tmpdir_factory):
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

    processors = {
        'java': JavaProcessor(workingDir=projectFolder)
    }
    processors['java'].load_project()

    return CustomFramework(workingDir=os.path.abspath(projectFolder), processors=processors)

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
    webContextDir = plugin._find_java_web_context()
    assert webContextDir == 'ThisShouldBeTheRightPath/'

def test_find_java_web_context_bad(plugin, mocker):
    mocker.patch('glob.glob', return_value=['test1', 'ThisShouldBeTheRightPath/test.jsp', 'index.jsp'])
    webContextDir = plugin._find_java_web_context()
    assert webContextDir == 'web/'
