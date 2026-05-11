#!/usr/bin/env python3
from pathlib import Path
import argparse,json,os,urllib.request

def fetch(url,headers=None):
    req=urllib.request.Request(url,headers=headers or {},method='GET')
    with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read().decode())

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='state'); ap.add_argument('--ollama-cloud',action='store_true'); args=ap.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    data=fetch('https://openrouter.ai/api/v1/models'); (out/'openrouter_models_snapshot.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    free=[]
    for m in data.get('data',[]):
        mid=m.get('id',''); pr=m.get('pricing') or {}; prompt=str(pr.get('prompt','')); comp=str(pr.get('completion',''))
        if mid.endswith(':free') or (prompt in ('0','0.0','0.000000') and comp in ('0','0.0','0.000000')):
            free.append({'id':mid,'name':m.get('name'),'context_length':m.get('context_length'),'supported_parameters':m.get('supported_parameters',[]),'top_provider':m.get('top_provider',{})})
    (out/'openrouter_free_candidates.json').write_text(json.dumps({'data':free},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if args.ollama_cloud:
        h={}; key=os.environ.get('OLLAMA_API_KEY')
        if key: h['Authorization']='Bearer '+key
        od=fetch('https://ollama.com/api/tags',h); (out/'ollama_cloud_models_snapshot.json').write_text(json.dumps(od,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
if __name__=='__main__': main()
