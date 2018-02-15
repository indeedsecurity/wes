FROM alpine:3.4
MAINTAINER Caleb Coffie "calebc@indeed.com"

# Install needed packages
RUN apk add --no-cache python3-dev python3 supervisor wget curl bash libxml2 \
  libxml2-dev libxslt libxslt-dev gcc g++ git openssh postgresql-dev libcap

# Set timezone. This is required for correct timestamps
RUN apk add --update --no-cache tzdata ca-certificates && update-ca-certificates
ARG TZ=UTC
ENV TZ ${TZ}
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Add wes user
RUN adduser -D -u 2323 wes

# Set working directory
RUN mkdir -p /usr/src/app && chown wes /usr/src/app
WORKDIR /usr/src/app

# Change to wes user
USER wes

# Copy over supervisord config
COPY supervisord.conf /etc/supervisord.conf

# Install python requirements
COPY requirements.txt /usr/src/app/
USER root
RUN pip3 install --no-cache-dir -r requirements.txt

# Add capibility to Python to open privileged ports
RUN setcap cap_net_raw+ep `realpath $(which supervisord)`
USER wes

# Copy over the project files to working dir
COPY wes /usr/src/app/wes
COPY projects.csv /usr/src/app
COPY entrypoint.sh /

# Set environment variable so python output is unbuffered for supervisord
ENV PYTHONUNBUFFERED 1
RUN touch /tmp/supervisor.sock && chmod 755 /tmp/supervisor.sock

# Add cron job
COPY cron /usr/src/app
USER root
RUN crontab /usr/src/app/cron
USER wes

# Grab ssh pub key from gitlab server
RUN mkdir -p ${HOME}/.ssh && touch ${HOME}/.ssh/known_hosts && ssh-keyscan -H github.com >> ${HOME}/.ssh/known_hosts

EXPOSE 80

# Start supervisor
ENTRYPOINT ["/entrypoint.sh"]
