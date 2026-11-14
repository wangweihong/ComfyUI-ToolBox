"""Run in ComfyUI's Python: real executor, CPU, synthetic prompts, temporary DB only."""
import argparse
import asyncio
import copy
import importlib
import json
import sys
import tempfile
import types
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plugin', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--comfy-root', type=Path, required=True)
    args = parser.parse_args()
    # Prevent ComfyUI from interpreting this script's arguments or initializing CUDA.
    sys.argv = [sys.argv[0], '--cpu']
    sys.path.insert(0, str(args.comfy_root))
    import comfy.options
    comfy.options.enable_args_parsing()
    import execution
    import nodes

    package = types.ModuleType('_toolbox_batch_integration')
    package.__path__ = [str(args.plugin)]
    sys.modules[package.__name__] = package
    prompts = importlib.import_module(package.__name__ + '.nodes.prompt_nodes')
    calls = []

    class Sink:
        @classmethod
        def INPUT_TYPES(cls):
            return {'required':dict(zip(('id','prompt','width','height','metadata','total'),
                                        (('INT',),('STRING',),('INT',),('INT',),('STRING',),('INT',))))}
        RETURN_TYPES = ('INT',)
        FUNCTION = 'consume'
        OUTPUT_NODE = True
        def consume(self, id, prompt, width, height, metadata, total):
            data = json.loads(metadata)
            assert (data['id'], data['width'], data['height']) == (id, width, height)
            assert data['shasum'] == prompts.prompt_shasum(prompt)
            calls.append((id, prompt, total))
            return (id,)

    messages = []
    server = types.SimpleNamespace(client_id=None, last_node_id=None, sockets_metadata={},
                                   send_sync=lambda *values:messages.append(values), queue_updated=lambda:None)
    nodes.NODE_CLASS_MAPPINGS.update({'ToolBoxPromptsByTag':prompts.ToolBoxPromptsByTag, 'ToolBoxTestSink':Sink})
    executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                                        cache_args={'ram':0,'ram_inactive':0})
    with tempfile.TemporaryDirectory(prefix='toolbox-batch-executor-') as directory:
        prompts.database.DEFAULT_DB = Path(directory) / 'prompts.sqlite3'
        def write(text):
            return prompts.ToolBoxPromptWriter().write_prompt(0,text,'zh','image','natural',False,
                                                               'plaintext',False,32,32,'摄影')[0]
        ids = [write('Synthetic CPU first'), write('Synthetic CPU second')]
        inputs = {name:info[1]['default'] for name,info in prompts.ToolBoxPromptsByTag.INPUT_TYPES()['required'].items()}
        inputs['tags'] = '摄影'
        graph = {'1':{'class_type':'ToolBoxPromptsByTag','inputs':inputs},
                 '2':{'class_type':'ToolBoxTestSink','inputs':{name:['1',i] for i,name in enumerate(Sink.INPUT_TYPES()['required'])}}}

        async def run():
            valid = await execution.validate_prompt('batch-check', copy.deepcopy(graph), None)
            assert valid[0], valid
            await executor.execute_async(copy.deepcopy(graph),'first',{'client_id':'synthetic'},['2'])
            assert executor.success, executor.status_messages
            assert [row[0] for row in calls] == ids
            assert all(row[2] == 2 for row in calls)
            first_ui = copy.deepcopy(executor.history_result['outputs']['1'])
            messages.clear()
            await executor.execute_async(copy.deepcopy(graph),'cached',{'client_id':'synthetic'},['2'])
            assert executor.success and len(calls) == 2
            cached_ui = [message[1]['output'] for message in messages if message[0] == 'executed' and message[1]['node'] == '1']
            assert cached_ui and cached_ui[-1] == first_ui, messages
            inputs.update(start_index=1,limit=1)
            await executor.execute_async(copy.deepcopy(graph),'offset',{'client_id':'synthetic'},['2'])
            assert executor.success and calls[-1][0] == ids[1] and len(calls) == 3
            write('Synthetic CPU third')
            await executor.execute_async(copy.deepcopy(graph),'revision',{'client_id':'synthetic'},['2'])
            assert executor.success and calls[-1][2] == 3 and len(calls) == 4
            inputs['start_index'] = 100
            await executor.execute_async({'1':copy.deepcopy(graph['1'])},'empty-preview',{'client_id':'synthetic'},['1'])
            assert executor.success
            preview = executor.history_result['outputs']['1']['toolbox_prompt_batch'][0]
            assert preview['total'] == 3 and preview['count'] == 0

        asyncio.run(run())
        print(json.dumps({'downstream_items':2,'scalar_total_broadcast':True,'cached_ui_restored':True,
                          'offset_and_revision':True,'empty_preview':True,'temporary_only':True}))


if __name__ == '__main__':
    main()
