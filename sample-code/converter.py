import os
import time
from io import BytesIO

from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.io import DocumentStream
from docling.datamodel.base_models import InputFormat
from docling.pipeline.vlm_pipeline import VlmPipeline


def convert_pdf(filename: str, file_bytes: bytes, ollama_base_url: str) -> str:
    """
    Convert a PDF file to the specified output format.

    Args:
        filename (str): The name of the PDF file.
        file_bytes (bytes): The content of the PDF file in bytes.
        ollama_base_url (str): The base URL of the Ollama API.

    Returns:
        str: The converted content in the specified format.
    """
    model_name = os.getenv("OLLAMA_VLM_MODEL", "granite3.2-vision")
    model_tag = os.getenv("OLLAMA_VLM_MODEL_TAG", "latest")
    full_model_name = f"{model_name}:{model_tag}" if model_tag else model_name

    vlm_options = VlmConvertOptions.from_preset(
        "granite_vision",
        engine_options=ApiVlmEngineOptions(
            engine_type=VlmEngineType.API_OLLAMA,
            url=f"{ollama_base_url}/v1/chat/completions",
            params={"model": full_model_name},
            timeout=600,
        ),
        force_backend_text=True
    )

    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_options,
        enable_remote_services=True,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                pipeline_cls=VlmPipeline,
            )
        }
    )
    source = DocumentStream(name=filename, stream=BytesIO(file_bytes))

    for attempt in range(6):
        try:
            result = converter.convert(source)
            return result.document.export_to_markdown()
        except Exception as exc:
            message = str(exc).lower()
            if attempt == 5 or not any(
                token in message for token in (
                    "connection refused",
                    "connect error",
                    "connect timeout",
                    "timed out",
                    "temporarily unavailable",
                    "connection reset",
                )
            ):
                raise
            time.sleep(2)

    raise RuntimeError("Failed to convert PDF after repeated Ollama connection attempts")