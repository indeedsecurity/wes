#!/usr/bin/env bash
cp /run/secrets/wes_priv_key ${HOME}/.ssh/id_rsa
chmod 400 ${HOME}/.ssh/id_rsa

supervisord --nodaemon
