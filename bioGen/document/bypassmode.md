### Bypass Mode

BioGAIP is written in Python with a minimal amount of Shell scripting. Therefore, in theory, it can run without any containerization technology — especially when operating in Client/Server (C/S) mode, where the user-side component (**BioAG**) may consider the virtualization overhead of containers to be excessively resource-intensive.

To solve this problem, we provide a non-containerized execution mode called **Bypass mode**. In this mode:

- **BioLauncher** uses **micromamba** to build the execution environment locally.
- **BioLauncher** runs **BioAG** directly in the local environment.
- No containerization or virtualization technology is required.

**⚠️ Experimental Feature**  
This capability is currently **experimental** and may exhibit the following limitations and issues:

 - Supported **only on Windows**.
 - Due to an unresolved compatibility issue with the `tqdm` library, **all RAG features are disabled**.
 - Team management and refresh mechanisms may behave unpredictably.
 - Frontend session message rendering may be abnormal (cause unknown).

### Enabling Bypass Mode

To activate Bypass mode, follow these steps during the first stage of **BioLauncher**:

1. Expand the **Advanced Options** collapsible section.
2. Check the **Use bypass mode** checkbox.
3. If your network has poor connectivity to Conda mirrors, enable **Use mirror for conda**.
4. Wait a few seconds — the page will automatically check whether a local Conda environment is ready.  
   If it is not ready, follow the on-screen wizard to set it up.
5. When the page shows that the Conda environment is ready, click **Next**.
6. Continue with the rest of the BioLauncher configuration as usual.