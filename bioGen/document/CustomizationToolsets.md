# Customization Toolsets

BioGAIP features a highly extensible architecture that allows advanced users to define custom tools via a unified YAML configuration file. This empowers your AI Agents with specialized capabilities tailored to your specific bioinformatics workflows. 

Custom tools are categorized into two types based on their execution environment: **Local Tools** (executed within the BioAG environment) and **Remote Tools** (executed on the BioWorker backend).

---

## 1. Local Tools (`tools`)

Local tools are executed natively by the BioAG process. They are converted into AutoGen `FunctionTool` objects and can be defined using either inline Python functions or by importing external Python classes.

### Method A: Inline Python Functions
For lightweight utilities, you can write raw Python code directly in your YAML file. BioGAIP parses the code block, extracts the function, and maps the parameter descriptions (`kwargs`).

    tools:
      hello_tool_key:
        name: 'hello_tool'
        description: 'A simple tool that greets the user.'
        kwargs:
          value: 'The name of the user to greet (str).'
        function: |
          def test_tools(value: str) -> str:
              return f"Hello {value}!"

### Method B: Importing Python Classes
For complex logic, you can encapsulate your tool within a Python module and import it dynamically.

    tools:
      advanced_analysis_tool:
        class: 'my_custom_package.modules.AnotherToolClass'
        name: 'AdvancedDataAnalyzer'       # Optional: Overrides the class name
        description: 'Performs deep data analysis.' # Optional: Overrides the class description
        kwargs:
          paramA: 'valueA'                 # Initialization parameters passed to the class
          paramB: 123

> **Note:** If the environment variable `SKIP_CUSTOM_TOOL=True` is set, BioAG will bypass loading all local custom tools.

---

## 2. Remote Tools (`remote_tools`)

Remote tools are custom scripts or commands pushed directly to the **BioWorker** backend via API. They are executed in the secure analysis environment. 

BioGAIP automatically compiles the definitions of these tools into a Markdown manual and injects them into the Agent's system prompt, ensuring the LLM understands how to invoke them.

    remote_tools:
      custom_aligner:
        name: 'Custom RNA Aligner'
        description: 'Aligns RNA sequences using a proprietary algorithm.'
        usage: 'custom_aligner -i <input.fasta> -o <output.bam>'
        kwargs: '-i: Path to input fasta file. -o: Path to output bam file.'
        script: |
          #!/bin/bash
          # This script runs securely on the BioWorker container
          echo "Starting alignment for $1..."

*Behind the scenes: BioAG extracts these scripts and pushes them to the BioWorker via the `/projects/{project_id}/import-tools` API endpoint during session initialization.*

---

## 3. Equipping Agents with Tools

Once your tools are defined in the configuration, you can assign them to specific agents within the `agents` block. 

- Use the `tools` list to assign **Local Tools** (referencing the tool key).
- Set `allow_remote_tools: True` to inject the **Remote Tools** manual into the agent's system message.

    agents:
      analysis_executor_agent:
        model_client: model_client1
        description: 'An agent capable of executing local functions and remote scripts.'
        system_message: |
          You are an executor agent. 
          Use the tools provided to fulfill the user's request.
        tools:
          - hello_tool_key
          - advanced_analysis_tool
        allow_remote_tools: True

By decoupling tool definition from agent logic, BioGAIP allows you to seamlessly mix and match capabilities, building highly specialized AI teams without altering the core codebase.