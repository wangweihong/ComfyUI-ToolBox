"""Local GGUF inference through the image's existing llama-cpp-python package."""
from contextlib import contextmanager
import base64
import io
import json
from pathlib import Path
import re
import time

import comfy.model_management as mm
import folder_paths
import numpy as np
from PIL import Image

NO_MMPROJ = "none"
MODEL_FOLDER = "moss_prompt_enhancer_models"
PROMPT_FOLDER = "moss_prompt_enhancer_prompts"
root = Path(folder_paths.models_dir) / "LLM"
folder_paths.folder_names_and_paths[MODEL_FOLDER] = ([str(root)], {".gguf"})
folder_paths.folder_names_and_paths[PROMPT_FOLDER] = (
    [str(root / "prompts"), str(Path(__file__).resolve().parent / "presets")], {".txt"})


def model_options():
    return [n for n in folder_paths.get_filename_list(MODEL_FOLDER)
            if "mmproj" not in Path(n).name.lower()] or ["No GGUF models found"]


def mmproj_options():
    return [NO_MMPROJ] + [n for n in folder_paths.get_filename_list(MODEL_FOLDER)
                          if "mmproj" in Path(n).name.lower()]


def system_prompt_options():
    return ["none"] + [n for n in folder_paths.get_filename_list(PROMPT_FOLDER)
                       if "/" not in n and "\\" not in n]


def full_system_prompt_path(name):
    if name not in system_prompt_options() or name == "none":
        raise ValueError(f"System prompt preset not found: {name}")
    return Path(folder_paths.get_full_path_or_raise(PROMPT_FOLDER, name))


def require_llama_cpp():
    try:
        import llama_cpp
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "MOSS Prompt Enhancer requires a working CUDA llama-cpp-python package. "
            "Reuse the tested wheel from your image; no CLI or LLM Text Processor is needed. "
            "See ComfyUI-ToolBox/docs/moss_prompt_enhancer.md."
        ) from error
    return llama_cpp, Llama, Jinja2ChatFormatter


@contextmanager
def load_model(model, mmproj, image, ctx_size, memory_mode, n_gpu_layers,
               n_cpu_moe_layers, seed, extra_args):
    _, Llama, _ = require_llama_cpp()
    if model not in model_options() or model == "No GGUF models found":
        raise ValueError(f"GGUF model not found: {model}")
    if mmproj not in mmproj_options():
        raise ValueError(f"Vision projector not found: {mmproj}")
    if image is not None and mmproj == NO_MMPROJ:
        raise ValueError("Image input requires a matching mmproj GGUF file.")
    options = json.loads(extra_args) if extra_args.strip() else {}
    allowed = {"n_threads", "n_threads_batch", "n_batch", "n_ubatch", "flash_attn_type", "type_k", "type_v"}
    if not isinstance(options, dict) or options.keys() - allowed:
        raise ValueError(f"extra_args must be a JSON object using only: {', '.join(sorted(allowed))}")
    options.update(model_path=folder_paths.get_full_path_or_raise(MODEL_FOLDER, model),
                   n_ctx=ctx_size, seed=seed if seed >= 0 else 0xFFFFFFFF,
                   n_gpu_layers=n_gpu_layers if memory_mode in {"gpu_layers", "gpu_and_cpu_moe_layers"} else "auto",
                   n_cpu_moe=n_cpu_moe_layers if memory_mode in {"cpu_moe_layers", "gpu_and_cpu_moe_layers"} else 0,
                   no_perf=False, verbose=False)
    if image is not None:
        options["mmproj_path"] = folder_paths.get_full_path_or_raise(MODEL_FOLDER, mmproj)
    # This also invokes the existing llama nodes' registered model-cleanup hooks.
    mm.throw_exception_if_processing_interrupted()
    mm.unload_all_models()
    mm.soft_empty_cache()
    llm = Llama(**options)
    try:
        yield llm
    finally:
        try:
            if image is not None:
                llm.chat_handler.close()
        finally:
            llm.close()


def generate(llm, system, prompt, image, max_tokens, temperature, top_p, top_k,
             repeat_penalty, seed, reasoning, deadline):
    llama_cpp, _, Jinja2ChatFormatter = require_llama_cpp()
    def check():
        mm.throw_exception_if_processing_interrupted()
        if time.monotonic() >= deadline:
            raise TimeoutError("MOSS prompt enhancement exceeded timeout_seconds")

    def abort(_):
        return mm.processing_interrupted() or time.monotonic() >= deadline

    check()
    callback = llama_cpp.ggml_abort_callback(abort)
    llama_cpp.llama_set_abort_callback(llm.ctx, callback, None)
    llama_cpp.llama_perf_context_reset(llm.ctx)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    params = dict(max_tokens=max_tokens, temperature=temperature, top_p=top_p, top_k=top_k,
                  repeat_penalty=repeat_penalty, seed=seed if seed >= 0 else None, stream=True,
                  reasoning_budget=0 if reasoning == "off" else -1)
    stream = None
    chunks = []
    try:
        if image is None:
            template = llm.metadata.get("tokenizer.chat_template")
            if not template:
                raise ValueError("The selected GGUF must contain tokenizer.chat_template")
            def token_text(token):
                return llm.detokenize([token], special=True).decode("utf-8") if token >= 0 else ""
            stops = [t for t in (llm.token_eos(), llm.token_eot()) if t >= 0]
            formatter = Jinja2ChatFormatter(template=template, bos_token=token_text(llm.token_bos()),
                                            eos_token=token_text(llm.token_eos()), stop_token_ids=stops)
            template_args = {} if reasoning == "auto" else {"enable_thinking": reasoning == "on"}
            formatted = formatter(messages=messages, **template_args)
            tokens = llm.tokenize(formatted.prompt.encode("utf-8"), add_bos=not formatted.added_special, special=True)
            stream = llm.create_completion(prompt=tokens, stop=formatted.stop,
                                            stopping_criteria=formatted.stopping_criteria, **params)
        else:
            content = [{"type": "text", "text": prompt}]
            for tensor in image:
                array = (tensor.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                buffer = io.BytesIO()
                Image.fromarray(array).save(buffer, format="PNG")
                url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": url}})
            messages[1]["content"] = content
            stream = llm.create_chat_completion(messages=messages, **params)
        for chunk in stream:
            check()
            choice = chunk["choices"][0]
            chunks.append(choice.get("text", choice.get("delta", {}).get("content", "")) or "")
        check()
        perf = llama_cpp.llama_perf_context(llm.ctx)
        prompt_rate = 1000 * perf.n_p_eval / perf.t_p_eval_ms if perf.t_p_eval_ms else 0
        generation_rate = 1000 * perf.n_eval / perf.t_eval_ms if perf.t_eval_ms else 0
        metrics = (f"llama-cpp-python {llama_cpp.__version__} | "
                   f"Prompt: {prompt_rate:.1f} t/s | Generation: {generation_rate:.1f} t/s | "
                   f"prompt_tokens={perf.n_p_eval}, generated_tokens={perf.n_eval}")
        raw = "".join(chunks).strip()
        thinking = re.findall(r"<think>(.*?)</think>", raw, flags=re.DOTALL)
        response = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return response, "\n".join(thinking).strip(), metrics
    except Exception:
        check()
        raise
    finally:
        if stream is not None:
            stream.close()
        # The ctypes callback must stay alive until native decoding has stopped.
        llama_cpp.llama_set_abort_callback(llm.ctx, llama_cpp.ggml_abort_callback(), None)
