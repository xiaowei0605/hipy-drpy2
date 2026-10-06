#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stripchat-live: Stripchat 直播 → APTV 本地 M3U 服务
============================================================
APTV「Python 脚本服务」模式: 把本文件添加到 APTV 并启动,
再用订阅配置添加 http://127.0.0.1:8768/all.m3u 即可。

接口:
  /               首页(频道列表)
  /health         存活检查
  /diag           诊断(缓存状态/各分类数量)
  /all.m3u        聚合订阅(4 分组: 女主播/情侣/男主播/跨性别)
  /<stream_id>.m3u8  单房间, 302 跳到解析出的 m3u8

用法:
  python3 stripchat-live.py [port]      # 默认 8768
仅标准库, 无第三方依赖。

注意: Stripchat 有 Cloudflare 盾, 本脚本为纯直连(无 CF 绕过),
若列表为空, 说明出口 IP 被 CF 拦截, 需换网络环境重试。
"""
import argparse
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_BASE = 'https://stripchat.com/api/front'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://stripchat.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
}
HLS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0',
    'Referer': 'https://stripchat.com/',
    'Accept-Language': 'en,zh-CN;q=0.9,zh;q=0.8',
}
CATEGORIES = [
    ('girls', '女主播'),
    ('couples', '情侣'),
    ('men', '男主播'),
    ('trans', '跨性别'),
]
LIST_LIMIT = 60
CACHE_TTL = 300  # 房间列表缓存 5 分钟


# ================= 基础 HTTP =================
def http_get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'ignore')


def http_get_json(url, headers=None, timeout=12):
    try:
        return json.loads(http_get(url, headers, timeout) or '{}')
    except Exception:
        return {}


def country_code_to_flag(code):
    code = (code or '').strip().upper()
    if len(code) == 2 and code.isalpha():
        return ''.join(chr(ord(c) - ord('A') + 0x1F1E6) for c in code)
    return ''


# ================= 房间列表 =================
def fetch_rooms(primary_tag, limit=LIST_LIMIT):
    url = ('%s/v2/models?primaryTag=%s&limit=%d&offset=0&sortBy=stripRanking&_t=%d'
           % (API_BASE, primary_tag, limit, int(time.time() * 1000)))
    data = http_get_json(url, HEADERS)
    models = []
    if isinstance(data, dict):
        if isinstance(data.get('models'), list):
            models = data['models']
        elif isinstance(data.get('blocks'), list):
            for b in data['blocks']:
                if isinstance(b.get('models'), list):
                    models.extend(b['models'])
    rooms = []
    for m in models:
        if not isinstance(m, dict):
            continue
        if str(m.get('status') or '').lower() != 'public':
            continue  # 只收录正在直播的
        stream = str(m.get('streamName') or '').strip()
        mid = str(m.get('id') or '').strip()
        sid = stream if stream.isdigit() else mid
        username = str(m.get('username') or '').strip()
        if not sid or not username:
            continue
        rooms.append({
            'id': sid,
            'name': country_code_to_flag(m.get('country')) + username,
            'viewers': m.get('viewersCount') or 0,
        })
    return rooms


_CACHE = {'ts': 0, 'rooms': {}, 'err': ''}


def refresh_cache():
    all_rooms = {}
    errs = []
    for tid, _name in CATEGORIES:
        try:
            all_rooms[tid] = fetch_rooms(tid)
        except Exception as e:
            errs.append('%s:%s' % (tid, e))
            all_rooms.setdefault(tid, [])
    _CACHE['ts'] = time.time()
    _CACHE['rooms'] = all_rooms
    _CACHE['err'] = '; '.join(errs)


def ensure_cache():
    if time.time() - _CACHE['ts'] > CACHE_TTL:
        refresh_cache()


def build_all_m3u(host):
    ensure_cache()
    lines = ['#EXTM3U']
    for tid, cname in CATEGORIES:
        for r in _CACHE['rooms'].get(tid, []):
            lines.append('#EXTINF:-1 tvg-id="%s" group-title="%s",%s'
                         % (r['id'], cname, r['name']))
            lines.append('http://%s/%s.m3u8' % (host, r['id']))
    return '\n'.join(lines) + '\n'


# ================= HLS 解析(有界, 避免单次点播卡太久) =================
def _join_url(base_url, relative):
    if not relative or relative.startswith('http'):
        return relative
    base = base_url.rstrip('/')
    if relative.startswith('/'):
        return base[:base.find('/', 8)] + relative
    return base + '/' + relative


def _parse_master_variants(m3u8_text, base_url):
    lines = (m3u8_text or '').split('\n')
    variants = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith('#EXT-X-STREAM-INF:'):
            continue
        bw = re.search(r'BANDWIDTH=(\d+)', line, re.I)
        name = re.search(r'NAME="([^"]+)"', line, re.I)
        res = re.search(r'RESOLUTION=(\d+)x(\d+)', line, re.I)
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        if not nxt or nxt.startswith('#'):
            continue
        nm = name.group(1) if name else ''
        if 'blurred' in nm.lower():
            continue
        variants.append({
            'bandwidth': int(bw.group(1)) if bw else 0,
            'name': nm,
            'height': int(res.group(2)) if res else 0,
            'url': _join_url(base_url, nxt),
        })
    return variants


def _variant_score(v):
    h = v.get('height', 0) or 0
    if str(v.get('name', '')).strip().lower() in ('source', 'orig', 'original'):
        h = max(h, 2160)
    return h * 1000000000 + int(v.get('bandwidth', 0) or 0)


def _build_master_urls(room_id):
    s = str(room_id)
    return [
        'https://edge-hls.doppiocdn.org/hls/%s/master/%s_auto.m3u8' % (s, s),
        'https://edge-hls.doppiocdn.com/hls/%s/master/%s_auto.m3u8' % (s, s),
        'https://edge-hls.growcdnssedge.com/hls/%s/master/%s_auto.m3u8' % (s, s),
    ]


def _is_playable_playlist(url):
    try:
        text = http_get(url, HLS_HEADERS, timeout=8)
        if not text or len(text) < 12:
            return False
        if '#EXT-X-MOUFLON-ADVERT' in text or 'cpa/v2/' in text:
            return False
        return '#EXTINF' in text
    except Exception:
        return False


def _to_grow_media_url(u):
    return re.sub(
        r'https?://media-hls\.doppiocdn\.(?:org|com|net)/(b-hls-\d+)/',
        'https://media-hls.growcdnssedge.com/\\1/', str(u or ''))


def resolve_hls(stream_id):
    """返回可播的 m3u8 地址, 失败返回 ''。全程有界, 最多约 20 个请求。"""
    sid = str(stream_id).strip()
    if not sid.isdigit():
        return ''
    variants = []
    for mu in _build_master_urls(sid):
        try:
            text = http_get(mu, HLS_HEADERS, timeout=8)
        except Exception:
            continue
        if not text or ('#EXT-X-MOUFLON-ADVERT' in text and '#EXT-X-STREAM-INF' not in text):
            continue
        base = mu.rsplit('/', 1)[0] + '/'
        variants.extend(_parse_master_variants(text, base))
    if variants:
        best = max(variants, key=_variant_score)
        url = best.get('url') or ''
        if url and _is_playable_playlist(url):
            grow = _to_grow_media_url(url)
            if grow != url and _is_playable_playlist(grow):
                return grow
            return url
    # 轻量兜底: 常见分片 x 有限后缀
    shards = []
    for v in variants:
        m = re.search(r'b-hls-(\d+)', str(v.get('url', '')), re.I)
        if m and m.group(1) not in shards:
            shards.append(m.group(1))
    for shard in (shards or ['10', '11', '12', '24'])[:4]:
        for suf in ('', '_source', '_1080p', '_720p'):
            url = 'https://media-hls.growcdnssedge.com/b-hls-%s/%s/%s%s.m3u8' % (shard, sid, sid, suf)
            if _is_playable_playlist(url):
                return url
    return ''


# ================= HTTP 服务 =================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        host = self.headers.get('Host', 'localhost:8768')

        if path in ('/', '/index.html'):
            ensure_cache()
            items = []
            for tid, cname in CATEGORIES:
                rooms = _CACHE['rooms'].get(tid, [])
                items.append('<h3>%s (%d)</h3><ul>' % (cname, len(rooms)))
                for r in rooms[:20]:
                    items.append('<li><a href="/%s.m3u8">%s</a></li>' % (r['id'], r['name']))
                items.append('</ul>')
            self._send(200, '<!DOCTYPE html><html><head><meta charset="utf-8">'
                            '<meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<title>Stripchat直播</title></head><body>'
                            '<h2>Stripchat 直播</h2>'
                            '<p>聚合订阅: <a href="/all.m3u">/all.m3u</a></p>'
                            + ''.join(items) + '</body></html>',
                       'text/html; charset=utf-8')
            return

        if path == '/health':
            self._send(200, 'ok')
            return

        if path == '/diag':
            ensure_cache()
            info = ['cache_age=%ds err=%s' % (int(time.time() - _CACHE['ts']), _CACHE['err'] or '无')]
            for tid, cname in CATEGORIES:
                info.append('%s(%s): %d间' % (cname, tid, len(_CACHE['rooms'].get(tid, []))))
            self._send(200, '\n'.join(info) + '\n')
            return

        if path == '/all.m3u':
            try:
                body = build_all_m3u(host)
            except Exception as e:
                self._send(503, '拉取失败: %s\n' % e)
                return
            n = body.count('#EXTINF')
            if n == 0:
                self._send(503, '暂无直播房间(可能被 CF 拦截), 请稍后重试\n')
                return
            self._send(200, body, 'application/vnd.apple.mpegurl')
            return

        m = re.match(r'^/(\d+)\.m3u8$', path)
        if m:
            url = resolve_hls(m.group(1))
            if url:
                self.send_response(302)
                self.send_header('Location', url)
                self.end_headers()
                return
            self._send(503, '房间暂无可用流\n')
            return

        self._send(404, 'not found\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port', nargs='?', type=int, default=8768)
    args = ap.parse_args()
    # 启动时后台预热房间列表, 首个订阅请求直接命中缓存
    threading.Thread(target=refresh_cache, daemon=True).start()
    srv = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    print('stripchat-live 启动, 监听端口 %d' % args.port, flush=True)
    print('聚合订阅: http://127.0.0.1:%d/all.m3u' % args.port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
