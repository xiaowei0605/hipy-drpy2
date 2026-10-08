// 从壳子内置目录加载cheerio
import cheerio from 'assets://js/lib/cheerio.min.js';

// 或者本地自备
// import cheerio from '../lib/cheerio.min.js';

const sites = [
    'https://www.cd-zj.com',
    'https://www.gzwlr.com',
]
const appConfig = {
    siteName: "枫叶4k影院",
    siteUrl: sites[0] // 默认使用 cd-zj.com
}
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36";
const Headers = {
    "User-Agent": UA,
    "Referer": appConfig.siteUrl + "/",
}
async function init(ext) {
    // 可以在这里做初始化配置
}

function getYearFilter() {
    let years = [{ "n": "全部", "v": "" }];
    const currentYear = new Date().getFullYear().toString();
    for (let y = currentYear; y >= currentYear - 22; y--) {
        years.push({ "n": String(y), "v": String(y) });
    }
    return { "key": "year", "name": "年份", "value": years };
}

function getLetterFilter() {
    return {
        "key": "letter", "name": "字母", "value": [
            { "n": "全部", "v": "" },
            { "n": "A", "v": "A" }, { "n": "B", "v": "B" }, { "n": "C", "v": "C" }, { "n": "D", "v": "D" },
            { "n": "E", "v": "E" }, { "n": "F", "v": "F" }, { "n": "G", "v": "G" }, { "n": "H", "v": "H" },
            { "n": "I", "v": "I" }, { "n": "J", "v": "J" }, { "n": "K", "v": "K" }, { "n": "L", "v": "L" },
            { "n": "M", "v": "M" }, { "n": "N", "v": "N" }, { "n": "O", "v": "O" }, { "n": "P", "v": "P" },
            { "n": "Q", "v": "Q" }, { "n": "R", "v": "R" }, { "n": "S", "v": "S" }, { "n": "T", "v": "T" },
            { "n": "U", "v": "U" }, { "n": "V", "v": "V" }, { "n": "W", "v": "W" }, { "n": "X", "v": "X" },
            { "n": "Y", "v": "Y" }, { "n": "Z", "v": "Z" }, { "n": "0-9", "v": "0-9" }
        ]
    }
}
const OtherFilters = [

    {
        "key": "area", "name": "地区", "value": [
            { "n": "全部", "v": "" }, { "n": "大陆", "v": "大陆" }, { "n": "香港", "v": "香港" },
            { "n": "台湾", "v": "台湾" }, { "n": "美国", "v": "美国" }, { "n": "韩国", "v": "韩国" },
            { "n": "日本", "v": "日本" }, { "n": "泰国", "v": "泰国" }, { "n": "新加坡", "v": "新加坡" },
            { "n": "马来西亚", "v": "马来西亚" }, { "n": "印度", "v": "印度" }, { "n": "英国", "v": "英国" },
            { "n": "法国", "v": "法国" }, { "n": "加拿大", "v": "加拿大" }, { "n": "西班牙", "v": "西班牙" },
            { "n": "俄罗斯", "v": "俄罗斯" }, { "n": "其它", "v": "其它" }
        ]
    },
    getYearFilter(),
    {
        "key": "lang", "name": "语言", "value": [
            { "n": "全部", "v": "" }, { "n": "国语", "v": "国语" }, { "n": "英语", "v": "英语" },
            { "n": "粤语", "v": "粤语" }, { "n": "闽南语", "v": "闽南语" }, { "n": "韩语", "v": "韩语" },
            { "n": "日语", "v": "日语" }, { "n": "其它", "v": "其它" }
        ]
    },
    getLetterFilter()
];

