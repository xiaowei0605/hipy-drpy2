# -*- coding: utf-8 -*-
import re
import os
import time
import json
import base64
import html as htmlmod
import datetime
import threading
import requests
from urllib.parse import urlparse, urljoin, quote, unquote, urlencode
from bs4 import BeautifulSoup, SoupStrainer
from base.spider import Spider


try:
    import cachetools
    _HAS_CACHETOOLS = True
except ImportError:
    _HAS_CACHETOOLS = False


class _SimpleTTLCache:
    def __init__(self, maxsize=300, ttl=7200):
        self._data = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def __contains__(self, k):
        if k in self._data:
            ts, _ = self._data[k]
            if time.time() - ts < self._ttl:
                return True
            del self._data[k]
        return False

    def __getitem__(self, k):
        return self._data[k][1]

    def __setitem__(self, k, v):
        if len(self._data) >= self._maxsize:
            oldest = min(self._data.items(), key=lambda x: x[1][0])[0]
            del self._data[oldest]
        self._data[k] = (time.time(), v)

    def get(self, k, default=None):
        return self[k] if k in self else default

    def clear(self):
        self._data.clear()


class _SimpleLRUCache:
    def __init__(self, maxsize=500):
        self._data = {}
        self._maxsize = maxsize

    def __contains__(self, k):
        return k in self._data

    def __getitem__(self, k):
        v = self._data.pop(k)
        self._data[k] = v
        return v

    def __setitem__(self, k, v):
        if k in self._data:
            self._data.pop(k)
        elif len(self._data) >= self._maxsize:
            self._data.pop(next(iter(self._data)))
        self._data[k] = v

    def get(self, k, default=None):
        return self[k] if k in self else default

    def clear(self):
        self._data.clear()


