# WES - Wintermute Endpoint Search

This project is a source code analysis project that will loop through a
repo and attempt to find most of the endpoints and parameters for the project.

To install the project you will want to do the following:
```
virtualenv -p python3 venv
source venv/bin/activate
pip install -r requirements.txt
```

To run the system you simply issue the following command to run through all the
projects:
```
python wes/main.py -rcsv <path to projects.csv>
```
This populates the tinydb json file called endpoints.json. You could then browse
this file like any other json but that's annoying and that's why there's a
REST api and web interface.

To run the web interface and REST api you want to simply run the following
command:
```
python wes/web.py
```
You will want to make sure the web interface and REST api are behind some sort
of authenticated proxy.


## Docker Usage
### Building the image
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

Within our swarm you will also want to add the following args:
```
--constraint 'node.labels.type == bigstorage'
--mount 'type=bind,src=/dockerstorage/wes,dest=usr/src/app/workingDir'
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
