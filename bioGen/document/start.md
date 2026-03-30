# Start

Once you have completed the above preparations, you can start bioGen.

## bioWorker
First, start the bioWorker server. If you are using Docker, you can run the following command:

```bash
## All paths need to use absolute paths and should be accessible on the machine where bioWorker is running.
docker run -d --name bioworker -p 38000:38000 \
  -e API_KEY=your_api_key \
  -v /path/to/input/data:/path/to/input/data:ro \
  -v /path/to/output/data:/path/to/output/data:rw \
  -v /path/to/work/dir:/data/work_dir:rw \
  bioworker:lastest
```
The important parameters are:
 - API_KEY: The API key for accessing the bioWorker server. 
    **Please note down this key, as you will need it when starting bioAG.**
 - /path/to/input/data: The path to the input data directory on the remote machine. we set it to read-only mode by `ro`.
 - /path/to/output/data: The path to the output data directory on the remote machine. we set it to read-write mode by `rw`.
 - /path/to/work/dir: The path to the working directory on the remote machine. bioWorker will use this directory to store temporary files during task execution. we set it to read-write mode by `rw`.

If you have more files for bioWorker to access, add them in the format above `(-v xxx:xxx:ro or, -v xxx:xxx:rw)`.

**Granting only the minimal folder permissions needed for the task. For sensitive data, 
strongly isolate input and output folders (e.g., use an empty output folder) and back up.**

>**[warning] !!!important warning!!!**
> 
> It is crucial to keep your API_KEY strong and unguessable!!! We recommend using a password generator to create a key of no less than 128 bits.
> for example [1password](https://1password.com/password-generator/)
>

.

>**[info] info**
> 
> If you don't want to manually complete the bioGen configuration, bioAG can also automatically complete the configuration (experimental feature) when SSH access is provided.
> 

## bioAG
he configuration of bioAG can be somewhat complex. 
Before starting, please ensure you have prepared the following information:
 - the configue file `system.yaml` (see [configure](configure.md) for details)
 - the IP and API_KEY for accessing bioWorker (the one you set when starting bioWorker) `or`
 - SSH access to the remote machine where bioWorker will run (experimental feature)

### Start bioAG without settings wizard
If you have already configured the `system.yaml` file, you can start bioAG with the following command:

```bash
docker run -d --name bioag -p 5801:5801 \
    -e API_URL=your_bioworker_server_ip:38000 \
    -e API_KEY=your_bioworker_api_key \
    -v /path/to/your/config/system.yaml:/config/system.yaml:ro \
    bioag:lastest streamlit
```

bioAG supports using `Streamlit`/`Chainlit` as the front-end for user interaction. 
If you want to use Chainlit as the front-end, please replace "`streamlit`" in the above command with "`chainlit`".

### Start bioAG with settings wizard (experimental feature)
If you have not configured the `bioWorker`, you can let `bioAG` help you, just need remove
two environment variables `API_URL` and `API_KEY` in the above command, start `bioAG` with
streamlit front-end as follows:

```bash
docker run -d --name bioag -p 5801:5801 \
    -v /path/to/your/config/system.yaml:/config/system.yaml:ro \
    bioag:lastest streamlit
```
Then open the web page `http://your_bioag_server_ip:5801` in your browser, and follow the instructions on the page to complete the configuration.

### Configure user name and password
By default, `bioAG` does set a username and password for login as 
    - user_name: `admin`
    - password: `admin`
You can change them by add a environment variable `APP_USER` in the above command, for example:
```bash
docker run -d --name bioag -p 5801:5801 \
    -e APP_USER=user_name:password \
    -e API_URL=your_bioworker_server_ip:38000 \
    -e API_KEY=your_bioworker_api_key \
    -v /path/to/your/config/system.yaml:/config/system.yaml:ro \
    bioag:lastest streamlit
```

>**[warning] limitation**
> 
> Chainlit is a feature under development, and some functionalities (such as file uploads) have not yet been implemented.
> Currently, for the Chainlit front-end, the username setting is not functional.
>

### Commandline interface
If you prefer to use the command line interface, you can start bioAG with the following command:
```bash
docker run -it --rm \
    -e API_URL=your_bioworker_server_ip:38000 \
    -e API_KEY=your_bioworker_api_key \
    -v /path/to/your/config/system.yaml:/config/system.yaml:ro \
    bioag:lastest
```

### External RAG
If you want to use external RAG (Retrieval-Augmented Generation) capabilities, you need to set up a vector database and document embedding service.
 - CONDA_META_DATABASE: The path to the conda chromadb database file. we have a script to help you create this file.
 - WORKFLOW_DATABASE: The path to the workflow chromadb database file. we have a script to help you create this file.
 - USER_EXT_DATABASE: The path to the user external documents, support multiple files types such as pdf, txt, md, etc. You can place your own documents in this database to enhance the model's knowledge base.

example:
```bash
docker run -d --name bioag -p 5801:5801 \
    -e API_URL=your_bioworker_server_ip:38000 \
    -e API_KEY=your_bioworker_api_key \
    -e CONDA_META_DATABASE=/data/conda_meta_db/chroma-embeddings \
    -e WORKFLOW_DATABASE=/data/workflow_db/chroma-embeddings \
    -e USER_EXT_DATABASE=/data/user_ext_db/chroma-embeddings \
    -v /path/to/your/config/system.yaml:/config/system.yaml:ro \
    -v /path/to/your/conda_meta_db:/data/conda_meta \
    -v /path/to/your/workflow_db:/data/workflow_db \
    -v /path/to/your/user_ext_db:/data/user_ext_db \
    bioag:lastest streamlit
```

### Stop bioAG and bioWorker
You can stop the running containers with the following commands:
```bash
docker stop bioag
docker stop bioworker
```

You can remove the containers with the following commands:
```bash
docker rm bioag
docker rm bioworker
```
