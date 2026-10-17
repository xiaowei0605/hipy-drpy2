# -*- coding: utf-8 -*-
# IDNFLIX Spider v7.5 - SSL Bypass + Rumble/Vidlink Direct
import re, os, time, json, datetime, traceback
import requests
import urllib3
from urllib.parse import urlparse, urljoin, quote, unquote
from bs4 import BeautifulSoup
from base.spider import Spider

# Suppress SSL warnings (karena kita verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENABLE_LOG_FILE = True


class _SimpleTTLCache:
    def __init__(self, maxsize=300, ttl=7200):
        self._d, self._m, self._t = {}, maxsize, ttl
    def __contains__(self, k):
        if k in self._d:
            ts, _ = self._d[k]
            if time.time() - ts < self._t: return True
            del self._d[k]
        return False
    def __getitem__(self, k): return self._d[k][1]
    def __setitem__(self, k, v):
        if len(self._d) >= self._m:
            del self._d[min(self._d.items(), key=lambda x: x[1][0])[0]]
        self._d[k] = (time.time(), v)
    def clear(self): self._d.clear()


class Spider(Spider):
    LOG_FILE = '/sdcard/Download/idnflix_log.txt'

    PLAYER_PATTERNS = [
        'vidsrc.', 'vidlink.', 'vidplay.', 'vidsrcs.', 'rumble.',
        'vidsrc2.', 'vidsrc.sh', 'vidcloud', 'embed.su', 'autoembed.',
        'filemoon', 'streamhide', 'dood.', 'voe.sx',
        '/embed/', '/e/', '/v/', '/player/',
    ]

    SERVER_PRIORITY = [
        'Vidlink', 'Rumble', 'Vidsrc2', 'Vidsrc', 'Vidsrcs', 'Vidsrc.sh',
        'Vidplay', 'Embed', 'Vidcloud', 'Filemoon',
        'Streamhide', 'Dood', 'Voe', 'Other'
    ]

    RELIABLE_SERVERS = set()
    SKIP_SERVERS = set()

    SERVER_HEADERS = {
        'Vidlink':    ('https://vidlink.pro/',  'https://vidlink.pro'),
        'Rumble':     ('https://rumble.com/',   'https://rumble.com'),
        'Vidsrc2':    ('https://vidsrc2.ru/',   'https://vidsrc2.ru'),
        'Vidsrc':     ('https://vidsrc.xyz/',   'https://vidsrc.xyz'),
        'Vidsrcs':    ('https://vidsrcs.com/',  'https://vidsrcs.com'),
        'Vidsrc.sh':  ('https://vidsrc.sh/',    'https://vidsrc.sh'),
        'Vidplay':    ('https://vidplay.online/', 'https://vidplay.online'),
        'Vidcloud':   ('https://vidcloud9.com/', 'https://vidcloud9.com'),
        'Embed':      ('https://embed.su/',     'https://embed.su'),
        'Filemoon':   ('https://filemoon.sx/',  'https://filemoon.sx'),
        'Streamhide': ('https://streamhide.to/', 'https://streamhide.to'),
        'Dood':       ('https://dood.li/',      'https://dood.li'),
        'Voe':        ('https://voe.sx/',       'https://voe.sx'),
    }

    def init(self, extend=""):
        self.log(f'===== INIT v7.5 =====')
        if ENABLE_LOG_FILE:
            try:
                with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                    f.write(f"=== IDNFLIX Spider v7.5 ===\n{datetime.datetime.now()}\n\n")
            except Exception: pass

        self.site = 'https://idnflix.com'
        self.ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')
        self.site_headers = {
            'User-Agent': self.ua,
            'referer': f'{self.site}/',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        self.url_cache = _SimpleTTLCache(maxsize=500, ttl=600)
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.log('===== INIT DONE v7.5 =====')

    def getName(self): return "IDNFLIX"
    def isVideoFormat(self, url):
        return any(e in (url or '').lower() for e in ['.m3u8', '.mp4', '.mkv', '.txt'])
    def manualVideoCheck(self): return True
    def destroy(self):
        try:
            self.session.close()
            self.url_cache.clear()
        except Exception: pass

    def log(self, msg, level="INFO"):
        try:
            line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}"
            print(f"[IDNFLIX] {line}")
            if ENABLE_LOG_FILE:
                try:
                    with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                        f.write(line + '\n')
                except Exception: pass
        except Exception: pass

    def _abs(self, href):
        if not href: return ''
        if href.startswith('http'): return href
        if href.startswith('//'): return 'https:' + href
        return urljoin(self.site, href)

    def _make_id(self, href):
        try:
            if href.startswith(self.site):
                p = urlparse(href)
                path = p.path + (('?' + p.query) if p.query else '')
                return quote(path, safe='/?=&%')
            return href
        except Exception: return href

    def _is_player_link(self, href):
        if not href: return False
        low = href.lower()
        if any(p in low for p in self.PLAYER_PATTERNS): return True
        if re.search(r'/eps?/|/watch/|/episode/', low): return True
        return False

    def _fix_player_url(self, url):
        if not url: return url
        if '?' not in url and '&' in url:
            m = re.match(r'^(https?://[^/]+/[^?&]+)(&.*)$', url)
            if m:
                url = m.group(1) + '?' + m.group(2)[1:]
        return url

    def _classify_server(self, url):
        if not url: return 'Other'
        low = url.lower()
        if 'vidlink' in low: return 'Vidlink'
        if 'rumble' in low: return 'Rumble'
        if 'vidsrc.sh' in low: return 'Vidsrc.sh'
        if 'vidsrc2' in low: return 'Vidsrc2'
        if 'vidsrcs' in low: return 'Vidsrcs'
        if 'vidsrc' in low: return 'Vidsrc'
        if 'vidplay' in low: return 'Vidplay'
        if 'vidcloud' in low: return 'Vidcloud'
        if 'embed.su' in low or 'autoembed' in low: return 'Embed'
        if 'filemoon' in low: return 'Filemoon'
        if 'streamhide' in low: return 'Streamhide'
        if 'dood.' in low: return 'Dood'
        if 'voe.sx' in low: return 'Voe'
        return 'Other'

    def _headers_for_server(self, server_name):
        clean = server_name.replace('★', '').strip()
        ref, origin = self.SERVER_HEADERS.get(clean, ('https://idnflix.com/', 'https://idnflix.com'))
        return {
            'User-Agent': self.ua,
            'Referer': ref,
            'Origin': origin,
            'Accept': '*/*',
        }

    # ============================================================
    # FETCH dengan SSL Bypass Option
    # ============================================================
    def _fetch_with_bypass(self, url, headers=None, timeout=10, verify_ssl=True):
        """Fetch dengan option bypass SSL verification."""
        headers = headers or self.site_headers
        try:
            r = self.session.get(url, headers=headers, timeout=timeout,
                                 allow_redirects=True, verify=verify_ssl)
            self.log(f'[fetch {r.status_code}] len={len(r.content)} {url[:90]}')
            return r
        except requests.exceptions.SSLError as e:
            self.log(f'[fetch SSL ERR] {e}', level="WARN")
            if verify_ssl:
                # Retry tanpa verify
                self.log(f'[fetch] retry with verify=False')
                return self._fetch_with_bypass(url, headers, timeout, verify_ssl=False)
            return None
        except Exception as e:
            self.log(f'[fetch ERR] {e}', level="WARN")
            return None

    def fetch(self, url, headers=None, timeout=10, retry=1):
        headers = headers or self.site_headers
        last = None
        for att in range(retry + 1):
            try:
                if att > 0: time.sleep(0.2 * att)
                r = self.session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                self.log(f'[fetch {r.status_code}] len={len(r.content)} {url[:90]}')
                return r
            except requests.exceptions.Timeout as e:
                last = e; self.log(f'[fetch TIMEOUT {att+1}] {url[:90]}')
            except requests.exceptions.RequestException as e:
                last = e; self.log(f'[fetch ERR {att+1}] {e}')
        if last: raise last

    # ============================================================
    # EXTRACT RUMBLE — with SSL Bypass
    # ============================================================
    def _extract_rumble(self, rumble_url):
        try:
            m = re.search(r'/embed/([a-zA-Z0-9]+)', rumble_url)
            if not m:
                return None
            video_id = m.group(1)
            pub = ''
            m2 = re.search(r'[?&]pub=([a-zA-Z0-9]+)', rumble_url)
            if m2: pub = m2.group(1)
            
            self.log(f'[rumble] video_id={video_id}, pub={pub}')
            
            # API URLs — pakai SSL bypass
            api_urls = [
                f'https://rumble.com/api/v1.0/embed/{video_id}?pub={pub}',
                f'https://rumble.com/api/v1.0/embed/{video_id}',
                f'https://rumble.com/embedJS/u3/?request=video&ver=2&v={video_id}',
            ]
            
            for api_url in api_urls:
                try:
                    self.log(f'[rumble] trying {api_url}')
                    hdrs = {
                        'User-Agent': self.ua,
                        'Referer': rumble_url,
                        'Origin': 'https://rumble.com',
                        'Accept': 'application/json, text/plain, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                    }
                    r = self._fetch_with_bypass(api_url, hdrs, timeout=10, verify_ssl=False)
                    if not r or r.status_code != 200:
                        continue
                    
                    try:
                        j = r.json()
                        self.log(f'[rumble] JSON keys: {list(j.keys())[:10]}')
                        
                        # Cari m3u8/mp4
                        m3u8 = self._find_m3u8_deep(j)
                        if m3u8:
                            self.log(f'[rumble] FOUND m3u8: {m3u8[:100]}')
                            return m3u8
                        
                        mp4 = self._find_mp4_deep(j)
                        if mp4:
                            self.log(f'[rumble] FOUND mp4: {mp4[:100]}')
                            return mp4
                        
                        # Kalau ada key 'u' atau 'ua' (Rumble format)
                        if 'u' in j and isinstance(j['u'], dict):
                            for k in ['mp4', 'hls', 'sd', 'hd']:
                                if k in j['u']:
                                    v = j['u'][k]
                                    if isinstance(v, dict):
                                        for sub in v.values():
                                            if isinstance(sub, str) and ('http' in sub):
                                                self.log(f'[rumble] FOUND in u.{k}: {sub[:100]}')
                                                return sub
                                    elif isinstance(v, str) and 'http' in v:
                                        return v
                    except Exception as e:
                        self.log(f'[rumble] JSON err: {e}')
                        
                        # Fallback: cari di raw text
                        m3u8 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', r.text)
                        if m3u8:
                            self.log(f'[rumble] m3u8 raw: {m3u8.group(1)[:100]}')
                            return m3u8.group(1)
                        
                        mp4 = re.search(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', r.text)
                        if mp4:
                            self.log(f'[rumble] mp4 raw: {mp4.group(1)[:100]}')
                            return mp4.group(1)
                except Exception as e:
                    self.log(f'[rumble] api err: {e}')
                    continue
            
            self.log(f'[rumble] all attempts failed', level="WARN")
        except Exception as e:
            self.log(f'[rumble] err: {e}')
        return None

    # ============================================================
    # EXTRACT VIDLINK
    # ============================================================
    def _extract_vidlink(self, vidlink_url):
        try:
            m = re.search(r'/(movie|tv)/(\d+)', vidlink_url)
            if not m:
                return None
            media_type = m.group(1)
            tmdb_id = m.group(2)
            self.log(f'[vidlink] {media_type} id={tmdb_id}')
            
            api_urls = [
                f'https://vidlink.pro/api/b/{media_type}/{tmdb_id}',
                f'https://vidlink.pro/api/{media_type}/{tmdb_id}',
            ]
            
            for api_url in api_urls:
                try:
                    self.log(f'[vidlink] trying {api_url}')
                    hdrs = {
                        'User-Agent': self.ua,
                        'Referer': vidlink_url,
                        'Origin': 'https://vidlink.pro',
                        'Accept': 'application/json, text/plain, */*',
                    }
                    r = self._fetch_with_bypass(api_url, hdrs, timeout=10, verify_ssl=False)
                    if not r or r.status_code != 200:
                        continue
                    
                    try:
                        j = r.json()
                        self.log(f'[vidlink] JSON keys: {list(j.keys())[:10]}')
                        
                        m3u8 = self._find_m3u8_deep(j)
                        if m3u8:
                            self.log(f'[vidlink] FOUND m3u8: {m3u8[:100]}')
                            return m3u8
                    except Exception as e:
                        self.log(f'[vidlink] JSON err: {e}')
                        m3u8 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', r.text)
                        if m3u8:
                            return m3u8.group(1)
                except Exception as e:
                    self.log(f'[vidlink] api err: {e}')
                    continue
        except Exception as e:
            self.log(f'[vidlink] err: {e}')
        return None

    def _find_m3u8_deep(self, data):
        if isinstance(data, str):
            if '.m3u8' in data and data.startswith('http'):
                return data
        elif isinstance(data, dict):
            for k, v in data.items():
                kl = k.lower()
                if kl in ('url', 'file', 'source', 'src', 'm3u8', 'stream', 'hls', 'playlist'):
                    if isinstance(v, str) and '.m3u8' in v:
                        return v
                r = self._find_m3u8_deep(v)
                if r: return r
        elif isinstance(data, list):
            for item in data:
                r = self._find_m3u8_deep(item)
                if r: return r
        return None

    def _find_mp4_deep(self, data):
        if isinstance(data, str):
            if '.mp4' in data and data.startswith('http'):
                return data
        elif isinstance(data, dict):
            for k, v in data.items():
                kl = k.lower()
                if kl in ('url', 'file', 'source', 'src', 'mp4', 'video'):
                    if isinstance(v, str) and '.mp4' in v:
                        return v
                r = self._find_mp4_deep(v)
                if r: return r
        elif isinstance(data, list):
            for item in data:
                r = self._find_mp4_deep(item)
                if r: return r
        return None

    # ============================================================
    # HOME / DETAIL / SEARCH
    # ============================================================
    def homeContent(self, filter):
        classes = [
            {'type_name': '🎬 Film',      'type_id': 'kategori/film'},
            {'type_name': '📺 TV Series', 'type_id': 'kategori/tv-series'},
            {'type_name': '🔞 18+',       'type_id': 'kategori/18-keatas'},
            {'type_name': '🐉 Donghua',   'type_id': 'kategori/donghua'},
            {'type_name': 'Action',       'type_id': 'jenis/action'},
            {'type_name': 'Comedy',       'type_id': 'jenis/comedy'},
            {'type_name': 'Drama',        'type_id': 'jenis/drama'},
            {'type_name': 'Horror',       'type_id': 'jenis/horror'},
            {'type_name': 'Romance',      'type_id': 'jenis/romance'},
            {'type_name': 'Sci-Fi',       'type_id': 'jenis/sci-fi'},
            {'type_name': 'Thriller',     'type_id': 'jenis/thriller'},
            {'type_name': 'Korea Selatan','type_id': 'negara/korea-selatan'},
            {'type_name': 'Jepang',       'type_id': 'negara/jepang'},
            {'type_name': 'USA',          'type_id': 'negara/usa'},
            {'type_name': '2024',         'type_id': 'tahun/2024'},
            {'type_name': '2025',         'type_id': 'tahun/2025'},
        ]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            r = self.fetch(self.site + '/', timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            return {'list': self._parse_items(soup, 40)}
        except Exception as e:
            self.log(f'[homeVideo] {e}')
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            if tid.startswith('sep'): return {'list': [], 'page':1, 'pagecount':1, 'limit':40, 'total':0}
            base = f"{self.site}/{tid}"
            if str(pg) != '1': base += f"?page={pg}"
            r = self.fetch(base, timeout=12)
            soup = BeautifulSoup(r.text, 'html.parser')
            items = self._parse_items(soup, 40)
            return {'list': items, 'page': int(pg), 'pagecount': int(pg)+1, 'limit': 40, 'total': 999999}
        except Exception as e:
            self.log(f'[category] ERROR: {e}')
            return {'list': [], 'page':1, 'pagecount':1, 'limit':40, 'total':0}

    def _parse_items(self, soup, limit=40):
        items, seen = [], set()
        covers = soup.select('a.item__cover[href]')
        if not covers: covers = soup.select('a[href*="/movie/"]')
        for cover in covers:
            if len(items) >= limit: break
            href = cover.get('href', '').strip()
            if not href or href in seen: continue
            if '/movie/' not in href: continue
            seen.add(href)
            vid = self._make_id(href)
            img = cover.find('img')
            pic = self._abs(img.get('src', '')) if img else ''
            title = (img.get('alt', '') if img else '').strip()
            parent = cover.find_parent('div', class_='item')
            if parent:
                h3 = parent.select_one('h3.item__title a')
                if h3: title = h3.get_text(strip=True) or title
            if title:
                items.append({'vod_id': vid, 'vod_name': title, 'vod_pic': pic})
        return items

    def detailContent(self, ids):
        try:
            path = ids[0]
            url = self._abs(path)
            r = self.fetch(url, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
            title = ''
            h1 = soup.select_one('h1.section__title--head') or soup.find('h1')
            if h1: title = h1.get_text(strip=True)
            pic = ''
            bg = soup.select_one('.section__details-bg')
            if bg and bg.get('data-bg'): pic = bg['data-bg']
            year = ''
            yl = soup.select_one('.item__meta a[href*="/tahun/"]')
            if yl: year = yl.get_text(strip=True)
            desc = ''
            de = soup.select_one('.item__description p, .item__description')
            if de: desc = de.get_text(strip=True)[:1500]
            play_urls = []
            seen = set()
            for a in soup.select('ul.episode li.list-item a[href]'):
                href = a.get('href', '').strip()
                if not href or href in seen: continue
                if not self._is_player_link(href): continue
                seen.add(href)
                label = a.get_text(' ', strip=True)[:40] or f'Ep {len(play_urls)+1}'
                play_urls.append((label, href))
            if not play_urls: return {'list': []}
            servers = {}
            for label, p in play_urls:
                srv = self._classify_server(p)
                servers.setdefault(srv, []).append((label, p))
            from_list, url_list = [], []
            for srv in self.SERVER_PRIORITY:
                if srv not in servers: continue
                eps = servers[srv]
                from_list.append(srv)
                url_list.append('#'.join(f"{l}${u}" for l, u in eps))
            if not from_list: return {'list': []}
            return {'list': [{
                'vod_id': path, 'vod_name': title, 'vod_pic': pic,
                'vod_year': year, 'vod_content': desc,
                'vod_play_from': '$$$'.join(from_list),
                'vod_play_url': '$$$'.join(url_list),
            }]}
        except Exception as e:
            self.log(f'[detail] ERROR: {e}')
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        try:
            if not key: return {'list': [], 'page': 1, 'pagecount': 1}
            url = f"{self.site}/?search={quote(key)}"
            r = self.fetch(url, timeout=12)
            soup = BeautifulSoup(r.text, 'html.parser')
            return {'list': self._parse_items(soup, 40), 'page': 1, 'pagecount': 1}
        except Exception as e:
            return {'list': [], 'page': 1, 'pagecount': 1}

    def playerContent(self, flag, id, vipFlags):
        self.log(f'===== player: flag={flag!r} id={id[:120]} =====')
        try:
            id = unquote(id)
            url = self._fix_player_url(self._abs(id))
            self.log(f'[player] url={url}')

            if self.isVideoFormat(url):
                hdr = self._headers_for_server(flag)
                return {'parse': 0, 'url': url, 'header': hdr}

            low = url.lower()
            
            if 'rumble.com' in low:
                self.log(f'[player] RUMBLE extract')
                direct = self._extract_rumble(url)
                if direct:
                    self.log(f'[player] RUMBLE m3u8 OK')
                    return {
                        'parse': 0, 'url': direct,
                        'header': {
                            'User-Agent': self.ua,
                            'Referer': 'https://rumble.com/',
                            'Origin': 'https://rumble.com',
                        }
                    }
            
            if 'vidlink.pro' in low:
                self.log(f'[player] VIDLINK extract')
                direct = self._extract_vidlink(url)
                if direct:
                    self.log(f'[player] VIDLINK m3u8 OK')
                    return {
                        'parse': 0, 'url': direct,
                        'header': {
                            'User-Agent': self.ua,
                            'Referer': 'https://vidlink.pro/',
                            'Origin': 'https://vidlink.pro',
                        }
                    }
            
            hdr = self._headers_for_server(flag)
            return {'parse': 1, 'url': url, 'header': hdr}
        except Exception as e:
            self.log(f'[player] ERROR: {e}')
            return {'parse': 1, 'url': self._abs(id), 'header': {'User-Agent': self.ua}}

    def localProxy(self, param):
        try:
            url = unquote(param.get('url', ''))
            if not url: return [400, 'text/plain', b'missing url']
            return [302, 'text/plain', b''], {'Location': url}
        except Exception as e:
            return [500, 'text/plain', str(e).encode()]