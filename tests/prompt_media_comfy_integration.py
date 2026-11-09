"""Run inside ComfyUI's Python with ComfyUI on PYTHONPATH. CPU synthetic data only."""
import argparse
import importlib
import json
import sys
import tempfile
import types
from fractions import Fraction
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plugin',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    package=types.ModuleType('_toolbox_example_test');package.__path__=[str(args.plugin)];sys.modules[package.__name__]=package
    prompts=importlib.import_module(package.__name__+'.nodes.prompt_nodes')
    examples=importlib.import_module(package.__name__+'.nodes.prompt_examples')
    media=importlib.import_module(package.__name__+'.nodes.prompt_media_nodes')
    example_schema=importlib.import_module(package.__name__+'.nodes.prompt_examples_schema')
    import torch
    import folder_paths
    import av
    from comfy_api.latest import InputImpl,Types
    with tempfile.TemporaryDirectory(prefix='toolbox-native-media-test-') as directory:
        root=Path(directory);output=root/'output';output.mkdir();folder_paths.set_output_directory(str(output))
        prompts.database.DEFAULT_DB=root/'prompts.sqlite3';examples.OUTPUT_ROOT=output
        row=prompts.ToolBoxPromptWriter().write_prompt(0,'Synthetic CPU save integration','zh','image','natural',False,'plaintext',False,32,32,'synthetic')
        with prompts.connect_db() as conn:example_schema.initialize(conn)
        revision=prompts.prompt_data_revision()
        images=torch.zeros((2,32,32,3),device='cpu');images[1,:,:,1]=1
        for metadata in ({},{'prompt_metadata':None},{'prompt_metadata':''},{'prompt_metadata':' \t\n'}):
            unlinked=media.ToolBoxPromptSaveImage().save(images,filename_prefix='images/synthetic/unlinked',prompt={'synthetic':{}},extra_pnginfo={'workflow':{}},**metadata)
            unlinked_report=json.loads(unlinked['result'][1]);assert unlinked_report['registration']=='skipped',unlinked_report
            assert unlinked['result'][0] is images
            assert len(unlinked_report['paths'])==2
            from PIL import Image
            for path in unlinked_report['paths']:
                with Image.open(output/path) as image:
                    assert image.size==(32,32)
                    assert json.loads(image.info['prompt'])=={'synthetic':{}}
                    assert json.loads(image.info['workflow'])=={}
            assert examples.list_examples({},row[0])['total']==0
        image_result=media.ToolBoxPromptSaveImage().save(images,row[-1],' images/synthetic/test ',prompt={'synthetic':{}},extra_pnginfo={'workflow':{}})
        image_report=json.loads(image_result['result'][1]);assert image_report['registration']=='registered',image_report
        assert len(image_report['paths'])==2
        assert all(path.startswith('images/synthetic/test_') and (output/path).is_file() for path in image_report['paths'])
        video=InputImpl.VideoFromComponents(Types.VideoComponents(images=images,frame_rate=Fraction(2)))
        video_class=media.ToolBoxPromptSaveVideo;schema=video_class.define_schema()
        assert schema.node_id=='ToolBoxPromptSaveVideo' and len(schema.outputs)==2
        video_class.hidden=types.SimpleNamespace(prompt={'synthetic':{}},extra_pnginfo={'workflow':{}})
        result=video_class.execute(video,row[-1],' videos/synthetic/test ',{'format':'mp4','codec':{'codec':'h264'}})
        report=json.loads(result.result[1]);assert report['registration']=='registered',report
        assert report['paths'][0].startswith('videos/synthetic/test_')
        assert result.result[0] is video
        video_path=output/report['paths'][0]
        with av.open(str(video_path)) as container:
            frames=list(container.decode(video=0));assert len(frames)==2 and frames[0].width==32
        vhs=media.ToolBoxPromptRecordMedia().record(row[-1],vhs_filenames=(True,[str(output/image_report['paths'][0]),str(video_path)]))
        assert json.loads(vhs['result'][0])['paths']==report['paths']
        assert examples.list_examples({},row[0])['total']==3
        assert prompts.prompt_data_revision()==revision
        assert prompts.ToolBoxPromptReader().read_prompt(row[0])[-1]==row[-1]
        print(json.dumps({'native_pngs':2,'native_h264_video_frames':len(frames),'vhs_final_only':True,'example_count':3,'temporary_only':True}))


if __name__=='__main__':main()
