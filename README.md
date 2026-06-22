# chinese-helper
面向小学生的本地学习助手，当前包含首页、语文、数学、英文四个学习入口。语文支持汉字、拼音、笔顺、组词、造句、记录和听写练习；数学和英文先保留最小入口，后续逐步扩展。

## 本地运行

这是一个本地网页 MVP，不需要安装第三方依赖。默认用 SQLite 保存查询历史。

推荐方式：启动本地服务。

```bash
python3 server.py
```

然后访问 `http://127.0.0.1:4173`。

数据库文件会自动创建在 `data/chinese_helper.sqlite3`。

只看页面、不保存历史时，也可以直接用浏览器打开 `index.html`。

也可以使用普通静态服务，但不会启用 SQLite 接口：

```bash
python3 -m http.server 4173
```

## 功能范围

- 顶部导航包含首页、语文、数学、英文。
- 首页是学生学习入口，提供语文、数学、英文三张学科入口卡片。
- 语文下包含汉字、字义、组词、造句、记录、听写。
- 汉字学习支持输入一个或多个汉字，并通过“一字一页”分页展示学习卡片。
- 卡片内部使用 Tab 分区：字形拼音、字义、笔顺、组词造句，减少首屏拥挤。
- 田字格展示大字，包含外框、横中线、竖中线和两条对角辅助线。
- **笔顺动画与描红练习**：每张卡片可播放笔顺动画，也可进入描红测验（基于 [Hanzi Writer](https://hanziwriter.org/) CDN）。
- 展示带调拼音、声调符号、声母、韵母、音节类型、多音字。
- 展示笔画名称、笔画符号和总笔画数。
- 展示部首、字形结构、本义、近义词、反义词。
- 展示 3-5 个适合小学生的常见组词、分级造句和量词搭配。
- 字义页按顿号分割输入，分别输出近义词和反义词。
- 组词页按顿号分割输入，每个字输出常见组词。
- 造句页按顿号分割输入，为每个字或词输出 3 条句子。
- 支持 Web Speech 朗读汉字、组词和句子；浏览器无中文语音时会降级为默认语音。
- 使用 SQLite 保存本地查询历史。
- 记录页可查看学习历史，支持搜索、按功能过滤、单选/多选删除；点击记录会自动切换到对应功能并回填查询。
- 支持打印当前结果页。
- 接入 `chinese-xinhua` 作为本地兜底数据源，避免常见字查询为空。
- 页面采用暖色护眼背景、大字号拼音信息和楷体/宋体优先字体栈，方便小学生观看。
- 数学和英文当前只做轻量入口，不引入复杂题库或词库。

## 兜底数据（按需懒加载）

精选字数据位于 `data/seed-characters.json`，不会直接挂到 `window`。构建脚本会把精选字和 `chinese-xinhua` 兜底数据合并后切成 32 个 JSON 分片，存放在 `data/generated/chars/<XX>.json`。页面只按输入内容 fetch 对应分片，避免首页一次性加载大文件，也避免 `window.CHARACTER_DATA` 这类全局变量污染。

重新生成兜底数据：

```bash
python3 scripts/download_chinese_xinhua.py
python3 scripts/build_fallback_data.py
```

会在 `data/generated/` 下生成：

- `chars/00.json` … `chars/1f.json` — 按 `ord(char) % 32` 分片
- `manifest.json` — 各分片字数统计

原始大文件下载到 `data/vendor/chinese-xinhua/`，分片与清单默认不进入版本库。

## 数据结构

精选字源数据位于 `data/seed-characters.json`，字段保持为：

```js
{
  character: "小",
  pinyin: "xiǎo",
  tone: "ˇ",
  initial: "x",
  final: "iǎo",
  syllableType: "普通音节",
  strokes: [
    { name: "竖钩", mark: "亅" },
    { name: "撇", mark: "丿" },
    { name: "点", mark: "丶" }
  ],
  radical: "小",
  structure: "独体字",
  meaning: "本义指细小、微小，也可以表示年纪小或程度轻。",
  antonyms: ["大"],
  synonyms: ["细", "微"],
  words: ["小学", "小心", "大小"],
  sentences: {
    beginner: "小鸟在树上唱歌。",
    intermediate: "我们要从小养成爱读书的好习惯。",
    advanced: "虽然这件事很小，但能看出他认真负责的态度。"
  },
  measureWords: ["一个小朋友", "一只小鸟", "一件小事"],
  polyphonic: []
}
```
