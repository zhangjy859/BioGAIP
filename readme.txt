## install gitbook
npm uninstall gitbook-cli -g
nvm install 10
nvm use 10
npm install gitbook-cli -g

see more dissusion: [https://stackoverflow.com/a/75249778/20240835](https://stackoverflow.com/a/75249778/20240835)

## build gitbook
nvm use 10

gitbook build

gitbook serve

use npx honkit serve instead of gitbook serve if you have honkit installed