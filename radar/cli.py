import argparse
import json
from pathlib import Path
from radar.service import Radar
from radar.topics import BY_ID
from radar.summaries import sync_reports

ROOT=Path(__file__).resolve().parent.parent

def main():
    parser=argparse.ArgumentParser(description='本地 arXiv 论文雷达')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ['fetch','digest']:
        p=sub.add_parser(name); p.add_argument('--days',type=int,default=7 if name=='digest' else 30)
        p.add_argument('--budget',type=int,default=30); p.add_argument('--topics',nargs='+',choices=list(BY_ID),default=list(BY_ID))
        p.add_argument('--enrich',action='store_true')
        p.add_argument('--start-date'); p.add_argument('--end-date')
        if name=='digest': p.add_argument('--no-fetch',action='store_true'); p.add_argument('--limit',type=int,default=20)
    ack=sub.add_parser('ack'); ack.add_argument('ids',nargs='+')
    configure=sub.add_parser('configure',help='选择已有 Obsidian 文献库，不修改库内容')
    configure.add_argument('--vault',required=True)
    sub.add_parser('status')
    sub.add_parser('sync-summaries')
    args=parser.parse_args(); r=Radar(ROOT)
    if args.command=='configure':
        vault=Path(args.vault).expanduser().resolve()
        if not vault.is_dir(): parser.error('Obsidian 目录不存在，请选择已有库')
        r.store.set_setting('vault_path',str(vault))
        print(json.dumps(r.store.settings(),ensure_ascii=False,indent=2)); return 0
    if args.command=='sync-summaries':
        print(json.dumps(sync_reports(r.store,ROOT/'reports'),ensure_ascii=False,indent=2)); return 0
    if args.command in ('fetch','digest'):
        if not 1<=args.days<=3650 or not 1<=args.budget<=200: parser.error('days 必须 1–3650，budget 必须 1–200')
        if bool(args.start_date)!=bool(args.end_date): parser.error('起止日期需要同时指定')
        if args.start_date:
            from datetime import date
            try:
                begin=date.fromisoformat(args.start_date); end=date.fromisoformat(args.end_date)
                if begin>end or (end-begin).days>3650: parser.error('日期范围无效')
            except ValueError: parser.error('日期必须 YYYY-MM-DD')
        task=None
        if args.command=='fetch' or not args.no_fetch:
            task=r.fetch(args.topics,args.days,args.budget,args.enrich,start_date=args.start_date,end_date=args.end_date)
        if args.command=='fetch': result={'task':task,'cached':len(r.store.papers())}
        else:
            path,rows=r.digest(args.limit)
            result={'task':task,'report_path':str(path) if path else None,'new_papers':rows,'count':len(rows),
                'delivery_note':'汇报成功后再运行 ack <ids>，生成草稿不会自动标记已汇报。'}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if task and task['status']=='failed' else 0
    if args.command=='ack': r.store.mark_reported(args.ids); print(json.dumps({'acknowledged':args.ids},ensure_ascii=False)); return 0
    print(json.dumps({'cached':len(r.store.papers()),'settings':r.store.settings(),'digests':r.store.digests()},ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
