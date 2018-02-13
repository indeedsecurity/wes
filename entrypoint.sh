#!/usr/bin/env bash
cp /run/secrets/wes-git-private-key ${HOME}/.ssh/id_rsa
chmod 400 ${HOME}/.ssh/id_rsa

supervisord --nodaemon
