#!/usr/bin/env bash
cp /run/secrets/wes-git-private-key /home/wes/.ssh/id_rsa
chmod 400 /home/wes/.ssh/id_rsa
chown wes /home/wes/.ssh/id_rsa
chown -R wes:wes /usr/src/app

supervisord --nodaemon
