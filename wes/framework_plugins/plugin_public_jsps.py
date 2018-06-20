import glob
# Add to wes to the sys path
import sys
import os
wes_dir = os.path.realpath(os.path.join(__file__, "..", ".."))
sys.path.append(wes_dir)
from wes.framework_plugins.common import Framework


class CustomFramework(Framework):
    def __init__(self, working_dir, processors):
        self.working_dir = working_dir
        self.web_context_dir = self._find_java_web_context()
        self.processor = processors['java']

    def identify(self):
        """
        This method attempts to identify all files within the web context folder with the jsp extension and not under
        the WEB-INF directory. This method returns True if there are files and false if there aren't any.
        :return: Boolean
        """
        glob_path = os.path.join(self.working_dir, self.web_context_dir, '**', '*.jsp')
        files = glob.glob(glob_path, recursive=True)

        files = list(filter(lambda x: os.path.isfile(x) and 'WEB-INF' not in x, files))

        if len(files) > 0:
            return True
        else:
            return False

    def find_endpoints(self):
        """
        This is just a wrapper method around the find_public_jsps to make if consistent across all plugins.
        :return: Dictionary from self.find_public_jsps()
        """
        return self.find_public_jsps()

    def find_public_jsps(self):
        """
        This method attempts to identify all files within the web context folder with the jsp extension and not under
        the WEB-INF directory. It then adds parses the params out of the jsp and adds those to the dictionary.
        :return: A Dictionary with the endpoints
        """
        # Find all of the java files
        glob_path = os.path.join(self.working_dir, self.web_context_dir, '**', '*.jsp')
        project_files = glob.glob(glob_path, recursive=True)
        project_files = list(filter(lambda x: os.path.isfile(x) and 'WEB-INF' not in x, project_files))

        endpoints = []

        for jsp in project_files:
            filepath = self.processor.strip_work_dir(jsp)
            params = self.processor.get_jsp_params(jsp.split(self.web_context_dir)[-1])
            params = list(map(lambda x: {'name': x, 'filepath': filepath}, params))
            endpoints.append({
                'filepath': filepath,
                'endpoints': set([jsp.split(self.web_context_dir)[1]]),
                'params': params if params else [],
                'methods': set(['GET']),
                'templates': set([filepath]) if filepath else set()
            })

        return endpoints

    def _find_java_web_context(self):
        """
        Finds the web context directory for the java project. It does this by looking for directories that contain
        the 'WEB-INF' directory.
        :return: A string with the directory
        """
        glob_path = os.path.join(self.working_dir, '**')
        results = glob.glob(glob_path, recursive=True)
        web_context_dir = None
        for r in results:
            if 'WEB-INF' in r:
                web_context_dir = r
        if not web_context_dir:
            return "web/"

        web_context_dir = web_context_dir.split('WEB-INF')[0].replace(self.working_dir, '').lstrip('/')

        return web_context_dir
