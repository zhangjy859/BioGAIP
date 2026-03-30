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

chown $MAMBA_USER:$MAMBA_USER /opt && \
  mkdir -p /runtime/conda && \
  chown $MAMBA_USER:$MAMBA_USER -R /runtime/conda && \
  if [ ! -f /runtime/conda/_PASS ] || [ ! -f /cache/chroma/_PASS ]; then
    chown $MAMBA_USER:$MAMBA_USER -R /cache /runtime && \
    chmod a+rwx -R /cache /runtime
    chown $MAMBA_USER:$MAMBA_USER -R /home/mambauser/
    chmod a+rwx -R /home/mambauser/
    echo "extra source data"
      echo extra source data to dir, its may take a while.
      cd /runtime && \
      touch /runtime/conda/_PASS && \
      cd -
      gosu $MAMBA_USER mkdir -p /cache/chroma/onnx_models/all-MiniLM-L6-v2 && \
                cd /cache/chroma/onnx_models/all-MiniLM-L6-v2
                tar zxvf /app/onnx.tar.gz && \
		touch /cache/chroma/_PASS
                cd -
  fi && \
  echo install playwright dependencies, its may take few minutes && \
  export PLAYWRIGHT_BROWSERS_PATH=/runtime/playwright-browsers
  gosu $MAMBA_USER mkdir -p $PLAYWRIGHT_BROWSERS_PATH
  if [ ! -d $PLAYWRIGHT_BROWSERS_PATH/webkit-* ]; then 
      gosu $MAMBA_USER micromamba run -n base playwright install chromium 2> /dev/null && \
      chown -R $MAMBA_USER:$MAMBA_USER $PLAYWRIGHT_BROWSERS_PATH && \
      chmod -R a+rwx $PLAYWRIGHT_BROWSERS_PATH
  fi && \
  echo start app webui && \
  chown $MAMBA_USER:$MAMBA_USER -R /app
  echo "" > /app/__init__.py && \
	  cd /app/ && \
	  gosu $MAMBA_USER micromamba run -n base /app/start.sh $@
