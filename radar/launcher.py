import argparse
import socket
import sys
import threading
import webbrowser
import httpx
import uvicorn

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--no-browser',action='store_true'); args=parser.parse_args()
    url='http://127.0.0.1:8765'
    try:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('127.0.0.1',8765))
    except OSError:
        try:
            resp=httpx.get(url+'/api/state',timeout=2,trust_env=False); resp.raise_for_status()
            if 'topics' in resp.json() and 'task' in resp.json():
                print('论文雷达已运行：'+url)
                if not args.no_browser: webbrowser.open(url)
                return 0
        except Exception: pass
        print('8765 端口被其他程序占用，请释放端口后再启动。',file=sys.stderr); return 1
    print('论文雷达：'+url,flush=True)
    if not args.no_browser: threading.Timer(1.5,lambda:webbrowser.open(url)).start()
    uvicorn.run('radar.server:app',host='127.0.0.1',port=8765,log_level='info')
    return 0

if __name__=='__main__': raise SystemExit(main())
