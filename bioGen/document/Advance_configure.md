### Install Docker
Whether you want to run BioAG or BioWorker, for most Linux distributions, we only require Docker to be installed.

If you don't have Docker installed, please refer to the [official Docker installation guide](https://docs.docker.com/engine/install/).

Following is a quick guide for `Ubuntu` users:
```bash
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl status docker
sudo systemctl start docker

sudo docker run hello-world
```

>**[warning] warning**
> 
> For most situations, we dont recommend run docker with superuser or `sudo`, you can add your user to the docker group, so you can run docker commands directly.:
> ```bash
> sudo usermod -aG docker $USER
> ```

.

>**[info] info**
> 
> In some situations, install docker with apt or other package mamanger tool is impossible, because insufficient permissions,
> especially on shared servers or HPC clusters. In this case, you can install docker in your home directory without root permissions, please refer to this [guide](https://docs.docker.com/engine/security/rootless/).

.

>**[warning] info**
> 
> Note: In some network environments, the connection to Docker Hub may have been blocked. This may manifest as network connectivity issues when running `hello-world`. 
> In such cases, you can refer to some third-party articles or projects (we are not affiliated with these projects and cannot guarantee their security).
> 
> eg: 
>  - [https://github.com/DaoCloud/public-image-mirror](https://github.com/DaoCloud/public-image-mirror)
>  - [https://github.com/dongyubin/DockerHub](https://github.com/dongyubin/DockerHub)

## Linux with Singularity (experimental)


>**[warning] warning**
> 
> If you have docker installed, this section can be skipped.
>


If you are using a Linux system where Docker is not available, such as some HPC clusters, you can use `Singularity` (or `Apptainer`) as an **alternative**.


Official Guide: [Unprivileged (non-setuid) Installation](https://docs.sylabs.io/guides/3.5/admin-guide/installation.html#unprivileged-non-setuid-installation)

We also bulid a custom script to help you install Singularity in your home directory without root permissions, please refer to this [script]().

## Windows or macOS
For Windows or macOS users, please install `Docker Desktop` from the [official Docker Desktop installation guide](https://docs.docker.com/desktop/) and 
follow the instructions to complete the installation.

For Windows 10 or 11 users, You can also install `WSL2` (Windows Subsystem for Linux) and then install `Docker` in the WSL2 environment.

Please refer to：

 - [Get started with Docker remote containers on WSL 2](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-containers) 
 - [Installing Docker on WSL 2 with Ubuntu 22.04](https://gist.github.com/dehsilvadeveloper/c3bdf0f4cdcc5c177e2fe9be671820c7)

for more details.

# Quick install BioGAIP
Please note that `BioGAIP` is designed with a `C/S` architecture, which means it includes `BioAG`for connecting to LLM, managing user sessions, importing RAG... and 
send execution command instructions to `BioWorker`. `BioAG` can run on any computer you can access (`local devices`), 
such as your personal computer, workstation, or NAS, while BioWorker needs to run on your server/HPC/cloud computing facilities (`remote devices`) and must be accessible by `BioAG` through the network.


>**[info] info**
> 
> This section actually includes the installation steps for both BioAG and BioWorker, but you only need to choose as needed.
> 

.

>**[info] info**
> 
> BioAG and BioWorker also can be installed at single server if need
> 

.

### docker image 

1. git clone the BioGAIP repository:
```bash
git clone xxx
```
2. Navigate to the BioGAIP docker directory:
```bash
cd BioGAIP/docker
```

3. build BioAG docker image
```bash
docker build -f Dockerfile -t BioAG:lastest .
```
4. build BioWorker docker image
```bash
cd ../BioWorker
docker build -f Dockerfile -t BioWorker:lastest .
```

### Singularity image (experimental)
For Singularity users, you can build the Singularity image from the Docker image directly. Or you can also build the Singularity image from the Singularity definition file in the `BioGAIP/docker` and `BioGAIP/BioWorker` directories.
1. git clone the BioGAIP repository:
```bash
git clone xxx
```

2. copy BioAG Singularity definition file to your working directory:
```bash
cp BioGAIP/BioGAIP/docker/bio_ag/xxx.sif ~/
```
3. copy BioWorker Singularity definition file to your working directory:
```bash
cp BioGAIP/BioGAIP/BioWorker/BioWorker.sif ~/
```

4. Note down the xxx.sif and BioWorker.sif file path, you will need it later.


>**[info] experimental feature**
> 
> BioAG provide a setup wizard to help you configure the initial settings of BioWorker,
> If you're lucky, you only need to install and run BioAG, and make
> sure `docker` or `singularity` installed at remote server, then provide it with the server's SSH connection information, and it will take care of everything through a proxy script.
> 

