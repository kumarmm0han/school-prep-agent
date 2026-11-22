import os

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from converter import convert_pdf

app = FastAPI(title="Docling Serve", description="A service for processing documents and interacting with Ollama models.")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama-server:11434")
DOCLING_URL = os.getenv("DOCLING_URL", "http://docling-serve:5001")

@app.get("/health")
def health():
    """Check the health of the service."""
    return {"status": "ok"}

@app.post("/convert")
async def convert(
    file: UploadFile = File(...), 
    format: str = Query(default="json",enum=["json", "markdown"]),
    do_picture_description: bool = Query(default=False)
):

    """Convert a PDF file to the specified output format."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()

    data = {
        "to_format": format,
        "force_ocr": "true",
        "do_table_structure": "true",
        "include_images": "true",
        "pipeline": "standard",
        "do_picture_description":"true"
    }
    if do_picture_description:
        data["do_picture_description"] = do_picture_description
        data["picture_description_api"] = (
            '{"url": "' + OLLAMA_URL + '/v1/chat/completions", "params": {"model": "granite3.2-vision"},"timeout": 120,"prompt": "Provide a detailed description of the image."}'
        )

    async with httpx.AsyncClient(timeout=2700) as client:
        response = await client.post(
            DOCLING_URL + "/v1/convert/file",
            files={"files": (file.filename, file_bytes, "application/pdf")},
            data=data,
        )

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        result = response.json()
        md_content = result.get("document", {}).get("md_content", "")
        if format == "markdown":
            return PlainTextResponse(content=md_content, media_type="text/markdown")

    return {"filename": file.filename, "result": result}


@app.post("/convert/vlm")
async def convertVlm(
    file: UploadFile = File(...), 
    format: str = Query(default="json",enum=["json", "markdown"])
):

    """Convert a PDF file to the specified output format."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()

    try:
        converted_content = convert_pdf(file.filename, file_bytes, OLLAMA_URL)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


    if format == "markdown":
        return PlainTextResponse(content=converted_content, media_type="text/markdown")

    return {"filename": file.filename, "result": converted_content}