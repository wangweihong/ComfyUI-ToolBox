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
        self.assertEqual(len(workflows), 6)
        for file in workflows:
            text = file.read_text()
            self.assertNotRegex(text, r'/home/|/media/|/tmp/comfyui-')
            graph = json.loads(text)
            node = next(n for n in graph['nodes'] if n['type'] == 'MOSSPromptEnhancer')
            self.assertEqual(node['widgets_values_named']['extra_args'], '')

    def test_bundled_reverse_preset_is_registered_after_user_presets(self):
        paths, extensions = self.backend.folder_paths.folder_names_and_paths[self.backend.PROMPT_FOLDER]
        self.assertEqual(paths[0], str(self.models/'LLM/prompts'))
        preset = Path(paths[1])/'image_prompt_reverse_zh.txt'
        self.assertTrue(preset.is_file())
        self.assertEqual(extensions, {'.txt'})
        with patch.object(self.backend.folder_paths, 'get_filename_list', return_value=[preset.name]), \
                patch.object(self.backend.folder_paths, 'get_full_path_or_raise', return_value=str(preset)):
            self.assertIn(preset.name, self.backend.system_prompt_options())
            self.assertEqual(self.backend.full_system_prompt_path(preset.name), preset)
        text = preset.read_text()
        self.assertIn('<|分区名称|>', text)
        self.assertIn('<|/分区名称|>', text)
        self.assertIn('{"sections":[', text)

    def test_reference_workflow_connects_image_projector_and_automatic_size(self):
        p = ROOT/'examples/moss_prompt_enhancer/api/06_参考图_llama-cpp中文分块反推_MOSS_Turbo8步.json'
        graph = json.loads(p.read_text())
        enhancer = graph['30']['inputs']
        self.assertEqual(enhancer['image'], ['41', 0])
        self.assertEqual(enhancer['width'], ['42', 0])
        self.assertEqual(enhancer['height'], ['42', 1])
        self.assertNotEqual(enhancer['mmproj'], 'none')
        self.assertEqual(enhancer['system_prompt'], 'image_prompt_reverse_zh.txt')
        self.assertEqual(enhancer['output_mode'], 'Tagged Caption')
        self.assertEqual(graph['4']['inputs']['text'], ['30', 0])
        self.assertEqual(graph['41']['inputs']['resolution_steps'], 16)

    def test_image_without_projector_fails_before_unloading_models(self):
        with patch.object(self.backend, 'require_llama_cpp', return_value=(None, None, None)):
            with self.assertRaisesRegex(ValueError, 'matching mmproj'):
                with self.backend.load_model('model.gguf', 'none', object(), 4096, 'gpu_layers', 99, 1, 1, ''):
                    self.fail('Should not load without a projector')
        self.assertEqual(self.calls, [])

    def test_tagged_caption_is_compiled_without_relying_on_model_punctuation(self):
        from toolbox_moss_test.tagged_caption import compile_tagged_caption
        draft = {'sections': [{'name': '镜头与全局比例', 'description': '方幅近景。'},
                              {'name': '主体与动作', 'description': '双手捧着蓝杯。'}]}
        expected = '<|镜头与全局比例|>「方幅近景。」<|/镜头与全局比例|><|主体与动作|>「双手捧着蓝杯。」<|/主体与动作|>'
        self.assertEqual(compile_tagged_caption(draft), expected)

        @contextmanager
        def model(*args):
            yield object()

        with patch.object(self.nodes, 'load_model', model), patch.object(
                self.nodes, 'generate', return_value=(json.dumps(draft, ensure_ascii=False), '', 'perf')):
            result = self.node.enhance(**dict(self.params(), output_mode='Tagged Caption'))
        self.assertEqual(result[0], expected)
        self.assertEqual(json.loads(result[1]), draft)
        choices = self.node.INPUT_TYPES()['required']['output_mode'][0]
        self.assertEqual(choices, ['Structured Layout', 'Caption', 'Tagged Caption'])

    def test_tagged_caption_rejects_missing_fields_and_nested_tags(self):
        from toolbox_moss_test.tagged_caption import compile_tagged_caption
        for draft in [
            {'caption': 'wrong protocol'}, {'sections': []},
            {'sections': [{'name': 'test'}]},
            {'sections': [{'name': 'bad|name', 'description': 'text'}]},
            {'sections': [{'name': 'test', 'description': ''}]},
            {'sections': [{'name': 'test', 'description': '<|nested|>text'}]},
        ]:
            with self.assertRaises(ValueError):
                compile_tagged_caption(draft)

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
