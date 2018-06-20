# WES - Wintermute Endpoint Search
WES is a static code analyzer for web applications that doesn’t take the
traditional approach of showing where problems may exist in our code. Rather WES
simply pulls all of the endpoints, parameters, templates, methods, and line
numbers for each, right out of the source code. These results can then be used
to feed a dynamic scanner as a site map of the application. Reading all of this
information right from the source code allows for a more complete listing of
vectors for your dynamic scan than traditional techniques(crawlers, proxies,
and brute forcers).

Currently WES supports processing the following frameworks:
- Spring
- Java Servlets
- JavaServer Pages (JSP)
- Django

## Installation
To install the project you will want to do the following:

From Github:
```
pip install git+ssh://git@github.com/indeedsecurity/wes.git
```
or 
```
pip install git+https://github.com/indeedsecurity/wes.git
```

## Running
### Processing the source code
WES supports a few methods of running from the command line. You have the option
of supplying a git repository address (eg. git@github.com:owner/project.git) or
a folder which contains the source code.

Running WES on individual projects can be done with the following commands:

#### Folder
```
wes -f myProjectFolder -u http://myProjectsBaseUrl.com
```

#### Git repo
```
wes -r git@github.com:owner/project.git -u http://myProjectsBaseUrl.com
```

## Running tests
All of the following commands should be run from the root WES directory.

### Unit tests
```
pytest tests
```

### Integration test
```
pytest integrationTest
```

### Code coverage
```
pytest --cov-config .coveragerc --cov wes --cov-report term-missing tests
```
