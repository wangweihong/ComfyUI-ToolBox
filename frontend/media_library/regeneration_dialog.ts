type Output = {id:string;path:string;name:string};
type Job = {id:string;status:string;error:string;outputs:Output[]};
type Prepared = {token:string;prefix:string;models:string[];batches:{batch_size:unknown}[];seed_changes:{node_id:string;title:string;field:string;before:number|string;after:number}[]};
type Request = <T=any>(path:string,data?:unknown)=>Promise<T>;

export function openRegenerationDialog({assetId,assetName,request,locate}:{assetId:string;assetName:string;request:Request;locate:(output:Output)=>Promise<void>}){
  const existing=document.getElementById('regeneration-dialog') as HTMLDialogElement|null;
  if(existing?.open){existing.focus();return;}
  const el=<K extends keyof HTMLElementTagNameMap>(tag:K,text='',className='')=>{const node=document.createElement(tag);node.textContent=text;node.className=className;return node;};
  const dialog=el('dialog');dialog.id='regeneration-dialog';dialog.setAttribute('aria-label','重新生成');
  const heading=el('div','','dialog-head'),title=el('h2','重新生成'),close=el('button','×');close.type='button';close.setAttribute('aria-label','关闭重新生成');heading.append(title,close);
  const intro=el('p',assetName,'detail-name'),note=el('p','使用素材中记录的原流程，换随机种子生成新图片；保留原批次，不修改当前画布。','muted');
  const selection=el('div'),summary=el('div','','regeneration-summary'),message=el('p','正在读取生成信息…','muted');message.setAttribute('role','status');
  const actions=el('div','','dialog-actions'),prepareButton=el('button','检查生成条件'),submitButton=el('button','确认排队生成','primary');submitButton.hidden=true;prepareButton.hidden=true;actions.append(prepareButton,submitButton);
  const progress=el('section','','regeneration-progress');progress.hidden=true;
  dialog.append(heading,intro,note,selection,message,summary,actions,progress);document.body.append(dialog);
  let closed=false,submitting=false,epoch=0,timer=0,prepared:Prepared|null=null,target='';
  const release=(token:string)=>{void request('/regenerations/release',{token}).catch(()=>{});};
  const dismiss=()=>{if(closed)return;closed=true;++epoch;clearTimeout(timer);if(prepared&&!submitting)release(prepared.token);dialog.close();dialog.remove();};
  close.onclick=dismiss;dialog.addEventListener('cancel',event=>{event.preventDefault();dismiss();});dialog.showModal();

  async function showJob(job:Job){
    if(closed)return;clearTimeout(timer);progress.hidden=false;progress.replaceChildren(el('h3','生成任务'));
    const labels:Record<string,string>={submitting:'正在提交',queued:'排队中',running:'正在生成',complete:'生成完成',failed:'生成失败',unknown:'提交或执行状态待确认'};
    progress.append(el('p',labels[job.status]||job.status));
    if(job.error)progress.append(el('p',job.error,'error'));
    for(const output of job.outputs){const button=el('button','定位 '+output.name);button.type='button';button.onclick=()=>{dismiss();void locate(output);};progress.append(button);}
    if(['queued','running','submitting'].includes(job.status))timer=window.setTimeout(()=>{void request<Job>('/regenerations/'+job.id).then(showJob).catch(error=>{if(!closed)progress.append(el('p',error.message,'error'));});},2000);
  }
  async function prepare(){
    if(!target)return;const current=++epoch;if(prepared)release(prepared.token);prepared=null;submitting=false;submitButton.hidden=true;submitButton.disabled=false;prepareButton.disabled=true;summary.replaceChildren();message.textContent='正在检查节点、模型和输入资源…';message.className='muted';
    try{
      const result=await request<Prepared>('/regenerations/prepare',{id:assetId,output_node:target});if(closed||current!==epoch){release(result.token);return;}
      prepared=result;message.textContent='预检通过。确认下方参数后再排队，不覆盖原图。';
      summary.append(el('h3','新图保存位置'),el('p',result.prefix+'_<序号>.png','folder-path'));
      summary.append(el('p','保留原流程批次'+(result.batches.length?'：'+result.batches.map(batch=>typeof batch.batch_size==='number'?String(batch.batch_size):'动态批次').join('、'):'；实际张数以执行结果为准'),'muted'));
      if(result.models.length)summary.append(el('h3','使用的模型'),el('p',result.models.join('\n'),'folder-path'));
      summary.append(el('h3','随机种子调整'));
      const list=el('div','','regeneration-seeds');for(const change of result.seed_changes){const row=el('div');row.append(el('strong',change.title),el('code',`${change.before} → ${change.after}`));list.append(row);}summary.append(list);submitButton.hidden=false;
    }catch(error){if(!closed&&current===epoch){message.textContent=(error as Error).message;message.className='error';}}
    finally{if(!closed&&current===epoch){prepareButton.disabled=false;prepareButton.textContent='重新预检';}}
  }
  prepareButton.onclick=()=>void prepare();
  submitButton.onclick=async()=>{
    if(!prepared||submitButton.disabled)return;submitting=true;submitButton.disabled=true;prepareButton.disabled=true;const current=epoch;
    try{const job=await request<Job>('/regenerations/submit',{token:prepared.token});if(closed||current!==epoch)return;submitButton.hidden=true;message.textContent=job.status==='failed'?'任务未能入队，请查看下方错误。':job.status==='unknown'?'提交结果待确认，不会自动重复入队。':'任务已交给 ComfyUI；关闭此窗口后仍会继续执行。';await showJob(job);}
    catch(error){if(!closed&&current===epoch){message.textContent=(error as Error).message;message.className='error';submitButton.disabled=false;}}
    finally{if(!closed&&current===epoch)prepareButton.disabled=false;}
  };
  void Promise.all([
    request<{available:boolean;reason?:string;outputs:{id:string;title:string;prefix:string}[]}>('/regenerations/options?'+new URLSearchParams({id:assetId})),
    request<{items:Job[]}>('/regenerations?'+new URLSearchParams({source_id:assetId}))
  ]).then(async([options,jobs])=>{
    if(closed)return;if(jobs.items.length)void request<Job>('/regenerations/'+jobs.items[0].id).then(showJob).catch(error=>{if(!closed){progress.hidden=false;progress.textContent=error.message;}});
    if(!options.available){message.textContent=options.reason||'此素材暂不支持直接重新生成';message.className='error';return;}
    prepareButton.hidden=false;
    if(options.outputs.length===1){target=options.outputs[0].id;selection.append(el('p','保存分支：'+options.outputs[0].title,'muted'));await prepare();}
    else{
      const label=el('label','选择要重新生成的图片保存分支'),select=el('select');select.setAttribute('aria-label','生成分支');const empty=el('option','请选择');empty.value='';select.append(empty);
      for(const output of options.outputs){const option=el('option',output.title+(output.prefix?' · '+output.prefix:''));option.value=output.id;select.append(option);}label.append(select);selection.append(label);prepareButton.disabled=true;message.textContent='检测到多个保存分支，请选择本次要运行的分支。';
      select.onchange=()=>{++epoch;target=select.value;if(prepared)release(prepared.token);prepared=null;summary.replaceChildren();submitButton.hidden=true;submitButton.disabled=false;prepareButton.disabled=!target;};
    }
  }).catch(error=>{if(!closed){message.textContent=error.message;message.className='error';}});
}