const myFilters = {
    // 电视剧
    "2": [
        {
            key: "type", "name": "类型", value: [
                { "n": "全部", "v": "2" },
                { "n": "国产剧", "v": "13" },
                { "n": "日韩剧", "v": "15" },
                { "n": "海外剧", "v": "16" },
            ]
        },
        {
            "key": "class", "name": "剧情", "value": [
                { "n": "全部", "v": "" }, { "n": "古装", "v": "古装" }, { "n": "战争", "v": "战争" },
                { "n": "青春偶像", "v": "青春偶像" }, { "n": "喜剧", "v": "喜剧" }, { "n": "家庭", "v": "家庭" },
                { "n": "犯罪", "v": "犯罪" }, { "n": "动作", "v": "动作" }, { "n": "奇幻", "v": "奇幻" },
                { "n": "剧情", "v": "剧情" }, { "n": "历史", "v": "历史" }, { "n": "经典", "v": "经典" },
                { "n": "乡村", "v": "乡村" }, { "n": "情景", "v": "情景" }, { "n": "商战", "v": "商战" },
                { "n": "网剧", "v": "网剧" }, { "n": "其他", "v": "其他" }
            ]
        },
        ...OtherFilters
    ],
    // 电影
    "1": [
        {
            "key": "type", "name": "类型", "value": [
                { "n": "全部", "v": "1" },
                { "n": "动作片", "v": "6" },
                { "n": "喜剧片", "v": "7" },
                { "n": "恐怖片", "v": "8" },
                { "n": "科幻片", "v": "9" },
                { "n": "爱情片", "v": "10" },
                { "n": "剧情片", "v": "11" }
            ]
        },
        {
            "key": "class", "name": "剧情", "value": [
                { "n": "全部", "v": "" },
                { "n": "喜剧", "v": "喜剧" },
                { "n": "爱情", "v": "爱情" },
                { "n": "恐怖", "v": "恐怖" },
                { "n": "动作", "v": "动作" },
                { "n": "科幻", "v": "科幻" },
                { "n": "剧情", "v": "剧情" },
                { "n": "战争", "v": "战争" },
                { "n": "警匪", "v": "警匪" },
                { "n": "犯罪", "v": "犯罪" },
                { "n": "动画", "v": "动画" },
                { "n": "奇幻", "v": "奇幻" },
                { "n": "武侠", "v": "武侠" },
                { "n": "冒险", "v": "冒险" },
                { "n": "枪战", "v": "枪战" },
                { "n": "悬疑", "v": "悬疑" },
                { "n": "惊悚", "v": "惊悚" },
                { "n": "经典", "v": "经典" },
                { "n": "青春", "v": "青春" },
                { "n": "文艺", "v": "文艺" },
                { "n": "微电影", "v": "微电影" },
                { "n": "古装", "v": "古装" },
                { "n": "历史", "v": "历史" },
                { "n": "运动", "v": "运动" },
                { "n": "农村", "v": "农村" },
                { "n": "儿童", "v": "儿童" },
                { "n": "网络电影", "v": "网络电影" }
            ]
        },
        ...OtherFilters
    ],
    // 动漫
    "4": [
        {
            "key": "type", "name": "类型", "value": [
                { "n": "全部", "v": "4" },
                { "n": "国产动漫", "v": "25" },
                { "n": "日韩动漫", "v": "26" },
            ]
        },
        {
            "key": "class", "name": "剧情", "value": [
                { "n": "全部", "v": "" },
                { "n": "情感", "v": "情感" },
                { "n": "科幻", "v": "科幻" },
                { "n": "热血", "v": "热血" },
                { "n": "推理", "v": "推理" },
                { "n": "搞笑", "v": "搞笑" },
                { "n": "冒险", "v": "冒险" },
                { "n": "萝莉", "v": "萝莉" },
                { "n": "校园", "v": "校园" },
                { "n": "动作", "v": "动作" },
                { "n": "机战", "v": "机战" },
                { "n": "运动", "v": "运动" },
                { "n": "战争", "v": "战争" },
                { "n": "少年", "v": "少年" },
                { "n": "少女", "v": "少女" },
                { "n": "社会", "v": "社会" },
                { "n": "原创", "v": "原创" },
                { "n": "亲子", "v": "亲子" },
                { "n": "益智", "v": "益智" },
                { "n": "励志", "v": "励志" },
                { "n": "其他", "v": "其他" }
            ]
        },
        ...OtherFilters
    ],
    // 综艺
    "3": [
        {
            "key": "type", "name": "类型", "value": [
                { "n": "全部", "v": "3" },
                { "n": "大陆综艺", "v": "21" },
                { "n": "日韩综艺", "v": "22" },
            ]
        },
        {
            "key": "class", "name": "剧情", "value": [
                { "n": "全部", "v": "" },
                { "n": "选秀", "v": "选秀" },
                { "n": "情感", "v": "情感" },
                { "n": "访谈", "v": "访谈" },
                { "n": "播报", "v": "播报" },
                { "n": "旅游", "v": "旅游" },
                { "n": "音乐", "v": "音乐" },
                { "n": "美食", "v": "美食" },
                { "n": "纪实", "v": "纪实" },
                { "n": "曲艺", "v": "曲艺" },
                { "n": "生活", "v": "生活" },
                { "n": "游戏互动", "v": "游戏互动" },
                { "n": "财经", "v": "财经" },
                { "n": "求职", "v": "求职" }
            ]
        },
        ...OtherFilters
    ],
    // 短剧
    "5": [
        getYearFilter(),
        getLetterFilter()
    ],
};

