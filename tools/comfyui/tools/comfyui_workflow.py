import json
import mimetypes
from typing import Any, Generator
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
import httpx
from tools.comfyui_client import ComfyUiClient, FileType
from dify_plugin import Tool


def sanitize_json_string(s):
    escape_dict = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\x08": "\\b", "\x0c": "\\f"}
    for char, escaped in escape_dict.items():
        s = s.replace(char, escaped)
    return s


class ComfyUIWorkflowTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        comfyui = ComfyUiClient(self.runtime.credentials["base_url"])
        positive_prompt = tool_parameters.get("positive_prompt", "")
        negative_prompt = tool_parameters.get("negative_prompt", "")
        images = tool_parameters.get("images") or []
        workflow = tool_parameters.get("workflow_json")
        image_names = []
        for image in images:
            if image.type != FileType.IMAGE:
                continue
            files = {
                "image": (image.filename, image.blob, image.mime_type),
                "overwrite": "true",
            }
            res = httpx.post(str(comfyui.base_url / "upload/image"), files=files)
            image_name = res.json().get("name")
            image_names.append(image_name)
        set_prompt_with_ksampler = True
        if "{{positive_prompt}}" in workflow:
            set_prompt_with_ksampler = False
            workflow = workflow.replace(
                "{{positive_prompt}}", positive_prompt.replace('"', "'")
            )
            workflow = workflow.replace(
                "{{negative_prompt}}", negative_prompt.replace('"', "'")
            )
        try:
            prompt = json.loads(workflow)
        except json.JSONDecodeError:
            cleaned_string = sanitize_json_string(workflow)
            try:
                prompt = json.loads(cleaned_string)
            except Exception:
                yield self.create_text_message("the Workflow JSON is not correct")
        if set_prompt_with_ksampler:
            try:
                prompt = comfyui.set_prompt_by_ksampler(
                    prompt, positive_prompt, negative_prompt
                )
            except Exception:
                pass
        if image_names:
            if image_ids := tool_parameters.get("image_ids"):
                image_ids = image_ids.split(",")
                try:
                    prompt = comfyui.set_prompt_images_by_ids(
                        prompt, image_names, image_ids
                    )
                except Exception:
                    raise ToolProviderCredentialValidationError(
                        "the Image Node ID List not match your upload image files."
                    )
            else:
                prompt = comfyui.set_prompt_images_by_default(prompt, image_names)
        if seed_id := tool_parameters.get("seed_id"):
            prompt = comfyui.set_prompt_seed_by_id(prompt, seed_id)
        images = comfyui.generate_image_by_prompt(prompt)
        for img in images:
            yield self.create_blob_message(
                blob=img["data"],
                meta={
                    "filename": img["filename"],
                    "mime_type": mimetypes.guess_type(img["filename"], strict=False)[0] or "application/octet-stream",
                    "extension": img["filename"].split(".")[-1],
                },
            )
            yield self.create_json_message({"filename": img["filename"], "url": img["url"]})
