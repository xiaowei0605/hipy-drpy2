# -*- coding: utf-8 -*-
import sys, os, json, re, requests, urllib.parse
from bs4 import BeautifulSoup
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    # 候选域名按优先级探测，首个返回正常列表页的生效；全部失效走发布页
    DOMAINS = ['https://www.wn10.cfd', 'https://www.wn08.ru', 'https://www.wn07.ru', 'https://www.wn03.ru']

    def getName(self): return "绅士漫画"

    def init(self, extend=""):
        self.session = requests.Session()
        self.ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.2957.129'
        self.headers = {'User-Agent': self.ua, 'Accept-Language': 'zh-CN,zh;q=0.9', 'Connection': 'keep-alive'}
        self.baseUrl = self.DOMAINS[0]
        self.proxies = self._proxies()
        self.check_domain()

    def check_domain(self):
        for base in self.DOMAINS:
            try:
                r = self.session.get(base + '/albums-index-page-1-cate-1.html', headers=self.headers, timeout=6, proxies=self.proxies)
                if r.status_code == 200 and ('gallary_wrap' in r.text or 'photos-index-aid' in r.text):
                    self.baseUrl = base
                    return
            except Exception:
                continue
        self.fetch_new_domain()

    def fetch_new_domain(self):
        try:
            r = self.session.get("https://wnlink.ru/", headers=self.headers, timeout=5, proxies=self.proxies)
            for url in re.findall(r'href="(https?://[^"]+)"', r.text):
                if "wn" in url and "link" not in url:
                    self.baseUrl = url.rstrip('/')
                    break
        except Exception:
            pass

    def get_header(self, url=None):
        h = self.headers.copy()
        h['Referer'] = url if url else self.baseUrl + '/'
        return h

    def _proxies(self):
        # 代理兜底：显式读取环境变量（requests 默认也读，这里显式传递以便统一管理）
        p = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY') \
            or os.environ.get('all_proxy') or os.environ.get('ALL_PROXY')
        return {'http': p, 'https': p} if p else None

    def _abs(self, u):
        if not u:
            return ""
        u = u.strip()
        if u.startswith('data:'):
            return ""
        if u.startswith('//'):
            return 'https://' + u.lstrip('/')
        if u.startswith('http'):
            return u
        if u.startswith('/'):
            return self.baseUrl + u
        return u

    def homeContent(self, filter):
        classes = [
            {"type_name": x[0], "type_id": x[1]} for x in [
                ("同人/汉化", "1"), ("单行/汉化", "9"), ("短篇/汉化", "10"),
                ("韩漫/汉化", "20"), ("Cosplay", "3"), ("CG画集", "2"), ("3D漫画", "23")
            ]
        ]
        return {"class": classes}

    def homeVideoContent(self):
        return self.categoryContent("1", "1", None, {})

    def categoryContent(self, tid, pg, filter, extend):
        return self.parse_list(f"{self.baseUrl}/albums-index-page-{pg}-cate-{tid}.html", pg, tid)

    def searchContent(self, key, quick, pg="1"):
        key = urllib.parse.quote(key)
        return self.parse_list(f"{self.baseUrl}/search/?q={key}&f=_all&s=create_time_DESC&p={pg}", pg, None)

    def parse_list(self, url, pg, tid):
        try:
            r = self.session.get(url, headers=self.get_header(url), timeout=10, proxies=self.proxies)
            soup = BeautifulSoup(r.text, 'html.parser')
            box = soup.select_one('.gallary_wrap') or soup.select_one('#classify_container')
            items = box.select('li') if box else soup.select('.gallary_item')
            videos = []
            for item in items:
                a = item.select_one('a')
                if not a or "page-" in a.get('href', ''):
                    continue
                title = a.get('title') or a.get_text(strip=True)
                title = re.sub(r'^\s*\[[^\]]+\]|\d{4}-\d{2}-\d{2}.*', '', title).strip()
                img = item.select_one('img')
                pic = self._abs(img.get('src') or img.get('data-src') or "") if img else ""
                info_text = item.get_text()
                count_m = re.search(r'(\d+)\s*[张張P]', info_text)
                count = count_m.group(1) + "P" if count_m else ""
                date_m = re.search(r'(\d{4}-\d{2}-\d{2})', info_text)
                date = date_m.group(1) if date_m else ""
                remark = f"{date} {count}".strip()
                href = a['href']
                if not href.startswith('http'):
                    href = self.baseUrl + '/' + href.lstrip('/')
                videos.append({"vod_id": href, "vod_name": title, "vod_pic": pic, "vod_remarks": remark})
            pages = [int(x) for x in re.findall(r'page-(\d+)-cate-%s\.html' % re.escape(str(tid)), r.text)] if tid else []
            pagecount = max(pages) if pages else 1
            return {"list": videos, "page": pg, "pagecount": pagecount, "limit": len(videos), "total": len(videos)}
        except Exception:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 0, "total": 0}

    def detailContent(self, ids):
        vid = ids[0]
        url = vid if vid.startswith('http') else self.baseUrl + '/' + vid.lstrip('/')
        try:
            r = self.session.get(url, headers=self.get_header(url), timeout=10, proxies=self.proxies)
            r.encoding = 'utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')
            h = soup.select_one('h2') or soup.select_one('h1')
            title = h.get_text(strip=True) if h else "未知标题"
            img = soup.select_one('.pic_box img')
            cover = self._abs(img.get('src') or "") if img else ""
            # 图片列表在画廊页 photos-gallery-aid-*.html 的 imglist 变量里
            play_url = re.sub(r'photos-index', 'photos-gallery', url)
            return {"list": [{
                "vod_id": vid, "vod_name": title, "vod_pic": cover, "vod_type": "漫画",
                "vod_play_from": "绅士漫画",
                "vod_play_url": f"全集${play_url}"
            }]}
        except Exception:
            return {"list": [{"vod_id": vid, "vod_name": "加载失败", "vod_play_from": "绅士漫画", "vod_play_url": f"全集${re.sub(r'photos-index', 'photos-gallery', url)}"}]}

    def playerContent(self, flag, id, vipFlags):
        last_err = ""
        for _ in range(2):
            try:
                r = self.session.get(id, headers=self.get_header(id), timeout=15, proxies=self.proxies)
                img_list = self._parse_imglist(r.text)
                if not img_list:
                    return {"parse": 0, "url": "", "msg": "未找到图片"}
                if self._validate_media(img_list[0]):
                    return {
                        "parse": 0,
                        "url": "pics://" + "&&".join(img_list),
                        "header": json.dumps(self.get_header(id))
                    }
                last_err = "图片签名校验失败"
            except Exception as e:
                last_err = str(e)
        return {"parse": 0, "url": "", "msg": f"Err:{last_err}"}

    def _parse_imglist(self, html):
        # 画廊页把图片列表写在 document.writeln 的 var imglist = [...] 中，条目形如：
        # { url: fast_img_host+"//imgN.wnimg2.cfd/data/xx/xx/0001.jpg?verify=签名", caption: "[0001]" }
        # verify 是 CDN 签名，缺失会被 403，必须随 URL 完整保留（不能用正则按扩展名截断）
        text = html.replace('\\"', '"').replace('\\/', '/')
        seg = ""
        for line in text.splitlines():
            if 'var imglist = ' in line:
                s = line.find('[')
                e = line.rfind(']')
                if s != -1 and e > s:
                    seg = line[s:e + 1]
                break
        if not seg:
            return []
        urls = []
        for um in re.finditer(r'url:\s*(?:fast_img_host\s*\+\s*)?"([^"]+)"', seg):
            u = um.group(1).strip()
            low = u.lower()
            if 'shoucang' in low or '/themes/' in low:
                continue
            if not re.search(r'\.(?:jpg|jpeg|png|webp|gif)(?:\?|$)', low):
                continue
            u = self._abs(u)
            if u and u not in urls:
                urls.append(u)
        return urls

    def _validate_media(self, url):
        try:
            r = self.session.get(url, headers={'User-Agent': self.ua, 'Referer': self.baseUrl + '/'}, timeout=10, stream=True, proxies=self.proxies)
            ok = r.status_code == 200 and 'image' in r.headers.get('Content-Type', '').lower()
            r.close()
            return ok
        except Exception:
            return False

    def localProxy(self, param): pass
