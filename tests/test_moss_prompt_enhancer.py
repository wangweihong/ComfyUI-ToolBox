"""CPU tests for registration, compiler compatibility and GGUF lifetime boundaries."""
import builtins
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class MossPromptEnhancer(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.models = Path(temp.name)
        (self.models/'LLM').mkdir()
        (self.models/'LLM/model.gguf').touch()
        self.calls = []
        self.interrupted = False

        class Interrupted(Exception):
            pass

        self.Interrupted = Interrupted

        def check_interrupt():
            if self.interrupted:
                raise Interrupted()

        management = types.ModuleType('comfy.model_management')
        management.throw_exception_if_processing_interrupted = check_interrupt
        management.processing_interrupted = lambda: self.interrupted
        management.unload_all_models = lambda: self.calls.append('unload')
        management.soft_empty_cache = lambda: self.calls.append('empty_cache')
        comfy = types.ModuleType('comfy'); comfy.model_management = management
        folders = types.ModuleType('folder_paths')
        folders.models_dir = str(self.models)
        folders.folder_names_and_paths = {}
        folders.get_filename_list = lambda key: ['model.gguf'] if key.endswith('_models') else []
        folders.get_full_path_or_raise = lambda key, name: str(self.models/'LLM'/name)
        pil = types.ModuleType('PIL'); pil.Image = types.SimpleNamespace()
        self.modules = {'comfy': comfy, 'comfy.model_management': management, 'folder_paths': folders,
                        'numpy': types.ModuleType('numpy'), 'PIL': pil}
        module_patch = patch.dict(sys.modules, self.modules)
        module_patch.start(); self.addCleanup(module_patch.stop)
        original_import = builtins.__import__
        self.llama_imports = []

        def without_llama(name, *args, **kwargs):
            if name == 'llama_cpp' or name.startswith('llama_cpp.'):
                self.llama_imports.append(name)
                raise ModuleNotFoundError('llama_cpp deliberately unavailable')
            return original_import(name, *args, **kwargs)

        import_patch = patch('builtins.__import__', side_effect=without_llama)
        import_patch.start(); self.addCleanup(import_patch.stop)
        package = ROOT/'nodes/moss_prompt_enhancer'
        spec = importlib.util.spec_from_file_location('toolbox_moss_test', package/'__init__.py',
                                                      submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(lambda: [sys.modules.pop(k, None) for k in list(sys.modules)
                                if k == spec.name or k.startswith(spec.name+'.')])
        spec.loader.exec_module(module)
        self.module = module
        self.nodes = sys.modules[spec.name+'.nodes']
        self.backend = sys.modules[spec.name+'.python_backend']
        self.node = module.NODE_CLASS_MAPPINGS['MOSSPromptEnhancer']()

    def params(self):
        return dict(model='model.gguf', mmproj='none', system_prompt='none', prompt='A red cube.',
                    max_tokens=1024, temperature=.3, top_p=.9, top_k=40, repeat_penalty=1.05,
                    ctx_size=4096, memory_mode='gpu_layers', n_gpu_layers=99, n_cpu_moe_layers=1,
                    seed=1, timeout_seconds=300, reasoning='off', width=512, height=256,
                    output_mode='Caption', retry_invalid_json=True, extra_args='')

    def test_registers_legacy_type_without_importing_optional_llama(self):
        self.assertEqual(self.llama_imports, [])
        self.assertEqual(set(self.module.NODE_CLASS_MAPPINGS), {'MOSSPromptEnhancer'})
        self.assertEqual(self.node.CATEGORY, 'ToolBox/MOSS')
        self.assertEqual(self.module.NODE_DISPLAY_NAME_MAPPINGS['MOSSPromptEnhancer'], 'tb-moss-prompt-enhancer')
        for language in ['en', 'zh']:
            locale = json.loads((ROOT/'locales'/language/'nodeDefs.json').read_text())
            self.assertEqual(locale['MOSSPromptEnhancer']['display_name'], 'tb-moss-prompt-enhancer')
        schema = self.node.INPUT_TYPES()
        self.assertEqual(list(schema['required']), [
            'model', 'mmproj', 'system_prompt', 'prompt', 'max_tokens', 'temperature', 'top_p',
            'top_k', 'repeat_penalty', 'ctx_size', 'memory_mode', 'n_gpu_layers', 'n_cpu_moe_layers',
            'seed', 'timeout_seconds', 'reasoning', 'width', 'height', 'output_mode', 'retry_invalid_json'])
        self.assertEqual(list(schema['optional']), ['image', 'enable_processing', 'extra_args'])
        self.assertEqual(self.node.RETURN_NAMES, ('RESPONSE', 'DRAFT_JSON', 'REASONING', 'PERF', 'WIDTH', 'HEIGHT'))
        self.assertEqual(self.node.RETURN_TYPES, ('STRING', 'STRING', 'STRING', 'STRING', 'INT', 'INT'))
        self.assertEqual(self.llama_imports, [])

    def test_missing_library_fails_only_at_execution_before_model_unload(self):
        with self.assertRaisesRegex(RuntimeError, 'working CUDA llama-cpp-python.*docs/moss_prompt_enhancer'):
            self.node.enhance(**self.params())
        self.assertEqual(self.calls, [])
        self.assertTrue(self.llama_imports)

    def test_bypass_does_not_require_optional_library(self):
        result = self.node.enhance(**dict(self.params(), enable_processing=False))
        self.assertEqual(result, ('A red cube.', '', '', '', 512, 256))
        self.assertEqual(self.llama_imports, [])

    def test_compiler_and_strict_json_extraction(self):
        self.assertEqual(self.nodes.compile_prompt({'caption': 'A red cube.'}), 'A red cube.')
        draft = dict(width=512, height=256, bbox_coord_space='abs', bbox_format='xyxy',
                     summary={'caption': 'A red cube.'},
                     items=[{'label': 'object', 'caption': 'Red cube', 'bbox': [10, 20, 110, 120]}])
        compiled = json.loads(self.nodes.compile_prompt(draft))
        self.assertEqual(compiled['items'][0]['bbox'], [-108, -246, -8, -146])
        self.assertEqual(compiled['bbox_coord_space'], 'abs_centralized')
        self.assertEqual(compiled['bbox_format'], 'yxyx')
        draft['items'][0]['bbox'][2] = 513
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.nodes.compile_prompt(draft)
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            self.node._extract_json('{"caption":"a","caption":"b"}')

    def test_invalid_json_retry_uses_one_context_and_closes_it(self):
        events = []

        @contextmanager
        def model(*args):
            events.append('load')
            try:
                yield object()
            finally:
                events.append('close')

        with patch.object(self.nodes, 'load_model', model), patch.object(
                self.nodes, 'generate', side_effect=[('invalid', '', ''), ('{"caption":"A red cube."}', '', 'perf')]) as generate:
            result = self.node.enhance(**self.params())
        self.assertEqual(result[0], 'A red cube.')
        self.assertEqual(events, ['load', 'close'])
        self.assertEqual(generate.call_count, 2)
        self.assertIn('previous attempt generated invalid JSON', generate.call_args.args[2])

    def test_model_closes_on_generation_error_and_interrupt(self):
        owner = self

        class Model:
            def __init__(self, **kwargs):
                owner.calls.append('load')
            def close(self):
                owner.calls.append('close')

        with patch.object(self.backend, 'require_llama_cpp', return_value=(None, Model, None)):
            with self.assertRaisesRegex(RuntimeError, 'generation failed'):
                with self.backend.load_model('model.gguf', 'none', None, 4096, 'gpu_layers', 99, 1, 1, ''):
                    raise RuntimeError('generation failed')
            self.assertEqual(self.calls[-1], 'close')
            self.interrupted = True
            count = self.calls.count('load')
            with self.assertRaises(self.Interrupted):
                with self.backend.load_model('model.gguf', 'none', None, 4096, 'gpu_layers', 99, 1, 1, ''):
                    self.fail('Should not load while interrupted')
            self.assertEqual(self.calls.count('load'), count)

    def test_examples_keep_type_and_contain_no_machine_paths(self):
        workflows = list((ROOT/'examples/moss_prompt_enhancer').glob('*.json'))
        self.assertEqual(len(workflows), 5)
        for file in workflows:
            text = file.read_text()
            self.assertNotRegex(text, r'/home/|/media/|/tmp/comfyui-')
            graph = json.loads(text)
            node = next(n for n in graph['nodes'] if n['type'] == 'MOSSPromptEnhancer')
            self.assertEqual(node['widgets_values_named']['extra_args'], '')

    def test_expired_generation_deadline_closes_context(self):
        closed = []

        class Model:
            def __init__(self, **kwargs):
                pass
            def close(self):
                closed.append(True)

        with patch.object(self.backend, 'require_llama_cpp', return_value=(None, Model, None)):
            with self.assertRaises(TimeoutError):
                with self.backend.load_model('model.gguf', 'none', None, 4096, 'gpu_layers', 99, 1, 1, '') as model:
                    self.backend.generate(model, 'system', 'prompt', None, 128, .3, .9, 40, 1.05,
                                          1, 'off', time.monotonic()-1)
        self.assertEqual(closed, [True])

    def test_docs_link_to_existing_files(self):
        for file in [ROOT/'docs/moss_prompt_enhancer.md', ROOT/'examples/moss_prompt_enhancer/README.md',
                     ROOT/'nodes/moss_prompt_enhancer/UPSTREAM.md']:
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', file.read_text()):
                target = target.split('#')[0]
                if target and '://' not in target:
                    self.assertTrue((file.parent/target).exists(), f'{file}: {target}')


if __name__ == '__main__':
    unittest.main()
