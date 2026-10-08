# coding = utf-8
# !/usr/bin/python
# 新时代青年 2025.06.25 getApp第三版
# 基于原作者修改版本，仅限个人学习爬虫技术，严禁用于任何盈利用途
from Crypto.Cipher import AES
from base.spider import Spider
from Crypto.Util.Padding import pad, unpad
from concurrent.futures import ThreadPoolExecutor, as_completed
import re, sys, time, uuid, json, base64, urllib3, random, hashlib, os, urllib.parse
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.append('..')
TARGET_DOMAIN = 'app.lkdyw.cn'

class Spider(Spider):
    xurl, key, iv, init_data, search_verify = '', '', '', '', ''
    username, password, device_id, version, get_type = '', '', '', '', '0'
    def_headers, auto_vip, line_block, search_timeout = {'User-Agent': 'okhttp/3.14.9'}, 0, [], 10
    vip_purchased, retry_count, sort_keywords, token_cache_file = False, 0, [], ''
    auto_vip_triggered, search_mode, auto_vip_enabled = False, False, False
    base_host, cache_dir = '', ''
    search_index_suffix = 'searchList'
    verify_code = ''
    is_api3 = False

    def _set_cache_filename(self, host):
        try:
            parsed = urllib.parse.urlparse(host)
            domain = parsed.netloc or os.path.basename(parsed.path)
            safe_domain = re.sub(r'[^a-zA-Z0-9_.-]', '_', domain)
            self.cache_dir = '/storage/emulated/0/Download/cache'
            os.makedirs(self.cache_dir, exist_ok=True)
            current_date = time.strftime("%Y%m%d")
            if parsed.netloc == TARGET_DOMAIN:
                self.token_cache_file = os.path.join(self.cache_dir, f"{safe_domain}_token{current_date}.json")
            else:
                self.token_cache_file = os.path.join(self.cache_dir, f"{safe_domain}_token.json")
        except:
            self.cache_dir = '/storage/emulated/0/Download/cache'
            os.makedirs(self.cache_dir, exist_ok=True)
            self.token_cache_file = os.path.join(self.cache_dir, "default_token.json")

    def init(self, extend=''):
        ext = json.loads(extend.strip()) if extend.strip() else {}
        api_map = {
            '2': '/api.php/qijiappapi',
            'qiji': '/api.php/qijiappapi',
            'flutter': '/api.php/getappapi',
            'get': '/api.php/getappapi',
            '3': '/api/vod/'
        }
        api = api_map.get(str(ext.get('api')), '/api.php/getappapi')
        self.get_type = str(ext.get('api')) if str(ext.get('api')) in api_map else 'default'
        self.is_api3 = self.get_type == '3'
        host = ext['host']

        self.search_index_suffix = ext.get('index', 'searchList').strip()
        self.verify_code = ext.get('verify_code', '').strip()

        if not re.match(r'^https?://', host):
            host = 'http://' + host
        parsed_host = urllib.parse.urlparse(host)
        self.base_host = f"{parsed_host.scheme}://{parsed_host.netloc}".rstrip('/')

        domain_set = set()
        if re.match(r'^https?:\/\/[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*(:\d+)?(\/)?$', host):
            domain_set.add(host)
        else:
            host_data = self.fetch(host, headers=self.get_headers(1), timeout=10, verify=False).text
            domain_set.update([d.strip() for d in host_data.split('\n') if d.strip()])

        self.def_headers['User-Agent'] = ext.get('ua', self.def_headers['User-Agent'])
        self.key = ext.get('key', ext.get('datakey'))
        if not self.key: return
        self.iv = ext.get('iv', ext.get('dataiv')) or self.key
        self.device_id = ext.get('devideid') or ext.get('deviceid', '')
        if not self.device_id:
            self.device_id = ''.join(random.choices('0123456789abcdef', k=33))
        self.version, self.username, self.password = str(ext.get('version', '')), ext.get('username'), ext.get('password')
        self.auto_vip = int(ext.get('auto_vip', 0))
        self.auto_vip_enabled = self.auto_vip in (1, 2)
        self.search_mode = ext.get('search', False) in (1, '1', 'true', 'TRUE')
        line_block_conf = ext.get('line_block', '')
        self.line_block = [kw.strip() for kw in (line_block_conf.split(',') if isinstance(line_block_conf, str) else line_block_conf) if kw.strip()]
        from_config = ext.get('from', '').strip()
        if from_config:
            self.sort_keywords = [kw.strip() for kw in from_config.split('>') if kw.strip()]
        self.search_timeout = int(ext.get('time', 10))
        self.search_timeout = 10 if not (0 < self.search_timeout <= 60) else self.search_timeout

        self._set_cache_filename(self.base_host)
        self.load_token_cache()

        if not self.def_headers.get('app-user-token') and ext.get('token'):
            self.def_headers['app-user-token'] = ext.get('token')
        if self.device_id:
            self.def_headers['app-user-device-id'] = self.device_id

        # ==================== 新增：初始化POST请求参数 ====================
        init_post_data = {
            "device_id": self.device_id,
            "version": self.version,
            "timestamp": str(int(time.time()))
        }
        # ===============================================================

        for domain in domain_set:
            try:
                self.xurl = f"{domain}{api}"
                init_api = 'init' if self.is_api3 else 'initV119'
                init_url = f'{self.xurl}{init_api}' if self.is_api3 else f'{self.xurl}.index/{init_api}'

                headers = self.get_headers()
                # ==================== 核心：init改用POST请求 ====================
                res = self.post(
                    url=init_url,
                    data=init_post_data,
                    headers=headers,
                    timeout=(5, 5),
                    verify=False
                ).json()
                # ===============================================================

                self.init_data = json.loads(self.decrypt(res['data']))
                self.search_verify = self.init_data['config'].get('system_search_verify_status', False)
                break
            except Exception as e:
                continue

        if self.auto_vip_enabled and not self.def_headers.get('app-user-token') and not self.vip_purchased:
            self.silent_register_and_buy_vip()
            self.vip_purchased = True

    def fuzzy_sort_lines(self, lines):
        if not lines or not self.sort_keywords: return lines
        def get_sort_weight(line):
            line_name = line['player_show'].lower()
            for idx, kw in enumerate(self.sort_keywords):
                if kw.lower() in line_name: return idx
            return len(self.sort_keywords)
        return sorted(lines, key=lambda x: get_sort_weight(x))

    def load_token_cache(self):
        try:
            parsed_host = urllib.parse.urlparse(self.base_host)
            if parsed_host.netloc == TARGET_DOMAIN:
                current_date = time.strftime("%Y%m%d")
                for file in os.listdir(self.cache_dir):
                    if file.startswith(f"{re.sub(r'[^a-zA-Z0-9_.-]', '_', parsed_host.netloc)}_token") and file.endswith('.json'):
                        if current_date not in file:
                            os.remove(os.path.join(self.cache_dir, file))
            if os.path.exists(self.token_cache_file):
                with open(self.token_cache_file, 'r') as f:
                    cache = json.load(f)
                    if cache.get('host') != self.base_host:
                        return
                    if cache.get('token'):
                        self.def_headers['app-user-token'] = cache['token']
                    if cache.get('device_id'):
                        self.device_id = cache['device_id']
                        self.def_headers['app-user-device-id'] = cache['device_id']
        except:
            pass

    def save_token_cache(self, token, device_id):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cache_data = {'token': token, 'device_id': device_id, 'timestamp': int(time.time()), 'host': self.base_host}
            with open(self.token_cache_file, 'w') as f:
                json.dump(cache_data, f)
        except:
            pass

    def get_headers(self, main=0):
        base_headers = {'Accept-Encoding': 'gzip'}
        if self.get_type == 'qiji': return {**base_headers, 'User-Agent': 'okhttp/3.10.0', 'Connection': 'Keep-Alive', **self.def_headers}
        elif self.get_type == 'flutter':
            flutter_headers = {'User-Agent': 'Dart/3.5 (dart:io)'} if main == 1 else {'User-Agent': '', 'app-version-code': self.version, 'app-os': 'android', 'app-ui-mode': 'light'}
            return {**base_headers, **flutter_headers, **self.def_headers}
        elif self.get_type == 'get':
            timestamp = str(int(time.time()))
            get_headers = {'User-Agent': 'okhttp/3.14.9'} if main == 1 else {'User-Agent': '', 'Connection': 'Keep-Alive', 'app-version-code': self.version, 'app-ui-mode': 'light', 'app-user-device-id': self.device_id, 'app-api-verify-time': timestamp, 'app-api-verify-sign': self.encrypt(timestamp), 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
            return {**base_headers, **get_headers, **self.def_headers}
        elif self.is_api3:
            return {**base_headers, **self.def_headers}
        return {**base_headers, **self.def_headers}

    def login(self):
        if self.username and self.password and self.device_id:
            timestamp = str(int(time.time()))
            headers = self.get_headers().copy()
            headers.update({'app-version-code': "", 'app-ui-mode': 'light', 'app-api-verify-time': timestamp, 'app-api-verify-sign': self.generate_signature(timestamp)})
            login_url = f'{self.xurl}appLogin' if self.is_api3 else f'{self.xurl}.index/appLogin'
            res = self.post(login_url, data={'password': self.password, 'code': "", 'device_id': self.device_id, 'user_name': self.username, 'invite_code': "", 'is_emulator': "0"}, headers=headers).json()
            auth_token = json.loads(self.decrypt(res['data']))['user']['auth_token']
            self.def_headers['app-user-token'] = auth_token
            self.save_token_cache(auth_token, self.device_id)

    def generate_signature(self, timestamp):
        key_bytes = self.key.encode('utf-8')
        iv_bytes = self.iv.encode('utf-8')
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
        padded_timestamp = pad(timestamp.encode('utf-8'), AES.block_size)
        encrypted_bytes = cipher.encrypt(padded_timestamp)
        return base64.b64encode(encrypted_bytes).decode('utf-8')

    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        for item in self.init_data.get('type_list', []):
            if item['type_name'] not in {'全部', 'QQ', 'juo.one'} and '企鹅群' not in item['type_name']:
                result['class'].append({"type_id": item['type_id'], "type_name": item['type_name']})
            filter_items = [{"key": 'by' if ft['name'] == 'sort' else ft['name'], "name": {'class': '类型', 'area': '地区', 'lang': '语言', 'year': '年份', 'sort': '排序'}.get(ft['name'], ft['name']), "value": [{"n": v, "v": v} for v in ft['list']]} for ft in item.get('filter_type_list', []) if ft.get('list')]
            if filter_items: result["filters"][str(item['type_id'])] = filter_items
        return result

    def homeVideoContent(self):
        return {'list': self.arr2vods([vid for item in self.init_data.get('type_list', []) for vid in item.get('recommend_list', [])])}

    def categoryContent(self, cid, pg, filter, ext):
        cate_url = f'{self.xurl}typeFilterVodList' if self.is_api3 else f'{self.xurl}.index/typeFilterVodList'
        res = self.post(cate_url, headers=self.get_headers(), data={'area': ext.get('area', '全部'), 'year': ext.get('year', '全部'), 'type_id': cid, 'page': str(pg), 'sort': ext.get('sort', '最新'), 'lang': ext.get('lang', '全部'), 'class': ext.get('class', '全部')}, verify=False).json()
        return {'list': self.arr2vods(json.loads(self.decrypt(res['data']))['recommend_list']), 'page': pg, 'pagecount': 9999, 'limit': 90, 'total': 999999}

    def _fetch_cate_page(self, page):
        try:
            cate_url = f'{self.xurl}typeFilterVodList' if self.is_api3 else f'{self.xurl}.index/typeFilterVodList'
            res = self.post(cate_url, headers=self.get_headers(), data={'area':'全部','year':'全部','type_id':'0','page':str(page),'sort':'最新','lang':'全部','class':'全部'}, verify=False).json()
            return self.arr2vods(json.loads(self.decrypt(res['data']))['recommend_list'])
        except: return []

    def custom_search(self, key):
        vods, c_page, stop = [], 1, False
        while not stop and c_page <= 100:
            batch_end = min(c_page+4, 100)
            with ThreadPoolExecutor(max_workers=5) as exe:
                tasks = [exe.submit(self._fetch_cate_page, p) for p in range(c_page, batch_end+1)]
                for fut in as_completed(tasks):
                    for v in fut.result():
                        if key in v['vod_name'] and v['vod_id'] not in [x['vod_id'] for x in vods]:
                            vods.append(v)
                            stop = True
                            exe.shutdown(wait=False)
                            break
                    if stop: break
            c_page = batch_end + 1
        return vods

    def searchContent(self, key, quick, pg="1"):
        if self.search_mode:
            return {'list': self.custom_search(key), 'page': int(pg), 'pagecount': 100, 'limit': 90, 'total': len(self.custom_search(key))}
        if 'xiaohys.com' in self.xurl:
            data = self.fetch(f'{self.xurl.split("api.php")[0]}index.php/ajax/suggest?mid=1&wd={key}', timeout=self.search_timeout, verify=False).json()
            return {'list': [{"vod_id": i['id'], "vod_name": i['name'], "vod_pic": i.get('pic')} for i in data['list']], 'page': pg, 'pagecount': 999, 'limit': 30, 'total': 9999}
        payload = {'keywords': key, 'type_id': "0", 'page': str(pg)}
        if self.search_verify:
            if self.verify_code and len(self.verify_code) == 4 and self.verify_code.isdigit():
                verifi = {'code': self.verify_code, 'uuid': str(uuid.uuid4())}
            else:
                verifi = self.verification()
            if not verifi: return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 30, 'total': 0}
            payload.update({'code': verifi['code'], 'key': verifi['uuid']})
        search_url = f'{self.xurl}{self.search_index_suffix}' if self.is_api3 else f'{self.xurl}.index/{self.search_index_suffix}'
        res = self.post(search_url, data=payload, headers=self.get_headers(), verify=False, timeout=self.search_timeout).json()
        if not res.get('data'): return {'list': [], 'msg': res.get('msg'), 'page': pg, 'pagecount': 0, 'limit': 30, 'total': 0}
        return {'list': self.arr2vods(json.loads(self.decrypt(res['data']))['search_list']), 'page': pg, 'pagecount': 999, 'limit': 30, 'total': 9999}

    def detailContent(self, ids):
        did = ids[0]
        payload = {'vod_id': did}
        api_endpoints = ['vodDetail2', 'vodDetail3'] if 'qijiappapi' in self.xurl else ['vodDetail']
        self.login()
        for endpoint in api_endpoints:
            detail_url = f'{self.xurl}{endpoint}' if self.is_api3 else f'{self.xurl}.index/{endpoint}'
            resp = self.post(detail_url, headers=self.get_headers(), data=payload, verify=False)
            if resp.status_code == 200:
                resp_data = resp.json()
                if any(msg in resp_data.get('msg', '') for msg in ['到期', '请先注册登录', '积分', '会员', '登录', '注册']) or resp_data.get('code') == 0:
                    if self.auto_vip_enabled and not self.vip_purchased and self.retry_count < 1 and not self.auto_vip_triggered:
                        self.silent_register_and_buy_vip()
                        self.vip_purchased = True
                        self.retry_count += 1
                        return self.detailContent(ids)
                    return None
                kjson = json.loads(self.decrypt(resp_data['data']))
                filter_keywords = {'防走丢', '群', '防失群', '官网'} | set(self.line_block)
                valid_lines = self.fuzzy_sort_lines([{'player_show': line['player_info']['show'], 'parse': line['player_info']['parse'], 'parse_type': line['player_info']['parse_type'], 'player_parse_type': line['player_info']['player_parse_type'], 'urls': line['urls']} for line in kjson['vod_play_list'] if not any(kw in line['player_info']['show'] for kw in filter_keywords)])
                play_form, play_url, name_count = [], [], {}
                for line in valid_lines:
                    show_name = line['player_show']
                    name_count[show_name] = name_count.get(show_name, 0) + 1
                    if name_count[show_name] > 1: show_name += str(name_count[show_name])
                    play_form.append(show_name)
                    play_url.append('#'.join([f"{vod['name']}${line['parse']},{vod['url']},token+{vod['token']},{line['player_parse_type']},{line['parse_type']}" for vod in line['urls']]))
                vod = kjson['vod']
                return {'list': [{"vod_id": did, "vod_name": vod['vod_name'], "vod_actor": vod['vod_actor'].replace('演员', ''), "vod_director": vod.get('vod_director', '').replace('导演', ''), "vod_content": vod['vod_content'], "vod_remarks": vod['vod_remarks'], "vod_year": vod['vod_year'], "vod_area": vod['vod_area'], "vod_play_from": '$$$'.join(play_form), "vod_play_url": '$$$'.join(play_url)}]}
        return None

    def playerContent(self, flag, vid, vip_Flags):
        uid, raw_url, token, player_parse_type, parse_type = vid.split(',', 4)
        token = token.replace('token+', '')
        default_header = {'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 14; 23113RK12C Build/SKQ1.231004.001)'}
        if parse_type == '0': return {"parse": 0, "url": raw_url, "header": default_header}
        elif parse_type == '2': return {"parse": 1, "url": f'{uid}{raw_url}', "header": default_header}
        elif player_parse_type == '2':
            try: url = self.fetch(f'{uid}{raw_url}', headers=self.get_headers(1), verify=False).json().get('url', '')
            except: url = ''
            return {"parse": 0, "url": url, "header": default_header}
        try:
            parse_url = f'{self.xurl}vodParse' if self.is_api3 else f'{self.xurl}.index/vodParse'
            resp = self.post(parse_url, headers=self.get_headers(), data={'parse_api': uid, 'url': self.encrypt(raw_url), 'player_parse_type': player_parse_type, 'token': token}, verify=False).json()
            url = json.loads(json.loads(self.decrypt(resp['data']))['json']).get('url', '')
        except: url = ''
        return {"parse": 0, "playUrl": '', "url": url, "header": default_header}

    def _is_captcha_error(self, response_msg):
        return any(kw in response_msg for kw in ["验证码", "captcha", "code", "验证", "校验"])

    def _silent_register_core(self):
        try:
            device_id = self.device_id or ''.join(random.choices('0123456789abcdef', k=33))
            username = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=10))
            password = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=10))
            timestamp = str(int(time.time()))
            verifi = None
            if self.auto_vip == 2:
                for _ in range(2):
                    verifi = self.verification()
                    if verifi: break
                    time.sleep(0.5)
                if not verifi: return None, None
            code = verifi['code'] if (self.auto_vip == 2 and verifi) else ""
            key = verifi['uuid'] if (self.auto_vip == 2 and verifi) else str(uuid.uuid4())
            register_data = json.dumps({"password": password, "code": code, "device_id": device_id, "user_name": username, "invite_code": "", "key": key, "is_emulator": 0}, separators=(',', ':'))
            headers = self.get_headers().copy()
            headers.update({"app-version-code": self.version or "120", "app-ui-mode": "light", "app-user-device-id": device_id, "app-api-verify-time": timestamp, "app-api-verify-sign": self.generate_signature(timestamp), "Content-Type": "application/x-www-form-urlencoded", "Connection": "Keep-Alive", "Accept-Encoding": "gzip"})
            reg_url = f'{self.xurl}appRegisterV133' if self.is_api3 else f'{self.xurl}.index/appRegisterV133'
            resp = self.post(reg_url, headers=headers, data={"data": self.encrypt(register_data)}, verify=False, timeout=10)
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json.get("code") != 1 and self._is_captcha_error(resp_json.get("msg", "")) and self.auto_vip == 2:
                    verifi = self.verification()
                    if verifi:
                        code = verifi['code']
                        key = verifi['uuid']
                        register_data = json.dumps({"password": password, "code": code, "device_id": device_id, "user_name": username, "invite_code": "", "key": key, "is_emulator": 0}, separators=(',', ':'))
                        resp = self.post(reg_url, headers=headers, data={"data": self.encrypt(register_data)}, verify=False, timeout=10)
                        resp_json = resp.json()
                if resp_json.get("code") == 1:
                    token = json.loads(self.decrypt(resp_json["data"]))['user'].get('auth_token')
                    if token: return token, device_id
        except: pass
        return None, None

    def silent_register_and_buy_vip(self):
        max_retries = 3
        for _ in range(max_retries):
            token, device_id = self._silent_register_core()
            if token and device_id:
                self.def_headers.update({'app-user-token': token, 'app-user-device-id': device_id})
                self.device_id = device_id
                self.save_token_cache(token, device_id)
                self.silent_buy_vip(token, device_id)
                self.auto_vip_triggered = True
                return True
            if self.auto_vip == 2: time.sleep(1)
        return False

    def silent_buy_vip(self, token, device_id):
        try:
            timestamp = str(int(time.time()))
            headers = self.get_headers().copy()
            headers.update({"app-version-code": self.version or "120", "app-ui-mode": "light", "app-user-device-id": device_id, "app-user-token": token, "app-api-verify-time": timestamp, "app-api-verify-sign": self.generate_signature(timestamp), "Content-Type": "application/x-www-form-urlencoded", "Connection": "Keep-Alive", "Accept-Encoding": "gzip"})
            buy_vip_url = f'{self.xurl}userBuyVip' if self.is_api3 else f'{self.xurl}.index/userBuyVip'
            resp = self.post(buy_vip_url, headers=headers, data={"index": "0"}, verify=False, timeout=10)
            return resp.status_code == 200 and resp.json().get("code") == 1
        except: return True

    def arr2vods(self, arr):
        return [{'vod_id': item['vod_id'], 'vod_name': item['vod_name'], 'vod_pic': item.get('vod_pic'), 'vod_remarks': item.get('vod_remarks')} for item in arr if isinstance(arr, list) and item.get('vod_id')]

    def decrypt(self, encrypted_data_b64):
        cipher = AES.new(self.key.encode('utf-8'), AES.MODE_CBC, self.iv.encode('utf-8'))
        return unpad(cipher.decrypt(base64.b64decode(encrypted_data_b64)), AES.block_size).decode('utf-8')

    def encrypt(self, sencrypted_data):
        cipher = AES.new(self.key.encode('utf-8'), AES.MODE_CBC, self.iv.encode('utf-8'))
        return base64.b64encode(cipher.encrypt(pad(sencrypted_data.encode('utf-8'), AES.block_size))).decode('utf-8')

    def verification(self):
        try:
            uuid_str = str(uuid.uuid4())
            verify_url = f'{self.xurl}verify/create?key={uuid_str}' if self.is_api3 else f'{self.xurl}.verify/create?key={uuid_str}'
            img_data = self.fetch(verify_url, headers=self.get_headers(), verify=False).content
            if not img_data: return None
            code = self.ocr(base64.b64encode(img_data).decode('utf-8'))
            if not code: return None
            replacements = {'y':'9','口':'0','q':'0','u':'0','o':'0','>':'1','d':'0','b':'8','已':'2','D':'0','五':'5'}
            if len(code) == 3: code = code.replace('566', '5066').replace('066', '1666')
            code = ''.join(replacements.get(c, c) for c in code)
            return {'uuid': uuid_str, 'code': code} if len(code) == 4 and code.isdigit() else None
        except: return None

    def ocr(self, base64img):
        try: return self.post('https://api.nn.ci/ocr/b64/text', data=base64img, headers=self.get_headers(1), verify=False).text.strip() or None
        except: return None

    def localProxy(self, params):
        proxy_map = {"m3u8": self.proxyM3u8, "media": self.proxyMedia, "ts": self.proxyTs}
        return proxy_map.get(params.get('type'))(params) if proxy_map.get(params.get('type')) else None

    def getName(self): pass
    def isVideoFormat(self, url): pass
    def manualVideoCheck(self): pass