async function home(filter) {
    return JSON.stringify({
        class: [
            { type_id: "", type_name: "热映推荐" },
            { type_id: "/label/qq", type_name: "腾讯精选" },
            { type_id: "/label/bli", type_name: "哔哩精选" },
            { type_id: "/label/youku", type_name: "优酷精选" },
        ],
        filters: myFilters
    });
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    let type = extend.type || tid;

    const isLanel = tid && tid.startsWith("/label");
    let url = "";

    // 根据站点确定前缀
    const isGzwlr = appConfig.siteUrl === 'https://www.gzwlr.com';
    const typePrefix = isGzwlr ? "list" : "cupfox-list";
    const searchPrefix = isGzwlr ? "search" : "cupfox-search";

    if (isLanel) {
        // 标签页
        url = appConfig.siteUrl + tid + `/page/${pg}.html`;
    } else if (type === "" || type === "5") {
        // 热门短剧或首页推荐
        if (type === "5") {
            // 短剧分类
            let classVal = extend.class || '';
            let areaVal = extend.area || '';
            let langVal = extend.lang || '';
            let letterVal = extend.letter || '';
            let orderVal = extend.orderBy || '';
            let yearVal = extend.year || '';
            url = `${appConfig.siteUrl}/${typePrefix}/5-${areaVal}-${''}-${classVal}-${langVal}-${letterVal}-${orderVal}-${''}-${pg}-${''}-${''}-${yearVal}.html`;
        } else {
            url = appConfig.siteUrl;
        }
    } else {
        // 分类筛选
        let classVal = extend.class || '';
        let areaVal = extend.area || '';
        let langVal = extend.lang || '';
        let letterVal = extend.letter || '';
        let orderVal = extend.orderBy || '';
        let yearVal = extend.year || '';

        url = `${appConfig.siteUrl}/${typePrefix}/${type}-${areaVal}-${''}-${classVal}-${langVal}-${letterVal}-${orderVal}-${''}-${pg}-${''}-${''}-${yearVal}.html`;
    }

    const html = (await req(url)).content;
    const $ = cheerio.load(html);
    let list = [];

    // 适配两种站点的列表选择器
    $(".public-list-div.public-list-bj").each(function (index, el) {
        let vod_id = $(el).find("a.public-list-exp").attr("href");
        let vod_name = $(el).find("a.public-list-exp").attr("title")?.trim() || '';
        let vod_pic = $(el).find(".public-list-exp img").attr("data-src") || $(el).find(".public-list-exp img").attr("src") || '';
        let vod_remarks = $(el).find(".ft2").text().trim();
        let text4k = $(el).find('.public-list-exp .public-prt-g').text().trim() || '';
        text4k = text4k ? `「${text4k}」` : '';
        let updateTime = $(el).find('.public-list-exp .public-prt')?.eq(1).text().trim() || '';
        let vod_year = text4k + " " + updateTime;

        list.push({
            vod_id,
            vod_name,
            vod_pic,
            vod_remarks,
            vod_year
        });
    });

    // 如果上面的选择器没抓到，尝试备用选择器
    if (list.length === 0) {
        $(".video-item, .movie-item, .public-list-bj").each(function (index, el) {
            let vod_id = $(el).find("a").attr("href") || '';
            let vod_name = $(el).find("a").attr("title")?.trim() || $(el).find(".title").text().trim() || '';
            let vod_pic = $(el).find("img").attr("data-src") || $(el).find("img").attr("src") || '';
            let vod_remarks = $(el).find(".remarks, .status").text().trim() || '';
            
            if (vod_id && vod_name) {
                list.push({
                    vod_id,
                    vod_name,
                    vod_pic,
                    vod_remarks,
                    vod_year: ''
                });
            }
        });
    }

    const pageStr = $('.page-tip').text().trim();
    const pagecount = pageStr.match(/\d+\/(\d+)页/)?.[1] || 
                      $('.page-count, .total-page').text().match(/(\d+)/)?.[1] || 
                      1;

    return JSON.stringify({
        list,
        pagecount: parseInt(pagecount) || 1
    });
}

