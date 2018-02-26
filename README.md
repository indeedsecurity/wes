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


```

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

#### Multiple projects
There's also a third option if you'd like to process multiple projects by
supplying a CSV file containing the git repositories for each project. Below
you'll see the required format for this csv file.

```
baseUrl,gitRepo
https://example.com,git@github.com:owner/project1.git
https://test.com,git@github.com:owner/project2.git
```

To run WES with the CSV you can supply the following command and it will process
the projects filling it's database with all of the found endpoints and
parameters.

```
wes -rcsv projects.csv
```

### Viewing the results
Once WES has processed a project you can run the REST API (run `web.py` or with
the command `wes-web`) to view the results from WES or you can manually view the
tables in the SQL database.

You will want to make sure the REST api is behind some sort of authenticated
proxy if you are running on an interface other than localhost.


## Docker usage
To simplify installation of WES we have also included a docker container to run
WES. The docker container is currently only configured to run with a CSV. The
container is meant to be a long running service that scans the projects in the
CSV every 24 hours. It also continually runs the REST API so you will have an
API with an up to date listing of all the endpoints in your application.

### Building the image
To use it, first clone the repository. From there you will also have to make a
CSV file describing all the projects you'd like analyzed. It should be named
`projects.csv` and contain the format described above. When that file is created
in the top folder of WES you can run the following command to build the docker
container.
```
docker build -t indeedsecurity/wes .
```

### Running the container
#### Locally
WES was originally created to be used with docker swarm secrets. If you'd like
to run WES with just plain docker you simply have mimic the behavior of Swarm
Secrets by passing your private key into the correct location. This private key
is the one that will be used to allow you to clone all of the projects from the
remote git repository. The key will need to be passed into the following
location within the docker container: `/run/secrets/wes-git-private-key`. You can do
this with the following command:
```
docker run -p 127.0.0.1:5000:5000 -v /path/to/privatekey:/run/secrets/wes-git-private-key --name="wes" indeedsecurity/wes
```
The above command will also expose the port 5000 so that you can access the REST
api. You are now running WES in Docker. Feel free to navigate to
`http://127.0.0.1:5000` to access the REST API.

#### Swarm
First we need to create our secret which is the ssh private key that will be
used to clone all the repositories.
```
openssl rsa -in ~/.ssh/id_rsa | docker secret create wes-git-private-key -
```

After we add the secret we can they create the swarm service and pass in the
secret with the following command:
```
docker service create --name="wes" --secret="wes-git-private-key" --publish 5000:5000 indeedsecurity/wes
```

You are now running WES in Docker Swarm. Feel free to navigate to
`http://<swarm-hostname>:5000` to access the REST API.

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
