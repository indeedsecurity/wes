# WES - Wintermute Endpoint Search

This project is a source code analysis project that will loop through a
repo and attempt to find most of the endpoints and parameters for the project.

To install the project you will want to do the following:

```
pip install git+ssh://git@github.com/indeedsecurity/wes.git
```

WES supports a few methods of running from the command line. You have the option
of supplying a git repository address (eg. git@github.com:owner/project.git) or
a folder which contains the source code. There's also a third option if you'd
like to process multiple projects by supplying a CSV file containing the git
repositories for each project. Below you'll see the required format for this csv
file.

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

You can also run WES on individual projects with the following commands:

folder
```
wes -f myProjectFolder -u http://myProjectsBaseUrl.com
```

git repo
```
wes -g git@github.com:owner/project.git -u http://myProjectsBaseUrl.com
```

Once WES has processed a project you can run the REST API (run `web.py` or with
the command `wes-web`) to view the results from WES or you can manually view the
tables in the SQL database.

You will want to make sure the REST api are behind some sort of authenticated
proxy if you are running on an interface other than localhost.


## Docker Usage
To simplify installation of WES we have also included a docker container to run
WES. The docker container is currently only configured to run with a CSV. The
container is meant to be a long running service that scans the projects in the
CSV every 24 hours. It also continually runs the REST API so you will have an
API with continually up to date listing of all the endpoints in your
application.

### Building the image
To use it, first clone the repository. From there you will also have to make a
CSV file describing all the projects you'd like analyzed. It should be named
`projects.csv` and contain the format described above. When that file is created
in the top folder of WES you can run the following command to build the docker
container.
```
docker build -t security/wes .
```

### Running the container
#### Locally
To run this container you will have to make your system into a single node
swarm because the secrets management only works with docker swarm. So to make
your system a single node swarm just issue the following command:
```
docker swarm init
```
Now just follow the instructions to run the container in a swarm below.

#### Swarm
First we need to create our secret which is the ssh private key that will be
used to clone all the repositories.
```
openssl rsa -in ~/.ssh/id_rsa | docker secret create wes_priv_key -
```

Next we create the service with the following command.
```
docker service create --name="wes" --secret="wes_priv_key" security/wes
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