async function search(wd, quick, page) {
    if (page >= 2) {
        return JSON.stringify({ list: [], pagecount: 1 });
    }
    try {
        const isGzwlr = appConfig.siteUrl === 'https://www.gzwlr.com';
        const searchPrefix = isGzwlr ? "search" : "cupfox-search";
        const url = `${appConfig.siteUrl}/${searchPrefix}/-------------.html?wd=${encodeURIComponent(wd)}`;
        
        const html = (await req(url)).content;
        const $ = cheerio.load(html);
        let list = [];

        // 适配搜索结果的多种选择器
        $('.search-box, .video-item, .public-list-div').each((i, el) => {
            const vod_id = $(el).find("a.thumb-txt, a.title, a").attr('href') || '';
            const vod_name = $(el).find(".thumb-txt a, .title a, .name").text().trim() || 
                             $(el).find("a").attr('title')?.trim() || '';
            const vod_pic = $(el).find('.left img, .thumb img, img').attr('data-src') || 
                            $(el).find('.left img, .thumb img, img').attr('src') || '';
            const vod_remarks = $(el).find('.public-list-prb, .remarks, .status').text().trim() || '';

            if (vod_id && vod_name) {
                list.push({
                    vod_id,
                    vod_name,
                    vod_pic,
                    vod_remarks
                });
            }
        });

        return JSON.stringify({
            list: list,
            pagecount: 1
        });
    } catch (e) {
        console.error("❌ search 遭遇内部崩溃 =", e.message);
        return JSON.stringify({ list: [] });
    }
}

async function detail(id) {
    try {
        const url = appConfig.siteUrl + id;
        const response = await req(url);
        const html = response ? response.content : '';
        const $ = cheerio.load(html);

        // 1. 基础信息解析
        const vod_name = $('.slide-info-title').text().trim() || 
                         $('.title, .detail-title').text().trim() || '';
        const vod_pic = $('.detail-pic img').attr("data-src") || 
                        $('.detail-pic img').attr("src") || 
                        $('.cover img').attr("src") || '';
        const vod_actor = $('.detail-info .slide-info').eq(2).text().replace(/演员：\s*/, '').trim() || 
                          $('.actor, .cast').text().trim() || '';
        const vod_remarks = $('.detail-info .slide-info').eq(4).text().replace(/连载\s*:\s*/, '').trim() || 
                            $('.status, .update').text().trim() || '';
        const vod_content = $('#height_limit').text().trim() || 
                            $('.desc, .summary, .content').text().trim() || '';

        // 2. 线路名称
        const lines = [];
        $('.swiper-slide, .play-tab, .tab-item').each((i, el) => {
            const lineName = $(el).clone().find('i, span, .badge').remove().end().text().trim();
            if (lineName) lines.push(lineName);
        });

        // 如果没抓到线路，尝试备用选择器
        if (lines.length === 0) {
            $('.play-source, .source-tab a, .play-list-tab').each((i, el) => {
                const lineName = $(el).text().trim();
                if (lineName) lines.push(lineName);
            });
        }

        // 3. 剧集列表
        const playlists = [];
        $('.anthology-list-box, .play-list, .episode-list').each((lineIndex, poolEl) => {
            const episodes = [];
            $(poolEl).find('a').each((episodeIndex, epEl) => {
                const name = $(epEl).text().trim();
                const href = $(epEl).attr('href') || '';
                if (name && href) {
                    episodes.push(`${name}\$${href}`);
                }
            });
            if (episodes.length > 0) {
                playlists.push(episodes);
            }
        });

        // 如果没抓到，尝试备用选择器
        if (playlists.length === 0) {
            $('.playlist, .episode-group').each((i, el) => {
                const episodes = [];
                $(el).find('a, .episode a').each((j, epEl) => {
                    const name = $(epEl).text().trim();
                    const href = $(epEl).attr('href') || '';
                    if (name && href) {
                        episodes.push(`${name}\$${href}`);
                    }
                });
                if (episodes.length > 0) {
                    playlists.push(episodes);
                }
            });
        }

        // 4. 处理剧集数据
        const { vod_play_from, vod_play_url } = buildVodPlayData(lines, playlists, true);

        const vod = {
            vod_id: id,
            vod_name,
            vod_pic,
            vod_actor,
            vod_remarks,
            vod_content,
            vod_play_from,
            vod_play_url
        };

        return JSON.stringify({ list: [vod] });

    } catch (error) {
        console.error(`解析详情页异常 [ID: ${id}]:`, error);
        return JSON.stringify({ list: [] });
    }
}

