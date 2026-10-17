import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Nodes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        management = types.ModuleType('comfy.model_management')
        management.unload_all_models = lambda: None
        management.soft_empty_cache = lambda: None
        comfy = types.ModuleType('comfy'); comfy.model_management = management
        pil = types.ModuleType('PIL'); pil.Image = types.SimpleNamespace()
        self.modules = {'torch': types.ModuleType('torch'), 'numpy': types.ModuleType('numpy'),
                        'PIL': pil, 'comfy': comfy, 'comfy.model_management': management,
                        'folder_paths': types.SimpleNamespace(get_output_directory=lambda: str(self.output))}
        with patch.dict(sys.modules, self.modules):
            spec = importlib.util.spec_from_file_location('toolbox_3dgs', ROOT/'nodes/3dgs/__init__.py')
            self.nodes = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.nodes)

    def test_registers_four_types_without_optional_dependencies(self):
        self.assertEqual(set(self.nodes.NODE_CLASS_MAPPINGS),
                         {'LocalCOLMAPDataset', 'LocalVideoFrames', 'LocalBrushTrain', 'LocalPLYFile'})
        for cls in self.nodes.NODE_CLASS_MAPPINGS.values():
            self.assertEqual(cls.CATEGORY, 'ToolBox/3DGS')
            self.assertTrue(cls.INPUT_TYPES()['required'])

    def test_missing_pycolmap_fails_before_creating_dataset(self):
        with patch.object(self.nodes.importlib.util, 'find_spec', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'PyCOLMAP is missing.*INSTALL_3DGS=true'):
                self.nodes.LocalCOLMAPDataset().export(None, 'sample', 2, True, 'global', 'exhaustive', 8192)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_brush_reports_installation_without_touching_models(self):
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Brush is missing.*INSTALL_3DGS=true'):
                self.nodes.LocalBrushTrain().train('', 5000, 768, 500000, 8)

    def test_brush_inherits_external_device_environment(self):
        dataset = self.output/'dataset'; dataset.mkdir()
        (dataset/'report.json').write_text(json.dumps({'registered_images': 8}))
        observed = {}
        def run(args, logfile, env):
            observed.update(env)
            (Path(args[args.index('--export-path')+1])/'scene_1000.ply').write_bytes(b'x'*1001)
        with patch.dict(sys.modules, self.modules), patch.object(self.nodes, 'require_brush', return_value=Path('/opt/3dgs/bin/brush_app')), \
             patch.object(self.nodes, 'run_logged', side_effect=run), patch.dict(os.environ, {'VK_DRIVER_FILES': 'external.json', 'VK_ICD_FILENAMES': 'legacy.json', 'LD_LIBRARY_PATH': 'external-libraries'}):
            result = self.nodes.LocalBrushTrain().train(str(dataset), 1000, 768, 10000, 0)
        for key, value in [('VK_DRIVER_FILES', 'external.json'), ('VK_ICD_FILENAMES', 'legacy.json'), ('LD_LIBRARY_PATH', 'external-libraries')]:
            self.assertEqual(observed[key], value)
        self.assertTrue(Path(result['result'][0]).is_file())

    def test_workflows_are_portable_and_keep_reuse_paths_empty(self):
        workflows = list((ROOT/'examples/3dgs/workflows').glob('*.json'))
        self.assertEqual(len(workflows), 4)
        for file in workflows:
            text = file.read_text()
            self.assertNotRegex(text, r'/home/|/media/|595\.58\.03|/tmp/comfyui-')
            graph = json.loads(text)
            if file.name.startswith(('03', '04')):
                strings = [n for n in graph['nodes'] if n['type']=='PrimitiveString']
                self.assertEqual([n['widgets_values'] for n in strings], [['']])
                self.assertTrue(all(v == '' for v in strings[0].get('widgets_values_named', {}).values()))

    def test_docs_and_example_links_exist(self):
        files = list((ROOT/'docs/3dgs').rglob('*.md')) + [ROOT/'examples/3dgs/README.md']
        for file in files:
            for match in re.finditer(r'!?\[[^\]]*\]\(([^\)]+)\)', file.read_text()):
                target = match[1].split('#')[0]
                if target and '://' not in target:
                    self.assertTrue((file.parent/target).exists(), f'{file}: {target}')


if __name__ == '__main__':
    unittest.main()
