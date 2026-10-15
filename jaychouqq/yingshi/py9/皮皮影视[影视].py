# -*- coding: utf-8 -*-
# 皮皮影视 www.ppys.live  (2026-10)
import sys, re, json
from urllib.parse import quote, unquote
sys.path.append('..')
from base.spider import Spider

HOST = 'https://www.ppys.live'
UA = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
HDR = {'User-Agent': UA, 'Referer': HOST + '/'}
CLASSES = [('2', '电影'), ('1', '电视剧'), ('4', '综艺'), ('3', '动漫'), ('26', '番剧'), ('5', '爽剧')]
BAN = re.compile(r'伦理|福利|午夜|写真|成人|三级')


class Spider(Spider):
    def getName(self):
        return '皮皮影视'

    def init(self, extend=''):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    def _get(self, path):
        r = self.fetch(HOST + path if path.startswith('/') else path, headers=HDR, timeout=8)
        r.encoding = 'utf-8'
        return r.text

    def _pic(self, u):
        u = (u or '').strip().replace('&amp;', '&')
        if not u:
            return ''
        m = re.search(r'img\.php\?url=(.+)$', u)
        if m:
            u = unquote(m.group(1))
        if 'huaqi.pro' in u and '?http' in u:
            u = u.split('?', 1)[1]
        if u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('/'):
            u = HOST + u
        if 'doubanio.com' in u:
            u += '@Referer=https://movie.douban.com/@User-Agent=' + UA
        return u

    def _cards(self, html):
        vods, seen = [], set()
        for m in re.finditer(r'<a class="[^"]*stui-vodlist__thumb[^"]*" href="/voddetail/(\d+)\.html" title="([^"]+)"[^>]*data-original="([^"]*)"[^>]*>(.*?)</a>', html, re.S):
            vid, name, pic, inner = m.groups()
            if vid in seen or BAN.search(name):
                continue
            seen.add(vid)
            rm = re.search(r'pic-text[^>]*>([^<]*)<', inner)
            vods.append({'vod_id': vid, 'vod_name': name, 'vod_pic': self._pic(pic),
                         'vod_remarks': rm.group(1).strip() if rm else ''})
        return vods

    def homeContent(self, filter):
        by = {'key': 'by', 'name': '排序', 'value': [{'n': '时间', 'v': 'time'}, {'n': '人气', 'v': 'hits'}, {'n': '评分', 'v': 'score'}]}
        years = {'key': 'year', 'name': '年份', 'value': [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': str(y)} for y in range(2026, 2009, -1)]}
        return {'class': [{'type_id': k, 'type_name': v} for k, v in CLASSES],
                'filters': {k: [by, years] for k, _ in CLASSES}}

    def homeVideoContent(self):
        try:
            return {'list': self._cards(self._get('/'))[:30]}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        ext = extend or {}
        url = '/vodshow/%s--%s------%s---%s.html' % (tid, ext.get('by', ''), pg if pg > 1 else '', ext.get('year', ''))
        vods = self._cards(self._get(url))
        return {'list': vods, 'page': pg, 'pagecount': pg + 1 if vods else pg, 'limit': len(vods), 'total': 9999}

    def detailContent(self, ids):
        vid = ids[0]
        html = self._get('/voddetail/%s.html' % vid)
        name = re.search(r'<h1 class="title">\s*([^<]+)', html)
        pic = re.search(r'stui-content__thumb.*?data-original="([^"]+)"', html, re.S)
        raw = ' '.join(re.findall(r'<p class="data[^"]*">(.*?)</p>', html, re.S))

        def field(k):
            m = re.search(k + r'：</span>(.*?)(?:<span class="(?:text-muted|split-line)|$)', raw, re.S)
            if not m:
                return ''
            links = re.findall(r'<a [^>]*>([^<]+)</a>', m.group(1))
            return ','.join(x.strip() for x in links) if links else re.sub(r'<[^>]+>|&nbsp;', '', m.group(1)).strip()
        desc = re.search(r'id="desc".*?<p class="col-pd">(.*?)</p>', html, re.S)
        tabs = re.findall(r'<a href="#([\w-]+)" data-toggle="tab">([^<]+)</a>', html)
        froms, urls = [], []
        for tid, tname in tabs:
            m = re.search(r'id="%s" class="tab-pane[^"]*">(.*?)</ul>' % re.escape(tid), html, re.S)
            if not m:
                continue
            eps = ['%s$%s' % (t.strip().replace('#', ' ').replace('$', ' '), p)
                   for p, t in re.findall(r'<a href="(/vodplay/[\d-]+\.html)">([^<]*)</a>', m.group(1))]
            if eps:
                froms.append(tname.strip())
                urls.append('#'.join(eps))
        vod = {'vod_id': vid, 'vod_name': name.group(1).strip() if name else '',
               'vod_pic': self._pic(pic.group(1)) if pic else '', 'type_name': field('类型'),
               'vod_area': field('地区'), 'vod_year': field('年份'), 'vod_actor': field('主演'),
               'vod_director': field('导演'), 'vod_remarks': field('更新'),
               'vod_content': re.sub(r'<[^>]+>|&nbsp;', '', desc.group(1)).strip() if desc else '',
               'vod_play_from': '$$$'.join(froms), 'vod_play_url': '$$$'.join(urls)}
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        pg = int(pg or 1)
        html = self._get('/vodsearch/%s----------%s---.html' % (quote(key), pg if pg > 1 else ''))
        vods, seen = [], set()
        for m in re.finditer(r'class="v-thumb stui-vodlist__thumb[^"]*" href="/voddetail/(\d+)\.html" title="([^"]+)"[^>]*data-original="([^"]*)"[^>]*>(.*?)</a>', html, re.S):
            vid, name, pic, inner = m.groups()
            if vid in seen or BAN.search(name):
                continue
            seen.add(vid)
            rm = re.search(r'pic-text[^>]*>([^<]*)<', inner)
            vods.append({'vod_id': vid, 'vod_name': name, 'vod_pic': self._pic(pic), 'vod_remarks': rm.group(1).strip() if rm else ''})
        return {'list': vods, 'page': pg}

    def playerContent(self, flag, id, vipFlags):
        try:
            html = self._get(id)
            j = json.loads(re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S).group(1))
            url = j.get('url', '')
            enc = str(j.get('encrypt', '0'))
            if enc == '1':
                url = unquote(url)
            elif enc == '2':
                import base64
                url = unquote(base64.b64decode(url).decode())
            if re.search(r'\.(m3u8|mp4)', url):
                return {'parse': 0, 'jx': 0, 'url': url, 'header': {'User-Agent': UA}}
            return {'parse': 1, 'jx': 1, 'url': url or HOST + id, 'header': HDR}
        except Exception:
            return {'parse': 1, 'jx': 0, 'url': HOST + id, 'header': HDR}
