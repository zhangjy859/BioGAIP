### Run BioAG with Singularity

As our development has progressed, we have removed most of BioAG's Unix-specific dependencies in favor of a more cross-platform implementation. In fact, BioLauncher's Easy Mode now provides excellent usability out of the box.

For users requiring advanced customization or secondary development, we highly recommend using Docker containers for a more robust application environment deployment.

Therefore, we no longer provide dedicated Singularity containerization solutions for BioAG. However, BioAG maintains Singularity compatibility. Users who require this can refer to the Singularity implementation method used for BioWorker.

### Run BioWorker with Singularity

#### 1. Install Singularity (Apptainer)

*Note: The open-source version of Singularity has been rebranded to Apptainer. We recommend using Apptainer as it is actively maintained by the Linux Foundation.*

**Method A: Root Installation (Ubuntu/Debian)**
If you have `sudo` privileges, the easiest way is to install it via the official PPA:

```
    sudo apt update
    sudo apt install -y software-properties-common
    sudo add-apt-repository -y ppa:apptainer/ppa
    sudo apt update
    sudo apt install -y apptainer
```

**Method B: Non-Root Installation (via Conda)**
If you do not have root privileges (which is common on HPC clusters), the most straightforward way is to install it in user space using Conda/Mamba:

```
    conda create -n apptainer-env -c conda-forge apptainer
    conda activate apptainer-env
```

*(Tip: On institutional HPC environments, check if it is already installed by your system administrator by running `module avail singularity` or `module avail apptainer`, and load it using `module load apptainer`.)*

> [!TIP]
>
> Although not recommended, if you wish to integrate Singularity with BioGAIP's built-in GUI, you must ensure that the `singularity` executable is added to your system's PATH environment variable so it can be correctly discovered.
>

#### 2. Download the BioWorker Container Image

- Download the `.tar.gz` package from [this link](http://). This archive is an offline build of the BioWorker Docker container.

- Use the following command to convert it into a Singularity-compatible `.sif` file:

```
    singularity build bioworker.sif docker-archive://<path_to_downloaded_file>.tar.gz
```

- Start the Singularity container using the command below. Note that you must pass a sufficiently strong `API_KEY` as an environment variable.

> If no `API_KEY` is provided, BioWorker will automatically generate one and print it to the terminal.

```
    # Generate a strong 32-character API key
    export API_KEY=$(openssl rand -hex 16)

    # Run the container 
    # (Note: Singularity uses the host network by default. Adjust the --bind paths as needed)
    singularity run \
      --env API_KEY=$API_KEY \
      --env BIOWORKER_PORT=38000 \
      --bind /your/local/workspace:/your/local/workspace \
      bioworker.sif
```