function buildVodPlayData(lines, playlists, shouldReverse = true) {
    const processedPlaylists = playlists.map(eps => {
        if (shouldReverse) {
            eps.reverse();
        }
        return eps.join('#');
    });
    return {
        vod_play_from: lines.filter(Boolean).join('$$$'),
        vod_play_url: processedPlaylists.join('$$$')
    };
}

function isDirectUrl(url) {
    return url && (url.startsWith('http') || url.endsWith(".m3u8") || url.endsWith(".mp4"));
}

async function parsePLayUrl(is2kLine, url) {
    const parseApiUrl = is2kLine ? "https://zzrs.mfdyvip.com" : "https://fgsrg.hzqingshan.com";
    
    try {
        const htmlRes = await req(`${parseApiUrl}/player/?url=${url}`, { method: 'GET', headers: Headers });
        const token = cheerio.load(htmlRes.content)('#player-data').attr('data-te');
        
        if (!token) {
            console.log("未获取到token，尝试备用解析方式");
            // 尝试直接返回原URL
            return url;
        }
        
        let playDataRes = await req(`${parseApiUrl}/player/mplayer.php`, {
            method: 'POST',
            headers: {
                'User-Agent': UA,
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            },
            body: `url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`
        });
        
        const result = JSON.parse(playDataRes.content);
        return result.url || '';
    } catch (e) {
        console.error("解析播放地址失败:", e.message);
        return "";
    }
}

async function play(flag, id, flags) {
    try {
        const html = (await req(`${appConfig.siteUrl}${id}`)).content;
        const url = getPlayUrl(html);

        console.log("play url =", url);

        if (!url) {
            return JSON.stringify({ parse: 0, url: "", msg: "未找到播放地址" });
        }

        if (isDirectUrl(url)) {
            return JSON.stringify({
                parse: 0,
                header: {
                    "User-Agent": UA
                },
                url,
            });
        }

        const is2kLine = flag && flag.includes('2k');
        const playUrl = await parsePLayUrl(is2kLine, url);

        if (!playUrl) {
            return JSON.stringify({ parse: 0, url: "", msg: "解析失败，请更换线路" });
        }

        return JSON.stringify({
            parse: 0,
            header: {
                "User-Agent": UA
            },
            url: playUrl
        });
    } catch (e) {
        console.error("❌ play 遭遇内部崩溃 =", e);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

function getPlayUrl(html) {
    // 尝试多种匹配模式
    let match = html.match(/var\s+player_aaaa[\s\S]*?"url"\s*:\s*"([^"]+)"/);
    let url = match ? match[1] : '';
    
    if (!url) {
        match = html.match(/"url"\s*:\s*"([^"]+)"/);
        url = match ? match[1] : '';
    }
    
    if (!url) {
        match = html.match(/player_aaaa\s*=\s*\{[\s\S]*?url:\s*['"]([^'"]+)['"]/);
        url = match ? match[1] : '';
    }
    
    url = url.replace(/\\/g, '');
    return url;
}

export default { init, home, category, detail, search, play };