class Spider(Spider):

    LOG_FILE = '/sdcard/Download/oppadrama_log.txt'

    # ============================================================
    # INIT
    # ============================================================
    def init(self, extend=""):
        try:
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(f"=== OPPADRAMA Spider Log ===\n")
                f.write(f"Started: {datetime.datetime.now()}\n\n")
        except Exception:
            pass

        self.site = 'https://oppa.biz'
        self.tmdb_host = 'https://api.themoviedb.org/3'
        self.phost = 'https://image.tmdb.org/t/p/w500'
        self.tmdb_key = os.getenv('TMDB_API_KEY', '')

        if extend:
            try:
                ext = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(ext, dict):
                    if ext.get('tmdb_key'):
                        self.tmdb_key = ext['tmdb_key']
                    if ext.get('site'):
                        self.site = ext['site'].rstrip('/')
            except Exception:
                pass

        self.site_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'referer': f'{self.site}/',
            'origin': self.site,
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'max-age=0',
            'sec-ch-ua': '"Chromium";v="136", "Not-A.Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
        }

        self.tmdb_headers = {
            'User-Agent': self.site_headers['User-Agent'],
            'accept': 'application/json',
            'accept-language': 'id-ID,id;q=0.9',
        }

        self.article_strainer = SoupStrainer(
            ['article', 'div'],
            class_=['bsx', 'listupd', 'items', 'list-series', 'movie-item',
                    'post-item', 'list-item', 'grid-item']
        )
        self.detail_strainer = SoupStrainer(
            ['main', 'div', 'section'],
            class_=['postbody', 'content', 'main-content',
                    'movie-detail', 'series-detail']
        )
        self.episode_strainer = SoupStrainer(
            ['div', 'ul'],
            class_=['episode-list', 'list-episode', 'episodes',
                    'eplister', 'epwrap', 'episodelist', 'chapterlist']
        )
        self.meta_strainer = SoupStrainer(
            'meta', property=['og:title', 'og:image', 'og:description']
        )
        self.iframe_strainer = SoupStrainer(
            'iframe', src=re.compile(r'(embed|player|video|stream|play|watch)', re.I)
        )

        # ---------- Video URL extract patterns ----------
        self.video_patterns_compiled = [
            re.compile(r'["\']file["\']\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|mkv)[^"\']*)["\']', re.I),
            re.compile(r'["\'](?:src|source|url|link|hls|dash)["\']\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|mkv)[^"\']*)["\']', re.I),
            re.compile(r'file\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|mkv)[^"\']*)["\']', re.I),
            re.compile(r'src\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|mkv)[^"\']*)["\']', re.I),
            re.compile(r'sources\s*:\s*\[\s*\{[^}]*?(?:file|src)\s*:\s*["\']([^"\']+)["\']', re.I),
            re.compile(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4|mkv)(?:\?[^\s"\'<>]*)?)', re.I),
            re.compile(r'data-(?:video|src|file|url|stream|hls)=["\']([^"\']+\.(?:m3u8|mp4|mkv)[^"\']*)["\']', re.I),
            re.compile(r'(https?://[^\s"\'<>]+\.(?:m3u8|mpd)(?:\?[^\s"\'<>]*)?)', re.I),
            re.compile(r'["\'](https?://[^"\']*(?:playlist|master|index)[^"\']*\.(?:m3u8|mpd)[^"\']*)["\']', re.I),
            re.compile(r'["\'](https?://[^"\']+/(?:stream|hls|video|play)/[^"\']+)["\']', re.I),
        ]

        self.year_patterns_compiled = [
            re.compile(r'\b(20\d{2}|19\d{2})\b'),
            re.compile(r'(?:Tahun|Year|Release|Rilis|Released)[\s:]*(\d{4})', re.I),
        ]
        self.episode_patterns_compiled = [
            re.compile(r'(?:episode|eps|ep\.|ep)\s*(\d+)', re.I),
            re.compile(r'ep\s*(\d+)', re.I),
            re.compile(r'eps\s*(\d+)', re.I),
            re.compile(r'bagian\s*(\d+)', re.I),
            re.compile(r'part\s*(\d+)', re.I),
            re.compile(r'#\s*(\d+)', re.I),
            re.compile(r'(\d+)\s*(?:end|finale)', re.I),
        ]

        if _HAS_CACHETOOLS:
            self.cache = cachetools.TTLCache(maxsize=300, ttl=7200)
            self.url_cache = cachetools.LRUCache(maxsize=500)
        else:
            self.cache = _SimpleTTLCache(maxsize=300, ttl=7200)
            self.url_cache = _SimpleLRUCache(maxsize=500)

        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10, pool_maxsize=20, max_retries=2,
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.current_year = datetime.datetime.now().year

        try:
            self.session.get(self.site, headers=self.site_headers, timeout=5)
        except Exception:
            pass

    def getName(self):
        return "OPPADRAMA"

    def isVideoFormat(self, url):
        exts = ['.m3u8', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
        return any(ext in (url or '').lower() for ext in exts)

    def manualVideoCheck(self):
        return True

    def destroy(self):
        try:
            if hasattr(self, 'session'):
                self.session.close()
            if hasattr(self, 'cache'):
                self.cache.clear()
            if hasattr(self, 'url_cache'):
                self.url_cache.clear()
        except Exception:
            pass

    def fetch(self, url, headers=None, params=None, timeout=15, retry=2, stream=False):
        headers = headers or self.site_headers
        if params:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}{urlencode(params)}"
        referer = headers.get('Referer') or headers.get('referer') or ''
        cache_key = f"fetch|{url}|{referer}"
        if not stream and cache_key in self.url_cache:
            return self.url_cache[cache_key]
        last_exc = None
        for attempt in range(retry + 1):
            try:
                if attempt > 0:
                    time.sleep(0.3 * attempt)
                response = self.session.get(
                    url, headers=headers, timeout=timeout,
                    stream=stream, allow_redirects=True,
                )
                response.raise_for_status()
                if not stream and len(response.content) < 500_000:
                    try:
                        self.url_cache[cache_key] = response
                    except Exception:
                        pass
                return response
            except requests.exceptions.Timeout as e:
                last_exc = e
                self.log(f"Timeout {attempt+1}/{retry+1}: {url}")
            except requests.exceptions.RequestException as e:
                last_exc = e
                self.log(f"Request error {attempt+1}/{retry+1}: {e}")
        if last_exc:
            raise last_exc

    # ============================================================
    # HOME
    # ============================================================
    def homeContent(self, filter):
        return {
            'class': [
                {'type_name': 'Ongoing', 'type_id': 'ongoing'},
                {'type_name': 'Completed', 'type_id': 'completed'},
                {'type_name': 'Drama Korea', 'type_id': 'drama-korea'},
                {'type_name': 'Drama China', 'type_id': 'drama-china'},
                {'type_name': 'Drama Thailand', 'type_id': 'drama-thailand'},
                {'type_name': 'Drama Jepang', 'type_id': 'drama-jepang'},
                {'type_name': 'Drama Taiwan', 'type_id': 'drama-taiwan'},
                {'type_name': 'Drama Filipina', 'type_id': 'drama-filipina'},
                {'type_name': 'Series Barat', 'type_id': 'series-barat'},
                {'type_name': 'Netflix', 'type_id': 'netflix'},
                {'type_name': 'Film Korea', 'type_id': 'film-korea'},
                {'type_name': 'Film China', 'type_id': 'film-china'},
                {'type_name': 'Film Hong Kong', 'type_id': 'film-hongkong'},
                {'type_name': 'Film Thailand', 'type_id': 'film-thailand'},
                {'type_name': 'Film Jepang', 'type_id': 'film-jepang'},
                {'type_name': 'Film Taiwan', 'type_id': 'film-taiwan'},
                {'type_name': 'Film Filipina', 'type_id': 'film-filipina'},
                {'type_name': 'Film India', 'type_id': 'film-india'},
                {'type_name': 'Film Barat', 'type_id': 'film-barat'},
                {'type_name': 'Variety Show', 'type_id': 'variety-show'},
                {'type_name': 'Animasi', 'type_id': 'animasi'},
                {'type_name': 'Jadwal', 'type_id': 'jadwal'},
                {'type_name': 'Bookmark', 'type_id': 'bookmark'},
                {'type_name': 'Terbaru', 'type_id': 'terbaru'},
                {'type_name': 'Populer', 'type_id': 'populer'},
                {'type_name': 'Series', 'type_id': 'series'},
                {'type_name': 'Movie', 'type_id': 'movie'},
                {'type_name': 'Anime', 'type_id': 'anime'},
            ],
            'filters': {}
        }

    def homeVideoContent(self):
        try:
            response = self.fetch(self.site + '/', timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser',
                                 parse_only=self.article_strainer)
            items, seen = [], set()
            for article in soup.find_all(['article', 'div'], limit=60):
                item = self._parse_article_fast(article)
                if item and item['vod_id'] not in seen:
                    seen.add(item['vod_id'])
                    if item.get('vod_year'):
                        item['vod_year'] = self._validate_year(item['vod_year'])
                    else:
                        item['vod_year'] = str(self.current_year - 1)
                    items.append(item)
                    if len(items) >= 40:
                        break
            if items:
                return {'list': items}
        except Exception as e:
            self.log(f'homeVideoContent error: {e}')
        try:
            result = self.categoryContent('terbaru', 1, False, {})
            return {'list': result.get('list', [])[:30]}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            category_map = {
                'ongoing': '/series/?status=Ongoing&type=&order=update',
                'completed': '/series/?status=Completed&type=Drama&order=update',
                'drama-korea': '/series/?country%5B%5D=south-korea&status=&type=Drama&order=update',
                'drama-china': '/series/?country%5B%5D=china&type=Drama&order=update',
                'drama-thailand': '/series/?country%5B%5D=thailand&status=&type=Drama&order=update',
                'drama-jepang': '/series/?country%5B%5D=japan&type=Drama&order=update',
                'drama-taiwan': '/series/?country%5B%5D=taiwan&status=&type=Drama&order=update',
                'drama-filipina': '/series/?country%5B%5D=philippines&type=Drama&order=update',
                'series-barat': '/series/?country%5B%5D=usa&type=Drama&order=update',
                'netflix': '/network/netflix/',
                'film-korea': '/series/?country%5B%5D=south-korea&status=&type=Movie&order=update',
                'film-china': '/series/?country%5B%5D=china&type=Movie&order=update',
                'film-hongkong': '/series/?country%5B%5D=hong-kong&type=Movie&order=update',
                'film-thailand': '/series/?country%5B%5D=thailand&status=&type=Movie&order=update',
                'film-jepang': '/series/?country%5B%5D=japan&type=Movie&order=update',
                'film-taiwan': '/series/?country%5B%5D=taiwan&status=&type=Movie&order=update',
                'film-filipina': '/series/?country%5B%5D=philippines&type=Movie&order=update',
                'film-india': '/series/?country%5B%5D=india&status=&type=Movie&order=update',
                'film-barat': '/series/?country%5B%5D=united-states&status=&type=Movie&order=update',
                'variety-show': '/series/?type=TV+Show&order=update',
                'animasi': '/series/?page=1&genre%5B0%5D=animation&type=&order=update',
                'jadwal': '/jadwal/',
                'bookmark': '/bookmark/',
                'terbaru': f'/release-year/{self.current_year}/',
                'populer': '/imdb/?imdb=7.5-10',
                'series': '/series/?status=&type=Drama&order=update',
                'movie': '/series/?type=Movie&order=update',
                'anime': '/series/?genre%5B0%5D=animation&type=&order=update',
            }
            base_path = category_map.get(tid, '/')
            url = f"{self.site}{base_path}"
            if str(pg) != '1' and tid not in ['jadwal', 'bookmark']:
                if '?' in url:
                    url += f"&page={pg}"
                else:
                    url += f"page/{pg}/"
            self.log(f'Category {tid} page {pg}: {url}')
            response = self.fetch(url, timeout=12)
            soup = BeautifulSoup(response.text, 'html.parser',
                                 parse_only=self.article_strainer)
            items, seen = [], set()
            for article in soup.find_all(['article', 'div'], limit=60):
                item = self._parse_article_fast(article)
                if item and item['vod_id'] not in seen:
                    seen.add(item['vod_id'])
                    if item.get('vod_year'):
                        item['vod_year'] = self._validate_year(item['vod_year'])
                    else:
                        item['vod_year'] = str(self.current_year - 1)
                    items.append(item)
            return {
                'list': items[:40], 'page': int(pg),
                'pagecount': 9999, 'limit': 40, 'total': 999999,
            }
        except Exception as e:
            self.log(f'categoryContent error {tid}: {e}')
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 40, 'total': 0}

    # ============================================================
    # DETAIL
    # ============================================================
    def detailContent(self, ids):
        try:
            path = ids[0]
            if not path or self._is_notification_link(path):
                return {'list': []}
            path = unquote(path)
            if not path.startswith('http'):
                full_url = f"{self.site}{path}" if path.startswith('/') else f"{self.site}/{path}"
            else:
                full_url = path

            self.log('========== DETAIL START ==========')
            self.log(f'path={path} full_url={full_url}')

            cache_key = f"detail|{full_url}"
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                if time.time() - cached.get('_ts', 0) < 3600:
                    self.log('Using CACHED detail')
                    return cached['data']

            response = self.fetch(full_url, timeout=15)
            html = response.text
            self.log(f'HTTP {response.status_code}, len={len(html)}, final={response.url}')

            detail_soup = BeautifulSoup(html, 'html.parser', parse_only=self.detail_strainer)
            meta_soup = BeautifulSoup(html, 'html.parser', parse_only=self.meta_strainer)
            detail = self._parse_detail_fast(detail_soup, meta_soup)
            self.log(f'Title: {detail.get("title")!r}')

            episode_soup = BeautifulSoup(html, 'html.parser', parse_only=self.episode_strainer)
            episodes = self._parse_episodes_fast(episode_soup)
            self.log(f'Episodes: {len(episodes)}')

            mirrors = self._parse_mirrors_from_html(html)
            self.log(f'Mirrors in page: {len(mirrors)}')

            if not mirrors and episodes:
                first_ep_url = episodes[0]['url']
                self.log(f'Fetching first episode: {first_ep_url}')
                ep_full_url = first_ep_url if first_ep_url.startswith('http') else (
                    f"{self.site}{first_ep_url}" if first_ep_url.startswith('/')
                    else f"{self.site}/{first_ep_url}"
                )
                try:
                    ep_resp = self.fetch(ep_full_url, timeout=15)
                    mirrors = self._parse_mirrors_from_html(ep_resp.text)
                    self.log(f'Mirrors from first ep: {len(mirrors)} -> {[m[0] for m in mirrors]}')
                except Exception as e:
                    self.log(f'Failed fetch first ep: {e}')

            if self.tmdb_key and detail.get('title'):
                try:
                    t = threading.Thread(target=self._fetch_tmdb_data,
                                         args=(detail['title'], detail.get('year'), detail),
                                         daemon=True)
                    t.start()
                    t.join(timeout=5)
                except Exception as e:
                    self.log(f'TMDB error: {e}')

            sorted_eps = self._sort_episodes_fast(episodes) if episodes else []
            if sorted_eps:
                all_eps_line = '#'.join(f"{ep['name']}${ep['url']}" for ep in sorted_eps[:80])
            else:
                all_eps_line = f"Play${full_url}"

            play_from_list, play_url_list = [], []
            if mirrors:
                for label, _ in mirrors:
                    play_from_list.append((label or 'Server').strip())
                    play_url_list.append(all_eps_line)
            else:
                play_from_list.append('Default')
                play_url_list.append(all_eps_line)

            play_from = '$$$'.join(play_from_list)
            play_url = '$$$'.join(play_url_list)
            self.log(f'play_from = {play_from}')
            self.log('========== DETAIL END ==========')

            remarks = detail.get('remarks', '')
            if episodes:
                remarks = f"{len(episodes)} Episode | {remarks}"

            result = {'list': [{
                'vod_id': path,
                'vod_name': detail.get('title', 'OPPADRAMA'),
                'vod_pic': detail.get('pic', ''),
                'vod_year': detail.get('year', str(self.current_year - 1)),
                'vod_area': detail.get('area', ''),
                'vod_remarks': remarks,
                'vod_content': detail.get('content', ''),
                'vod_play_from': play_from,
                'vod_play_url': play_url,
            }]}

            try:
                self.cache[cache_key] = {'data': result, '_ts': time.time()}
            except Exception:
                pass
            return result
        except Exception as e:
            self.log(f'detailContent error: {e}', level='ERROR')
            import traceback
            self.log(f'traceback: {traceback.format_exc()}', level='ERROR')
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        try:
            if not key or len(key) < 2:
                return {'list': []}
            search_url = f"{self.site}/?s={quote(key)}"
            if str(pg) != '1':
                search_url += f"&page={pg}"
            self.log(f'Search: {search_url}')
            response = self.fetch(search_url, timeout=12)
            soup = BeautifulSoup(response.text, 'html.parser', parse_only=self.article_strainer)
            items, seen = [], set()
            for article in soup.find_all(['article', 'div'], limit=50):
                item = self._parse_article_fast(article)
                if item and item['vod_id'] not in seen:
                    seen.add(item['vod_id'])
                    if item.get('vod_year'):
                        item['vod_year'] = self._validate_year(item['vod_year'])
                    items.append(item)
            return {'list': items[:40], 'page': int(pg),
                    'pagecount': 9999, 'limit': 40, 'total': 999999}
        except Exception as e:
            self.log(f'searchContent error: {e}')
            return {'list': [], 'page': 1, 'pagecount': 1}

    # ============================================================
    # PLAYER — 6 STRATEGI EXTRACT
    # ============================================================
    def playerContent(self, flag, id, vipFlags):
        try:
            id = unquote(id)
            self.log(f'=== PLAYER === flag={flag!r} id={id!r}')

            iframe_url = None

            if any(x in id for x in ['abyssplayer.com', 'minochinos.com',
                                      'player.', '/embed', '/v/', '/e/',
                                      'dailymotion', 'ok.ru', 'filelions',
                                      'streamtape', 'dood', 'vidhide']):
                iframe_url = id if id.startswith('http') else f"https:{id}"
            else:
                ep_url = id if id.startswith('http') else (
                    f"{self.site}{id}" if id.startswith('/') else f"{self.site}/{id}"
                )
                response = self.fetch(ep_url, timeout=15)
                mirrors = self._parse_mirrors_from_html(response.text)
                if not mirrors:
                    return {'parse': 1, 'url': ep_url,
                            'header': {'User-Agent': self.site_headers['User-Agent'],
                                       'Referer': self.site}}
                target = None
                want = (flag or '').strip().lower()
                if want and want not in ('default', 'semua episode', ''):
                    for label, url in mirrors:
                        lbl_low = label.lower()
                        if want == lbl_low or want in lbl_low or lbl_low in want:
                            target = (label, url)
                            break
                if not target:
                    target = mirrors[0]
                self.log(f'Picked: {target[0]} -> {target[1]}')
                iframe_url = target[1]

            parsed = urlparse(iframe_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"

            # ---------- Fetch iframe ----------
            iframe_html = ''
            for idx, hdr in enumerate([
                {'User-Agent': self.site_headers['User-Agent'],
                 'Referer': iframe_url,
                 'Accept': '*/*',
                 'Accept-Language': 'en-US,en;q=0.9'},
                {'User-Agent': self.site_headers['User-Agent'],
                 'Referer': iframe_url,
                 'Origin': origin,
                 'Accept': '*/*'},
                {'User-Agent': self.site_headers['User-Agent'],
                 'Accept': '*/*'},
            ]):
                try:
                    self.log(f'Fetch iframe #{idx+1}')
                    r = self.fetch(iframe_url, headers=hdr, timeout=15, retry=1)
                    iframe_html = r.text
                    if len(iframe_html) > 200 and 'restricted' not in iframe_html.lower():
                        self.log(f'  → OK, len={len(iframe_html)}')
                        break
                    else:
                        self.log(f'  → restricted/short, try next')
                except Exception as e:
                    self.log(f'  → err: {e}')

            if not iframe_html:
                self.log('No iframe HTML')
                return {'parse': 1, 'url': iframe_url,
                        'header': {'User-Agent': self.site_headers['User-Agent'],
                                   'Referer': iframe_url}}

            # ============================================================
            # STRATEGI 1: Regex patterns biasa
            # ============================================================
            video_url = self._find_video_fast(iframe_html)
            if video_url:
                if video_url.startswith('//'):
                    video_url = 'https:' + video_url
                if not video_url.startswith('http'):
                    video_url = urljoin(iframe_url, video_url)
                self.log(f'>>> S1 VIDEO: {video_url[:150]}')
                return {'parse': 0, 'url': video_url,
                        'header': {'User-Agent': self.site_headers['User-Agent'],
                                   'Referer': iframe_url,
                                   'Origin': origin}}

            # ============================================================
            # STRATEGI 2: Decode base64 di HTML
            # ============================================================
            self.log('S2: cari base64...')
            b64_candidates = re.findall(r'["\']([A-Za-z0-9+/=]{60,})["\']', iframe_html)
            for b64 in b64_candidates[:20]:
                try:
                    dec = base64.b64decode(b64 + '=' * (-len(b64) % 4)).decode('utf-8', 'ignore')
                    if '.m3u8' in dec or '.mp4' in dec:
                        m = re.search(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', dec)
                        if m:
                            self.log(f'>>> S2 VIDEO (b64): {m.group(1)[:150]}')
                            return {'parse': 0, 'url': m.group(1),
                                    'header': {'User-Agent': self.site_headers['User-Agent'],
                                               'Referer': iframe_url,
                                               'Origin': origin}}
                except Exception:
                    pass

            # ============================================================
            # STRATEGI 3: Cari variabel JS khusus
            # ============================================================
            self.log('S3: cari variabel JS...')
            js_vars = re.findall(
                r'(?:var|let|const)\s+(\w+)\s*=\s*["\']([^"\']{20,})["\']',
                iframe_html
            )
            for name, value in js_vars:
                name_low = name.lower()
                if any(k in name_low for k in ['url', 'file', 'src', 'video', 'source',
                                                'link', 'stream', 'm3u8', 'mp4', 'play']):
                    if '.m3u8' in value or '.mp4' in value or value.startswith('http'):
                        if value.startswith('//'):
                            value = 'https:' + value
                        if not value.startswith('http'):
                            value = urljoin(iframe_url, value)
                        self.log(f'>>> S3 VIDEO ({name}): {value[:150]}')
                        return {'parse': 0, 'url': value,
                                'header': {'User-Agent': self.site_headers['User-Agent'],
                                           'Referer': iframe_url,
                                           'Origin': origin}}

            # ============================================================
            # STRATEGI 4: Cari API endpoint
            # ============================================================
            self.log('S4: cari API endpoint...')
            api_patterns = [
                r'["\'](/api/[^"\']+)["\']',
                r'["\']([^"\']*get_video[^"\']*)["\']',
                r'["\']([^"\']*getVideo[^"\']*)["\']',
                r'["\']([^"\']*play[^"\']*\.php[^"\']*)["\']',
                r'fetch\(["\']([^"\']+)["\']',
                r'axios\.get\(["\']([^"\']+)["\']',
                r'XMLHttpRequest[^;]+open\(["\']\w+["\'],\s*["\']([^"\']+)["\']',
            ]
            for pat in api_patterns:
                for m in re.finditer(pat, iframe_html, re.I):
                    api_url = m.group(1)
                    if api_url.startswith('//'):
                        api_url = 'https:' + api_url
                    elif not api_url.startswith('http'):
                        api_url = urljoin(iframe_url, api_url)
                    self.log(f'API candidate: {api_url}')

                    try:
                        api_resp = self.fetch(api_url, headers={
                            'User-Agent': self.site_headers['User-Agent'],
                            'Referer': iframe_url,
                            'Origin': origin,
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json,text/plain,*/*',
                        }, timeout=12, retry=1)
                        api_text = api_resp.text
                        self.log(f'  → api len: {len(api_text)}')

                        v = self._find_video_fast(api_text)
                        if v:
                            if v.startswith('//'):
                                v = 'https:' + v
                            self.log(f'>>> S4 VIDEO (api): {v[:150]}')
                            return {'parse': 0, 'url': v,
                                    'header': {'User-Agent': self.site_headers['User-Agent'],
                                               'Referer': iframe_url,
                                               'Origin': origin}}
                    except Exception as e:
                        self.log(f'  api err: {e}')

            # ============================================================
            # STRATEGI 5: <source> tag
            # ============================================================
            self.log('S5: cari <source> tag...')
            for m in re.finditer(r'<(?:source|video)[^>]+(?:src|data-src)=["\']([^"\']+)["\']',
                                  iframe_html, re.I):
                v = m.group(1)
                if v.startswith('//'):
                    v = 'https:' + v
                if v.startswith('http') and ('.m3u8' in v or '.mp4' in v or 'stream' in v):
                    self.log(f'>>> S5 VIDEO: {v[:150]}')
                    return {'parse': 0, 'url': v,
                            'header': {'User-Agent': self.site_headers['User-Agent'],
                                       'Referer': iframe_url,
                                       'Origin': origin}}

            # ============================================================
            # STRATEGI 6: Nested iframe
            # ============================================================
            self.log('S6: nested iframe...')
            inner_matches = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', iframe_html, re.I)
            for inner in inner_matches:
                if inner.startswith('//'):
                    inner = 'https:' + inner
                elif not inner.startswith('http'):
                    inner = urljoin(iframe_url, inner)
                self.log(f'Nested: {inner}')
                try:
                    nr = self.fetch(inner, headers={
                        'User-Agent': self.site_headers['User-Agent'],
                        'Referer': iframe_url,
                    }, timeout=12, retry=1)
                    v = self._find_video_fast(nr.text)
                    if v:
                        if v.startswith('//'):
                            v = 'https:' + v
                        self.log(f'>>> S6 VIDEO (nested): {v[:150]}')
                        return {'parse': 0, 'url': v,
                                'header': {'User-Agent': self.site_headers['User-Agent'],
                                           'Referer': inner}}
                except Exception as e:
                    self.log(f'Nested err: {e}')

                return {'parse': 1, 'url': inner,
                        'header': {'User-Agent': self.site_headers['User-Agent'],
                                   'Referer': iframe_url}}

            # ============================================================
            # FALLBACK
            # ============================================================
            self.log(f'Fallback parse=1: {iframe_url}')
            return {'parse': 1, 'url': iframe_url,
                    'header': {'User-Agent': self.site_headers['User-Agent'],
                               'Referer': iframe_url,
                               'Origin': origin}}

        except Exception as e:
            self.log(f'playerContent error: {e}')
            import traceback
            self.log(f'traceback: {traceback.format_exc()}', level='ERROR')
            fallback = id if id.startswith('http') else f"{self.site}{id}"
            return {'parse': 1, 'url': fallback, 'header': self.site_headers}

    def localProxy(self, param):
        return [404, 'text/plain', b'']

    # ============================================================
    # MIRROR PARSER
    # ============================================================
    def _try_decode_b64_iframe(self, val):
        if not val or len(val) < 20:
            return None
        try:
            decoded = base64.b64decode(val + '=' * (-len(val) % 4)).decode('utf-8', 'ignore')
        except Exception:
            return None
        m = re.search(r'src\s*=\s*["\']([^"\']+)["\']', decoded, re.I)
        if not m:
            return None
        url = m.group(1).strip()
        if url.startswith('//'):
            url = 'https:' + url
        return urljoin(self.site, url)

    def _parse_mirrors_from_html(self, html):
        mirrors = []
        seen_urls = set()
        if not html:
            return mirrors

        def _add(label, url):
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            mirrors.append((label or f'Server {len(mirrors)+1}', url))

        soup = BeautifulSoup(html, 'html.parser')

        select = soup.find('select', class_='mirror')
        if select:
            for opt in select.find_all('option'):
                label = (opt.get_text(strip=True) or '').strip()
                val = (opt.get('value') or '').strip()
                url = self._try_decode_b64_iframe(val)
                if url:
                    _add(label, url)
            if mirrors:
                self.log(f'[mirror] via select.mirror: {len(mirrors)}')
                return mirrors

        for sel in soup.find_all('select'):
            for opt in sel.find_all('option'):
                label = (opt.get_text(strip=True) or '').strip()
                val = (opt.get('value') or '').strip()
                url = self._try_decode_b64_iframe(val)
                if url:
                    _add(label, url)
        if mirrors:
            self.log(f'[mirror] via any select: {len(mirrors)}')
            return mirrors

        for opt in soup.find_all('option'):
            label = (opt.get_text(strip=True) or '').strip()
            val = (opt.get('value') or '').strip()
            url = self._try_decode_b64_iframe(val)
            if url:
                _add(label, url)
        if mirrors:
            self.log(f'[mirror] via any option: {len(mirrors)}')
            return mirrors

        for varname in ['mirrors', 'sources', 'options', 'servers', 'players']:
            pattern = re.compile(
                r'(?:var\s+|let\s+|const\s+)?' + varname + r'\s*[:=]\s*(\[.*?\])\s*[;,}]',
                re.S | re.I
            )
            m = pattern.search(html)
            if m:
                block = m.group(1)
                for b64match in re.finditer(r'["\']([A-Za-z0-9+/=]{40,})["\']', block):
                    url = self._try_decode_b64_iframe(b64match.group(1))
                    if url:
                        _add(f'Server {len(mirrors)+1}', url)
        if mirrors:
            self.log(f'[mirror] via JS variable: {len(mirrors)}')
            return mirrors

        containers = [
            soup.find(id='pembed'),
            soup.find(id='embed_holder'),
            soup.find(class_='player-embed'),
            soup.find(class_='video-content'),
            soup.find(class_='megavid'),
        ]
        for cont in containers:
            if not cont:
                continue
            for ifr in cont.find_all('iframe'):
                src = (ifr.get('src') or '').strip()
                if src and 'about:blank' not in src.lower():
                    if src.startswith('//'):
                        src = 'https:' + src
                    src = urljoin(self.site, src)
                    _add('Server 1', src)
        if mirrors:
            self.log(f'[mirror] via iframe container: {len(mirrors)}')
            return mirrors

        return mirrors

    # ============================================================
    # PARSING HELPERS
    # ============================================================
    def _parse_article_fast(self, article):
        try:
            link = article.find('a', href=True)
            if not link:
                return None
            href = link.get('href', '').strip()
            if not href or self._is_bad_link(href):
                return None
            title = ''
            title_elem = article.find(['h2', 'h3', 'h4'])
            if title_elem:
                title = title_elem.get_text(strip=True)
            if not title:
                img = article.find('img')
                if img and img.get('alt'):
                    title = img.get('alt', '').strip()
            if not title or self._is_notification_title(title):
                return None
            img_src = ''
            img = article.find('img')
            if img:
                for attr in ['src', 'data-src', 'data-lazy-src']:
                    if img.get(attr):
                        img_src = img.get(attr)
                        break
            year = ''
            for pattern in self.year_patterns_compiled:
                m = pattern.search(article.get_text())
                if m:
                    year = m.group(1)
                    break
            remarks = ''
            status_elem = article.find(class_=['epx', 'bt', 'typez', 'quality', 'status'])
            if status_elem:
                remarks = status_elem.get_text(strip=True)
            return {
                'vod_id': self._make_relative_path(href),
                'vod_name': self._clean_html_text(title[:200]),
                'vod_pic': self._abs_url_oppa(img_src),
                'vod_year': year,
                'vod_remarks': remarks[:100] if remarks else '',
            }
        except Exception:
            return None

    def _parse_detail_fast(self, detail_soup, meta_soup):
        result = {'title': '', 'pic': '', 'year': '', 'area': '', 'remarks': '', 'content': ''}
        try:
            title_elem = detail_soup.find(['h1', 'h2'])
            if title_elem:
                result['title'] = title_elem.get_text(strip=True)
            if not result['title']:
                og_title = meta_soup.find('meta', property='og:title')
                if og_title:
                    result['title'] = og_title.get('content', '').split('|')[0].strip()
            og_image = meta_soup.find('meta', property='og:image')
            if og_image:
                result['pic'] = og_image.get('content', '')
            if not result['pic']:
                img_elem = detail_soup.find('img')
                if img_elem:
                    for attr in ['src', 'data-src', 'data-lazy-src']:
                        if img_elem.get(attr):
                            result['pic'] = img_elem.get(attr)
                            break
            text_content = detail_soup.get_text()
            for pattern in self.year_patterns_compiled:
                m = pattern.search(text_content)
                if m:
                    result['year'] = m.group(1)
                    break
            area_map = {
                'korea': 'KR', 'korean': 'KR', 'china': 'CN', 'chinese': 'CN',
                'thailand': 'TH', 'thai': 'TH', 'japan': 'JP', 'japanese': 'JP',
                'indonesia': 'ID', 'indonesian': 'ID', 'taiwan': 'TW', 'taiwanese': 'TW',
                'philippines': 'PH', 'filipino': 'PH', 'usa': 'US', 'america': 'US',
                'india': 'IN', 'indian': 'IN', 'hong kong': 'HK', 'hongkong': 'HK',
            }
            lower_text = text_content.lower()
            for key, code in area_map.items():
                if key in lower_text:
                    result['area'] = code
                    break
            status_elem = detail_soup.find(class_=['status', 'completed', 'ongoing'])
            if status_elem:
                result['remarks'] = status_elem.get_text(strip=True)
            content_elem = detail_soup.find(class_=['entry-content', 'description', 'sinopsis'])
            if content_elem:
                result['content'] = content_elem.get_text(strip=True)[:800]
            result['title'] = self._clean_html_text(result['title'])
            result['content'] = self._clean_html_text(result['content'])
            result['remarks'] = self._clean_html_text(result['remarks'])
        except Exception as e:
            self.log(f'_parse_detail_fast error: {e}')
        return result

    def _parse_episodes_fast(self, episode_soup):
        episodes = []
        try:
            links = episode_soup.find_all('a', href=True)
            for link in links[:150]:
                try:
                    href = link.get('href', '').strip()
                    if not href or self._is_bad_link(href):
                        continue
                    text = link.get_text(strip=True)
                    if not text:
                        continue
                    ep_name = '1'
                    for pattern in self.episode_patterns_compiled:
                        m = pattern.search(text.lower())
                        if m:
                            ep_name = m.group(1)
                            break
                    episodes.append({
                        'name': ep_name,
                        'url': self._make_relative_path(href),
                    })
                except Exception:
                    continue
        except Exception as e:
            self.log(f'_parse_episodes_fast error: {e}')
        return episodes

    def _sort_episodes_fast(self, episodes):
        if not episodes:
            return []
        try:
            return sorted(episodes, key=lambda x: int(x['name']) if x['name'].isdigit() else 99999)
        except Exception:
            return episodes

    def _find_video_fast(self, html):
        if not html:
            return None
        for pattern in self.video_patterns_compiled:
            for m in pattern.finditer(html):
                url = m.group(1)
                if not url or not url.startswith('http'):
                    continue
                low = url.lower()
                if any(x in low for x in ['google', 'youtube', 'schema.org',
                                           'facebook.com', 'twitter.com',
                                           'w3.org', 'googletagmanager',
                                           'google-analytics']):
                    continue
                return url
        return None

    def _fetch_tmdb_data(self, title, year, detail_dict):
        try:
            if not self.tmdb_key:
                return
            params = {'query': title, 'api_key': self.tmdb_key,
                      'language': 'id-ID', 'page': 1, 'include_adult': 'false'}
            resp = self.fetch(f'{self.tmdb_host}/search/tv', params=params,
                              headers=self.tmdb_headers, timeout=8)
            data = resp.json()
            if data.get('results'):
                r = data['results'][0]
                if r.get('name'): detail_dict['title'] = r['name']
                if r.get('poster_path'): detail_dict['pic'] = f"{self.phost}{r['poster_path']}"
                if r.get('overview'): detail_dict['content'] = r['overview']
                if r.get('first_air_date'):
                    detail_dict['year'] = self._validate_year(r['first_air_date'].split('-')[0])
                return
            resp = self.fetch(f'{self.tmdb_host}/search/movie', params=params,
                              headers=self.tmdb_headers, timeout=8)
            data = resp.json()
            if data.get('results'):
                r = data['results'][0]
                if r.get('title'): detail_dict['title'] = r['title']
                if r.get('poster_path'): detail_dict['pic'] = f"{self.phost}{r['poster_path']}"
                if r.get('overview'): detail_dict['content'] = r['overview']
                if r.get('release_date'):
                    detail_dict['year'] = self._validate_year(r['release_date'].split('-')[0])
        except Exception as e:
            self.log(f'TMDB error: {e}')

    def _is_bad_link(self, href):
        if not href:
            return True
        low = href.lower()
        bad_keywords = [
            'javascript:', '#', '?s=', '/wp-content/', 'disclaimer',
            '/tag/', '/category/', '/author/', '/page/', '/feed/',
            'notification', 'pemberitahuan', 'announcement',
            'pengumuman', 'telegram', 't.me', 'whatsapp',
            'facebook.com', 'twitter.com', 'instagram.com',
            '/search/', 'wp-login.php', '/comments/',
            '/privacy-policy', '/terms-of-service',
            '/contact', '/about', '/donate', '#respond',
            '#comments', 'mailto:', 'tel:',
        ]
        return any(b in low for b in bad_keywords)

    def _is_notification_link(self, href):
        if not href:
            return False
        low = href.lower()
        keywords = ['/notification', '/pemberitahuan', '/announcement',
                    '/pengumuman', '/disclaimer', '/telegram',
                    '/channel', '/broadcast', '#announce']
        return any(k in low for k in keywords)

    def _is_notification_title(self, title):
        if not title:
            return False
        low = title.lower()
        keywords = ['notification', 'pemberitahuan', 'announcement',
                    'pengumuman', '📢', '🔔', '⚡', '🚨',
                    'info:', 'update:', 'important:', 'penting:',
                    'pemberitahuan penting', 'important announcement',
                    'announ:', 'notif:', 'info penting']
        return any(k in low for k in keywords)

    def _abs_url_oppa(self, src):
        if not src or src.strip() == '':
            return ''
        src = src.strip()
        if src.startswith('http'): return src
        if src.startswith('//'): return 'https:' + src
        if src.startswith('/'): return self.site + src
        return self.site + '/' + src

    def _make_relative_path(self, href):
        try:
            parsed = urlparse(href)
            site_domains = ['oppa.biz', 'www.oppa.biz', 'oppadrama.biz',
                            '45.11.57.125', '212.86.121.175', '45.11.57.192']
            if parsed.netloc and any(d in parsed.netloc for d in site_domains):
                path = parsed.path
                if parsed.query:
                    path += '?' + parsed.query
                return path
            if not parsed.netloc:
                return href if href.startswith('/') else '/' + href
            return href
        except Exception:
            return href if href.startswith('/') else '/' + href

    def _clean_html_text(self, text):
        if not text:
            return ''
        try:
            text = htmlmod.unescape(text)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        except Exception:
            return text or ''

    def _validate_year(self, year_str):
        try:
            y = int(year_str)
            if 1900 <= y <= self.current_year + 2:
                return str(y)
        except Exception:
            pass
        return ''

    def log(self, message, level="INFO"):
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] [{level}] [OPPADRAMA] {message}"
            print(line)
            try:
                with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception:
                pass
        except Exception:
            print(f"[OPPADRAMA] {message}")