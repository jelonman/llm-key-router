#!/usr/bin/env python3
from pathlib import Path
import argparse,json,sys,urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from llm_key_router.app import load_json, parse_env, secret

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='config.json'); ap.add_argument('--secrets',default='secrets.env'); args=ap.parse_args()
    cfg=load_json(Path(args.config)); env=parse_env(Path(args.secrets)); results=[]
    for pname,p in cfg.get('providers',{}).items():
        if p.get('type')!='openai_compatible' or 'openrouter.ai' not in str(p.get('base_url','')): continue
        for c in p.get('credentials',[]):
            if not c.get('enabled',True): continue
            key=secret(c.get('api_key_env'), env); label=c.get('label')
            if not key: results.append({'provider':pname,'label':label,'status':'missing_secret'}); continue
            try:
                req=urllib.request.Request('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+key},method='GET')
                with urllib.request.urlopen(req,timeout=30) as r:
                    d=json.loads(r.read().decode()).get('data',{})
                    results.append({'provider':pname,'label':label,'status':r.status,'is_free_tier':d.get('is_free_tier'),'limit':d.get('limit'),'limit_remaining':d.get('limit_remaining'),'limit_reset':d.get('limit_reset'),'usage_daily':d.get('usage_daily')})
            except Exception as e: results.append({'provider':pname,'label':label,'status':'error','error':repr(e)})
    print(json.dumps({'results':results},indent=2,ensure_ascii=False))
if __name__=='__main__': main()
