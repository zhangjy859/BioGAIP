#!/bin/bash
set -euo pipefail

TEST_URL="http://detectportal.firefox.com/success.txt"

if [ -n "${http_proxy-}" ]; then
    echo "checking http proxy: $http_proxy"
    response=$(curl -s -o /dev/null -w "%{http_code}" -x "$http_proxy" "$TEST_URL")
    if [ "$response" -eq 200 ]; then
        echo "HTTP Proxy Ok"
    else
        echo "HTTP Proxy invalid: $response"
        exit 1
    fi
else
    echo "http_proxy not set"
fi

if [ -n "${https_proxy-}" ]; then
    echo "checking https proxy: $https_proxy"
    response=$(curl -s -o /dev/null -w "%{http_code}" -x "$https_proxy" "$TEST_URL")
    if [ "$response" -eq 200 ]; then
        echo "HTTPS Proxy Ok"
    else
        echo "HTTPS proxy invalid: $response"
        exit 1
    fi
else
    echo "https_proxy not set"
fi

#echo $(ll -h /var/lib/postgresql/14)

service postgresql start && \
  echo install playwright dependencies, its may take few minutes && \
  if [ ! -d /cache/ms-playwright/webkit-* ]; then 
      micromamba run -n base playwright install > /dev/null 2>&1 && \
      cp -r /root/.cache/ms-playwright /cache/ && \
      chown -R $MAMBA_USER:$MAMBA_USER /cache/ms-playwright && \
      chmod -R a+rw /cache/ms-playwright 
  fi && \
  echo start app webui && \
  gosu $MAMBA_USER /app/start.sh $@
