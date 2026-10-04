# -*- coding: utf-8 -*-
import re
import requests
import json
import time
import base64
import urllib3
from urllib.parse import quote, urljoin, urlparse, unquote
from bs4 import BeautifulSoup
from base.spider import Spider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Spider(Spider):
    def init(self, extend=""):
        self.site = 'https://lk21.de'
        self.site_name = 'LK21'
        
        self.site_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': self.site,
        }
        
        self.session = requests.Session()
        self._img_cache = {}
        self._pc_cache = {}
        
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.server_priority = [
            'TURBOVIP', 'P2P', 'CAST', 'HYDRAX',
            'VIDSRC', 'FILEMOON', 'STREAMTAPE', 'DOODSTREAM',
            'MIXDROP', 'UPSTREAM', 'MP4UPLOAD', 'VIDGUARD',
        ]
        
        self.log("LK21 Spider Started - Deep Resolver Version")

    def getName(self):
        return "🎬 LK21"

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(ext in url.lower() for ext in ['.m3u8', '.mp4'])

    def manualVideoCheck(self):
        return True

    # ================================================================
    # HOME CONTENT
    # ================================================================
    def homeContent(self, filter):
        return {
            'class': [
                {'type_id': 'latest', 'type_name': '🆕 Post Terbaru'},
                {'type_id': 'populer', 'type_name': '🔥 Terpopuler'},
                {'type_id': 'rating', 'type_name': '⭐ Rating'},
                {'type_id': 'release', 'type_name': '📅 Urut Tahun'},
                {'type_id': 'most-commented', 'type_name': '💬 Komen Terbanyak'},
                {'type_id': 'nontondrama', 'type_name': '📺 Series'},
                {'type_id': 'genre-action', 'type_name': '⚔️ Action'},
                {'type_id': 'genre-comedy', 'type_name': '😂 Comedy'},
                {'type_id': 'genre-drama', 'type_name': '🎭 Drama'},
                {'type_id': 'genre-horror', 'type_name': '👻 Horror'},
                {'type_id': 'genre-romance', 'type_name': '💕 Romance'},
                {'type_id': 'genre-thriller', 'type_name': '😱 Thriller'},
                {'type_id': 'genre-animation', 'type_name': '🎨 Animation'},
                {'type_id': 'genre-scifi', 'type_name': '🚀 Sci-Fi'},
                {'type_id': 'country-usa', 'type_name': '🇺🇸 Amerika'},
                {'type_id': 'country-uk', 'type_name': '🇬🇧 Inggris'},
                {'type_id': 'country-japan', 'type_name': '🇯🇵 Jepang'},
                {'type_id': 'country-south-korea', 'type_name': '🇰🇷 Korea'},
                {'type_id': 'country-china', 'type_name': '🇨🇳 Cina'},
                {'type_id': 'country-india', 'type_name': '🇮🇳 India'},
                {'type_id': 'year-2026', 'type_name': '📆 2026'},
                {'type_id': 'year-2025', 'type_name': '📆 2025'},
                {'type_id': 'year-2024', 'type_name': '📆 2024'},
            ],
            'filters': {}
        }

    # ================================================================
    # IMAGE PROXY
    # ================================================================
    def _proxy_img(self, url):
        if not url:
            return ''
        try:
            b64 = base64.urlsafe_b64encode(url.encode('utf-8')).decode('ascii')
            pb = self.getProxyUrl(local=True)
            sep = '&' if '?' in pb else '?'
            return f"{pb}{sep}m=img&u={b64}"
        except Exception:
            return url

    def localProxy(self, param):
        if isinstance(param, str):
            try:
                param = json.loads(param)
            except Exception:
                param = {}
        if not isinstance(param, dict) or param.get('m') != 'img':
            return [404, 'text/plain', b'']
        
        u = (param.get('u') or '').strip()
        if not u:
            return [404, 'text/plain', b'']
        
        try:
            raw = base64.urlsafe_b64decode(u + '=' * (-len(u) % 4)).decode('utf-8')
        except Exception:
            return [404, 'text/plain', b'']
        
        if raw in self._img_cache:
            return self._img_cache[raw]
        
        try:
            headers = {
                'User-Agent': self.site_headers['User-Agent'],
                'Referer': 'https://poster.assetsy.de/',
                'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            }
            
            r = self.session.get(raw, headers=headers, timeout=20, verify=False)
            
            if r.status_code != 200 or not r.content:
                return [404, 'text/plain', b'']
            
            ct = (r.headers.get('Content-Type', '') or 'image/jpeg').split(';')[0].strip() or 'image/jpeg'
            result = [200, ct, r.content]
            
            if len(self._img_cache) < 50:
                self._img_cache[raw] = result
            
            return result
        except Exception as e:
            self.log(f"img proxy error: {e}")
            return [404, 'text/plain', b'']

    # ================================================================
    # FETCH
    # ================================================================
    def fetch(self, url, headers=None, timeout=15, max_retries=2):
        headers = headers or self.site_headers
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    time.sleep(1.5 * attempt)
                
                resp = self.session.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
                if resp.status_code == 200:
                    resp.encoding = 'utf-8'
                    return resp
            except Exception as e:
                self.log(f"Fetch attempt {attempt+1} failed: {e}")
        
        class Dummy:
            text = ''
            status_code = 0
        return Dummy()

    # ================================================================
    # HOME VIDEO
    # ================================================================
    def homeVideoContent(self):
        try:
            resp = self.fetch(self.site)
            if not resp or not resp.text:
                return {'list': []}
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            seen_keys = set()
            
            articles = soup.select('article') or soup.select('.gallery-grid article, .post, .ml-item, .slider')
            
            for article in articles[:50]:
                try:
                    video = self._parse_video_item(article)
                    if not video:
                        continue
                    ck = f"{video['vod_name']}_{video['vod_year']}"
                    if ck in seen_keys:
                        continue
                    seen_keys.add(ck)
                    items.append(video)
                except Exception:
                    continue
            
            return {'list': items[:40]}
        except Exception as e:
            self.log(f"Home error: {e}")
            return {'list': []}

    # ================================================================
    # PARSE VIDEO ITEM
    # ================================================================
    def _parse_video_item(self, item):
        try:
            link = item.find('a', href=True)
            if not link:
                return None
            
            href = link.get('href', '').strip()
            if not href or 'javascript:' in href or href.startswith('#'):
                return None
            
            href_lower = href.lower()
            if any(p in href_lower for p in ['/genre/', '/country/', '/year/', '/page/', 
                                              '/populer', '/rating', '/latest', '/release',
                                              '/faq', '/dmca', '/privacy', '/search']):
                return None
            
            url = href if href.startswith('http') else self._abs_url(href)
            
            title = ''
            title_elem = item.select_one('h3.poster-title, .poster-title, h3, .video-title, .tt h2, .tt')
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            if not title:
                img = item.find('img')
                if img and img.get('alt'):
                    title = img.get('alt', '').strip()
            
            if not title:
                return None
            
            img_url = ''
            img = item.find('img')
            if img:
                img_url = (img.get('src') or img.get('data-src') or 
                          img.get('data-lazy-src') or img.get('data-srcset') or '')
                if img_url and ',' in img_url and 'http' in img_url:
                    img_url = img_url.split(',')[0].strip().split(' ')[0]
            
            year = ''
            year_elem = item.select_one('.year, [itemprop="datePublished"], .video-year')
            if year_elem:
                ym = re.search(r'(20\d{2}|19\d{2})', year_elem.get_text())
                if ym:
                    year = ym.group(1)
            if not year:
                ym = re.search(r'\((\d{4})\)', title)
                if ym:
                    year = ym.group(1)
            
            remarks = ''
            label_elem = item.select_one('.label, .quality, .badge, .duration, .rating')
            if label_elem:
                remarks = label_elem.get_text(strip=True)
            
            if img_url:
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                elif img_url.startswith('/'):
                    img_url = self.site + img_url
            
            clean_title = self._clean_title(title)
            
            return {
                'vod_id': url,
                'vod_name': clean_title[:100] if clean_title else 'Unknown',
                'vod_pic': self._proxy_img(img_url[:300] if img_url else ''),
                'vod_year': year,
                'vod_remarks': remarks[:20] if remarks else 'HD'
            }
        except Exception:
            return None

    def _clean_title(self, title):
        if not title:
            return ''
        patterns = [
            r'\([^)]*\)', r'\[[^\]]*\]',
            r'Nonton\s+', r'Streaming\s+', r'Download\s+',
            r'Sub\s+Indo', r'Subtitle\s+Indonesia', r'LK21', r'Layarkaca21',
            r'\d{3,4}p', r'\bHD\b', r'\bFHD\b', r'BluRay', r'WEB-DL', r'WEBRip',
            r'\s+di\s+Lk21.*$', r'\s+di\s*$', r'^Film\s+', r'^Movie\s+',
        ]
        clean = title
        for pattern in patterns:
            clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean if clean else title.strip()

    # ================================================================
    # CATEGORY
    # ================================================================
    def _get_category_url(self, tid, pg):
        pg = int(pg) if pg else 1
        if tid == 'latest':
            base = '/latest/'
        elif tid == 'rating':
            base = '/rating/'
        elif tid == 'release':
            base = '/release/'
        elif tid == 'populer':
            base = '/populer/'
        elif tid == 'most-commented':
            base = '/most-commented/'
        elif tid == 'nontondrama':
            base = '/nontondrama/'
        elif tid.startswith('genre-'):
            base = f"/genre/{tid.replace('genre-', '')}/"
        elif tid.startswith('country-'):
            base = f"/country/{tid.replace('country-', '')}/"
        elif tid.startswith('year-'):
            base = f"/year/{tid.replace('year-', '')}/"
        else:
            return f"{self.site}/search/?s={quote(tid)}"
        
        if pg > 1:
            return f"{self.site}{base}page/{pg}/"
        return f"{self.site}{base}"

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
            url = self._get_category_url(tid, pg)
            self.log(f"Category '{tid}' page {pg}")
            
            resp = self.fetch(url)
            if not resp or not resp.text:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 40, 'total': 0}
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            seen_keys = set()
            
            articles = soup.select('article') or soup.select('.gallery-grid article, .post, .ml-item, .slider')
            
            for article in articles:
                video = self._parse_video_item(article)
                if not video:
                    continue
                ck = f"{video['vod_name']}_{video['vod_year']}"
                if ck in seen_keys:
                    continue
                seen_keys.add(ck)
                items.append(video)
            
            pagecount = self._get_pagecount(soup, url, pg)
            
            return {'list': items, 'page': pg, 'pagecount': pagecount, 'limit': 40, 'total': len(items)}
        except Exception as e:
            self.log(f"Category error: {e}")
            return {'list': [], 'page': int(pg) if pg else 1, 'pagecount': 1, 'limit': 40, 'total': 0}

    def _get_pagecount(self, soup, current_url=None, current_page=1):
        try:
            pagination = (
                soup.find('nav', class_='pagination-wrapper') or
                soup.find('ul', class_='pagination') or
                soup.find('div', class_='pagination') or
                soup.find('nav', class_='navigation') or
                soup.find('div', class_='wp-pagenavi') or
                soup.find('div', class_='hpage')
            )
            
            if pagination:
                pages = []
                for link in pagination.find_all('a'):
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        pages.append(int(text))
                    else:
                        m = re.search(r'/page/(\d+)/', href)
                        if m:
                            pages.append(int(m.group(1)))
                if pages:
                    return max(pages)
            
            next_link = soup.find('a', string=re.compile(r'Next|»|›|Berikutnya', re.IGNORECASE))
            if next_link and next_link.get('href'):
                m = re.search(r'/page/(\d+)/', next_link.get('href'))
                if m:
                    return int(m.group(1))
                return current_page + 1
            
            return current_page
        except Exception:
            return current_page

    # ================================================================
    # DETECT SERVERS
    # ================================================================
    def _detect_servers(self, soup):
        groups = {}
        
        def _add(server, url):
            if not server or not url:
                return
            server = str(server).strip().upper()
            url = str(url).strip()
            if not server or not url:
                return
            if server not in groups:
                groups[server] = []
            if url not in groups[server]:
                groups[server].append(url)
        
        for a in soup.select('#player-list li a'):
            server = (a.get('data-server') or a.get_text(strip=True) or '').strip()
            url = a.get('data-url') or a.get('href') or ''
            _add(server, url)
        
        for opt in soup.select('select#player-select option'):
            server = opt.get('data-server', '').strip()
            if not server:
                txt = opt.get_text(strip=True).replace('GANTI PLAYER', '').strip()
                server = txt
            url = opt.get('value', '').strip()
            _add(server, url)
        
        for a in soup.find_all('a', attrs={'data-server': True}):
            server = a.get('data-server', '').strip()
            url = a.get('data-url') or a.get('href') or ''
            _add(server, url)
        
        for script in soup.find_all('script'):
            if not script.string:
                continue
            content = script.string
            for m in re.findall(r'(https?://[^\s"\']+/iframe\d*/([a-zA-Z0-9_-]+)/[^\s"\']+)', content):
                _add(m[1].upper(), m[0])
        
        main_iframe = soup.select_one('iframe#main-player')
        if main_iframe and main_iframe.get('src'):
            url = main_iframe['src']
            server_guess = 'MAIN'
            m = re.search(r'/iframe\d*/([a-zA-Z0-9_-]+)/', url)
            if m:
                server_guess = m.group(1).upper()
            _add(server_guess, url)
        
        for iframe in soup.find_all('iframe', src=True):
            src = iframe.get('src', '')
            if any(k in src.lower() for k in ['iframe', 'player', 'embed', 'videonode', '/p2p/', '/cast/', '/hydrax/']):
                server_guess = 'IFRAME'
                m = re.search(r'/iframe\d*/([a-zA-Z0-9_-]+)/', src)
                if m:
                    server_guess = m.group(1).upper()
                _add(server_guess, src)
        
        return groups

    def _order_servers(self, servers_dict):
        ordered = []
        used = set()
        for pref in self.server_priority:
            if pref in servers_dict:
                ordered.append(pref)
                used.add(pref)
        for name in servers_dict:
            if name not in used:
                ordered.append(name)
        return ordered

    # ================================================================
    # DETAIL CONTENT
    # ================================================================
    def detailContent(self, ids):
        try:
            if not ids:
                return {'list': []}
            
            path = ids[0]
            full_url = self._abs_url(path)
            self.log(f"Detail: {full_url}")
            
            resp = self.fetch(full_url)
            if not resp or not resp.text:
                return {'list': []}
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            title = ''
            pic = ''
            year = ''
            rating = ''
            
            watch_json = soup.find('script', id='watch-history-data')
            if watch_json and watch_json.string:
                try:
                    data = json.loads(watch_json.string)
                    title = data.get('title', '')
                    pic = data.get('poster', '')
                    year = str(data.get('year', ''))
                    rating = str(data.get('rating', ''))
                except Exception:
                    pass
            
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)
                    title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
            
            if not pic:
                meta_img = soup.find('meta', property='og:image')
                if meta_img:
                    pic = meta_img.get('content', '')
            
            if not year:
                h1 = soup.find('h1')
                if h1:
                    m = re.search(r'\((\d{4})\)', h1.get_text())
                    if m:
                        year = m.group(1)
            
            sinopsis = ''
            synopsis_elem = soup.select_one('.synopsis')
            if synopsis_elem:
                sinopsis = synopsis_elem.get_text(strip=True)[:800]
            if not sinopsis:
                meta_desc = soup.find('meta', {'name': 'description'})
                if meta_desc:
                    sinopsis = meta_desc.get('content', '')[:800]
            
            server_groups = self._detect_servers(soup)
            
            self.log(f"🔍 Server terdeteksi: {list(server_groups.keys())}")
            
            ordered_servers = self._order_servers(server_groups)
            
            play_from_list = []
            play_url_list = []
            
            for server_name in ordered_servers:
                urls = server_groups[server_name]
                if not urls:
                    continue
                
                ep_group = []
                for idx, url in enumerate(urls):
                    if len(urls) > 1:
                        label = f"{server_name} #{idx+1}"
                    else:
                        label = server_name
                    ep_group.append(f"{label}${url}")
                
                play_from_list.append(server_name)
                play_url_list.append('#'.join(ep_group))
            
            if not play_from_list:
                play_from_list.append('DIRECT')
                play_url_list.append(f"Play${full_url}")
            
            play_from = '$$$'.join(play_from_list)
            play_url = '$$$'.join(play_url_list)
            
            clean_title = self._clean_title(title) or title or 'Unknown'
            remarks = f"{len(play_from_list)} Server"
            if rating:
                remarks = f"⭐{rating} • {remarks}"
            
            return {'list': [{
                'vod_id': path,
                'vod_name': clean_title[:150],
                'vod_pic': self._proxy_img(self._abs_url(pic)),
                'vod_year': year,
                'vod_area': '',
                'vod_remarks': remarks,
                'vod_content': sinopsis,
                'vod_play_from': play_from,
                'vod_play_url': play_url
            }]}
        except Exception as e:
            self.log(f"Detail error: {e}")
            return {'list': []}

    # ================================================================
    # SEARCH
    # ================================================================
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg else 1
            encoded = quote(key)
            
            if pg == 1:
                url = f"{self.site}/search/?s={encoded}"
            else:
                url = f"{self.site}/search/page/{pg}/?s={encoded}"
            
            resp = self.fetch(url)
            if not resp or not resp.text:
                return {'list': [], 'page': pg, 'pagecount': 1}
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            seen_keys = set()
            
            articles = soup.select('article') or soup.select('.gallery-grid article, .post, .ml-item, .slider')
            
            for result in articles[:40]:
                video = self._parse_video_item(result)
                if not video:
                    continue
                ck = f"{video['vod_name']}_{video['vod_year']}"
                if ck in seen_keys:
                    continue
                seen_keys.add(ck)
                items.append(video)
            
            pagecount = self._get_pagecount(soup, url, pg)
            if pagecount < pg:
                pagecount = pg
            
            return {'list': items, 'page': pg, 'pagecount': pagecount, 'limit': 40, 'total': len(items)}
        except Exception as e:
            self.log(f"Search error: {e}")
            return {'list': [], 'page': 1, 'pagecount': 1}

    # ================================================================
    # 🔥 DEEP RESOLVER - Ini kunci agar bisa streaming
    # ================================================================
    def _resolve_to_direct(self, url, server_name='', depth=0):
        """
        Coba ubah URL iframe menjadi URL video langsung (m3u8/mp4).
        Return: (final_url, headers) atau None
        """
        if depth > 3:
            return None
        
        if not url or not url.startswith('http'):
            return None
        
        # Sudah direct video?
        if '.m3u8' in url.lower() or '.mp4' in url.lower():
            return (url, {
                'User-Agent': self.site_headers['User-Agent'],
                'Referer': urlparse(url).scheme + '://' + urlparse(url).netloc + '/',
                'Origin': urlparse(url).scheme + '://' + urlparse(url).netloc,
            })
        
        try:
            headers = {
                'User-Agent': self.site_headers['User-Agent'],
                'Referer': self.site + '/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            r = self.session.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
            if r.status_code != 200:
                return None
            
            content = r.text
            base_url = r.url
            
            # ---------- Cari m3u8/mp4 langsung ----------
            patterns = [
                # JSON escaped
                r'["\']?(https?:(?:\\/|/)[^"\']*?\.m3u8[^"\']*?)["\']',
                r'["\']?(https?:(?:\\/|/)[^"\']*?\.mp4[^"\']*?)["\']',
                # source/file/src attributes
                r'(?:source|file|src|url|link|video_url|videoUrl|play_url|playUrl)["\']?\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                # Bare
                r'(https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)',
                r'(https?://[^\s"\'<>\\]+\.mp4[^\s"\'<>\\]*)',
            ]
            
            found_urls = []
            for pattern in patterns:
                for m in re.findall(pattern, content, re.IGNORECASE):
                    u = m if isinstance(m, str) else m[0]
                    u = u.replace('\\/', '/').replace('\\u002F', '/').replace('\\u0026', '&')
                    if u.startswith('http') and ('.m3u8' in u.lower() or '.mp4' in u.lower()):
                        if u not in found_urls:
                            found_urls.append(u)
            
            if found_urls:
                # Pilih yang paling relevan
                best = self._pick_best_video_url(found_urls)
                if best:
                    ref_domain = urlparse(base_url).scheme + '://' + urlparse(base_url).netloc
                    return (best, {
                        'User-Agent': self.site_headers['User-Agent'],
                        'Referer': base_url,
                        'Origin': ref_domain,
                    })
            
            # ---------- Cari iframe nested ----------
            soup = BeautifulSoup(content, 'html.parser')
            
            # Cek iframe
            for iframe in soup.find_all('iframe', src=True):
                nested = iframe.get('src', '')
                if nested.startswith('//'):
                    nested = 'https:' + nested
                elif nested.startswith('/'):
                    nested = urljoin(base_url, nested)
                elif not nested.startswith('http'):
                    nested = urljoin(base_url, nested)
                
                # Rekursif
                result = self._resolve_to_direct(nested, server_name, depth + 1)
                if result:
                    return result
            
            # ---------- Cari di JS variable ----------
            js_patterns = [
                r'var\s+(?:video|file|source|src|url|link)\s*=\s*["\']([^"\']+)["\']',
                r'(?:videoUrl|video_url|playUrl|play_url|streamUrl|stream_url)\s*[:=]\s*["\']([^"\']+)["\']',
                r'"file"\s*:\s*"([^"]+)"',
                r"'file'\s*:\s*'([^']+)'",
            ]
            
            for pattern in js_patterns:
                for m in re.findall(pattern, content, re.IGNORECASE):
                    u = m.replace('\\/', '/').replace('\\u002F', '/')
                    if u.startswith('//'):
                        u = 'https:' + u
                    elif u.startswith('/'):
                        u = urljoin(base_url, u)
                    
                    if u.startswith('http'):
                        # Kalau m3u8/mp4 langsung
                        if '.m3u8' in u.lower() or '.mp4' in u.lower():
                            ref_domain = urlparse(base_url).scheme + '://' + urlparse(base_url).netloc
                            return (u, {
                                'User-Agent': self.site_headers['User-Agent'],
                                'Referer': base_url,
                                'Origin': ref_domain,
                            })
                        # Kalau URL lain → rekursif
                        elif depth < 2:
                            result = self._resolve_to_direct(u, server_name, depth + 1)
                            if result:
                                return result
            
            # ---------- Cari base64-encoded ----------
            for m in re.findall(r'atob\(["\']([A-Za-z0-9+/=]+)["\']\)', content):
                try:
                    decoded = base64.b64decode(m + '=' * (-len(m) % 4)).decode('utf-8', 'ignore')
                    if '.m3u8' in decoded or '.mp4' in decoded:
                        for u in re.findall(r'(https?://[^\s"\']+)', decoded):
                            if '.m3u8' in u.lower() or '.mp4' in u.lower():
                                ref_domain = urlparse(base_url).scheme + '://' + urlparse(base_url).netloc
                                return (u, {
                                    'User-Agent': self.site_headers['User-Agent'],
                                    'Referer': base_url,
                                    'Origin': ref_domain,
                                })
                except Exception:
                    pass
            
        except Exception as e:
            self.log(f"Resolve error {server_name}: {e}")
        
        return None

    def _pick_best_video_url(self, urls):
        """Pilih URL video terbaik: prioritas m3u8 > mp4, hindari iklan"""
        if not urls:
            return None
        
        def score(u):
            s = 0
            ul = u.lower()
            if '.m3u8' in ul:
                s += 100
            if 'master' in ul:
                s += 20
            if 'playlist' in ul:
                s += 15
            if 'index' in ul:
                s += 10
            if '.mp4' in ul:
                s += 50
            if 'hd' in ul or '1080' in ul or '720' in ul:
                s += 10
            if '360' in ul or '480' in ul:
                s += 5
            # Hindari iklan
            if any(x in ul for x in ['ads', 'advert', 'banner', 'popup', 'trailer', 'sample']):
                s -= 50
            return s
        
        return max(urls, key=score)

    # ================================================================
    # PLAYER CONTENT
    # ================================================================
    def playerContent(self, flag, id, vipFlags):
        try:
            self.log(f"Player flag={flag} id={id[:120] if id else ''}")
            
            # Parse "LABEL$URL"
            if '$' in str(id):
                parts = str(id).split('$', 1)
                server_name = parts[0]
                url = parts[1]
            else:
                server_name = str(flag or 'P2P')
                url = str(id or '')
            
            if not url:
                return {'parse': 1, 'url': ''}
            
            # Sudah direct video
            if '.m3u8' in url.lower() or '.mp4' in url.lower():
                self.log(f"✓ Already direct: {url[:100]}")
                return {
                    'parse': 0,
                    'url': url,
                    'header': {
                        'User-Agent': self.site_headers['User-Agent'],
                        'Referer': urlparse(url).scheme + '://' + urlparse(url).netloc + '/',
                    }
                }
            
            # Cache
            cache_key = ('pc', url)
            hit = self._pc_cache.get(cache_key)
            if hit and time.time() - hit[0] < 1800:
                self.log(f"✓ Cache hit: {hit[1].get('url', '')[:80]}")
                return hit[1]
            
            # 🔥 DEEP RESOLVE
            self.log(f"🔍 Deep resolving {server_name}: {url[:100]}")
            resolved = self._resolve_to_direct(url, server_name)
            
            if resolved:
                final_url, headers = resolved
                self.log(f"✅ RESOLVED {server_name} → {final_url[:100]}")
                res = {'parse': 0, 'url': final_url, 'header': headers}
                self._pc_cache[cache_key] = (time.time(), res)
                return res
            
            # Fallback: webview
            self.log(f"⚠️ Fallback webview: {url[:100]}")
            res = {
                'parse': 1,
                'url': url,
                'header': {
                    'User-Agent': self.site_headers['User-Agent'],
                    'Referer': self.site,
                }
            }
            self._pc_cache[cache_key] = (time.time(), res)
            return res
        except Exception as e:
            self.log(f"Player error: {e}")
            return {'parse': 1, 'url': str(id) if id else ''}

    # ================================================================
    # HELPERS
    # ================================================================
    def _abs_url(self, src):
        if not src:
            return ''
        if src.startswith('http'):
            return src
        if src.startswith('//'):
            return 'https:' + src
        if src.startswith('/'):
            return self.site.rstrip('/') + src
        return self.site.rstrip('/') + '/' + src

    def log(self, msg):
        print(f"[LK21] {msg}")

    def destroy(self):
        if hasattr(self, 'session') and self.session:
            self.session.close()


if __name__ == "__main__":
    spider = Spider()
    spider.init()
    
    print("=" * 60)
    print("🧪 TESTING LK21 - DEEP RESOLVER")
    print("=" * 60)
    
    # Test resolve langsung
    test_urls = [
        'https://videonode.de/iframe3/p2p/xYaIb21KNDHKVGwtTt_OSg',
        'https://videonode.de/iframe3/cast/gxYPIhFMCBjIya4jlOgh0w',
        'https://videonode.de/iframe3/hydrax/b6W0vF0N8tjBmC-ztxrCnA',
    ]
    
    for u in test_urls:
        print(f"\n🔍 Testing: {u}")
        result = spider._resolve_to_direct(u)
        if result:
            print(f"   ✅ RESOLVED: {result[0][:120]}")
        else:
            print(f"   ❌ NOT RESOLVED")
    
    print("\n" + "=" * 60)
    print("✅ DONE")