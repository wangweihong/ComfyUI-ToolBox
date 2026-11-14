"""CPU-only deterministic queue adapter for tests; never loads a model."""
import copy
import json
from pathlib import Path
from PIL import Image, PngImagePlugin


def graph(batch=2):
    return {
        'seed': {'class_type':'Seed (rgthree)','inputs':{'seed':123}},
        'image': {'class_type':'EmptyImage','inputs':{'width':32,'height':32,'batch_size':batch,'color':['seed',0]}},
        'save': {'class_type':'SaveImage','inputs':{'images':['image',0],'filename_prefix':'original'}},
    }


class FakeRuntime:
    def __init__(self, root):
        self.root=Path(root);self.submissions=[];self.states={};self.validation_error=None;self.submit_error=None

    def output_root(self): return self.root

    def definitions(self, prompt):
        return {
            'Seed (rgthree)': {'required':{'seed':('INT',{'min':-1,'max':2**64-1})}},
            'PrimitiveInt': {'required':{'value':('INT',{'min':0,'max':2**64-1})}},
            'EmptyImage': {'required':{'width':('INT',{}),'height':('INT',{}),'batch_size':('INT',{}),'color':('INT',{})}},
            'KSampler': {'required':{'seed':('INT',{'min':0,'max':2**64-1})}},
            'SaveImage': {'required':{'images':('IMAGE',),'filename_prefix':('STRING',)}},
        }

    async def validate(self, prompt_id, prompt, target):
        if self.validation_error: raise self.validation_error
        assert target in prompt

    async def submit(self, payload):
        if self.submit_error: raise self.submit_error
        self.submissions.append(copy.deepcopy(payload))
        target=payload['partial_execution_targets'][0];prompt=payload['prompt'];prefix=prompt[target]['inputs']['filename_prefix']
        image_node=prompt[prompt[target]['inputs']['images'][0]]
        batch=image_node['inputs'].get('batch_size',1)
        png=PngImagePlugin.PngInfo();png.add_text('prompt',json.dumps(prompt));png.add_text('tb_media_regeneration',json.dumps(payload['extra_data']['extra_pnginfo']['tb_media_regeneration']))
        images=[]
        for index in range(batch):
            path=self.root/(prefix+f'_{index:05}.png');path.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(32,32),'blue').save(path,pnginfo=png)
            images.append({'filename':path.name,'subfolder':path.parent.relative_to(self.root).as_posix(),'type':'output'})
        self.states[payload['prompt_id']]={'status':'complete','images':images}

    def status(self, prompt_id, target): return self.states.get(prompt_id,{'status':'unknown','error':'status unavailable'})
