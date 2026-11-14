/** Decode embedded JSON objects without turning textual numbers/booleans into new types. */
export function structuredMetadata(value:unknown,depth=0,decodeStrings=true):unknown {
  if(depth>=32)return value;
  let decoded=value;
  if(typeof value==='string'){
    if(!decodeStrings)return value;
    for(let count=0;count<3&&typeof decoded==='string';count++){
      const text=decoded.trim();if(!/^[{[\"]/.test(text))break;
      try{
        let unsafe=false;
        const parsed=JSON.parse(text,(_key:string,item:unknown,context?:{source?:string})=>{
          if(typeof item==='number'&&Number.isInteger(item)&&!Number.isSafeInteger(item)){
            if(context?.source)return context.source;
            unsafe=true;
          }
          return item;
        });
        // Older engines cannot recover the exact digits; retain the original JSON string.
        if(unsafe)return value;
        decoded=parsed;
      }catch{break;}
    }
    if(decoded===null||typeof decoded!=='object')return value;
  }
  if(decoded!==null&&typeof decoded==='object'&&!Array.isArray(decoded)){
    const object=decoded as Record<string,unknown>;
    // Widget/input values are executable data: a JSON-looking prompt is still text.
    if(Array.isArray(object.nodes)||Object.values(object).some(node=>node!==null&&typeof node==='object'&&'class_type' in node&&'inputs' in node))decodeStrings=false;
  }
  if(Array.isArray(decoded))return decoded.map(item=>structuredMetadata(item,depth+1,decodeStrings));
  if(decoded!==null&&typeof decoded==='object')return Object.fromEntries(Object.entries(decoded).map(([key,item])=>[key,structuredMetadata(item,depth+1,decodeStrings)]));
  return decoded;
}
