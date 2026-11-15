## RAG  pipeline to convert the PDF books by chapters to Markdown

- Develop a pipeline to convert the pdf book chapters available under the books folder to markdown files using docling . Docling serve api is running in a docker container - ` http://localhost:5001`. 

- `converter.py` file contains a sample code which invokes the docling serve endpoint with fixed arguments. Additionally this code provides configuration to invoke VLM running in local ollama `http://host.docker.internal:11434` to describe the images available in the the pdf. 

- `convertVlm` method available in the main.py api also additionally converts the response to `"text/markdown"` response type. This additional steps helps to save the file in .md file without any encoding. 

- `convert` method availablei n the main.py api utilizes the docling serve end point to convert pdf. This endpoint supports additional parameters needed to convert the scanned PDFs such as do_ocr, vlm pipeline etc. This method is goog enough for most of the scenarios. I have not used `converter.py` much. 

- These markdowns will be used as a knowledge base for futher LLM based application. These will help create students and instructor specific agentic workflows as a next steps. This part of the design can be elaborated later as a 2nd step. 

- But the design for building the knowledge graph needs to be fully completed. 

- to start with this can be a locally executable OpenCode based harness. Any additional simplified design can be explored. 

- Current setup is DGX-Spark running Qwen3.8 27B model. This entire execution is running in same hardware. This pipeline can run in docker containers. I prefer docker-compose for orchestration. 
