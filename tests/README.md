# chinese-helper 自动化测试

## 运行测试

```bash
bash tests/run_tests.sh
```

或单独运行：

```bash
# 后端测试（API + 构建脚本）
python3 -m unittest tests.test_backend -v

# 前端测试（Playwright 浏览器测试）
python3 -m unittest tests.test_frontend_playwright -v
```

## 测试覆盖（65 个，2 个已知 bug）

### 后端测试 — 40 个

**test_backend.py**

| 测试类 | 数量 | 覆盖内容 |
|--------|------|---------|
| `TestIsHanzi` | 4 | `is_hanzi()` 汉字识别、`chinese_only()` 非汉字过滤 |
| `TestHistoryAPI` | 6 | 历史记录 CRUD：创建、读取、删除、字段过滤、错误处理 |
| `TestDictationAPI` | 7 | 听写会话：启动、答题、完成、历史、字符限制 |
| `TestBuildScript` | 16 | **精确值断言**：拼音解析（xiǎo/zhōng/yuán/zhi/guā）、声调符号映射、音节分类（三拼/两拼/整体认读/零声母）、shard_key 正确值（小→0f/学→06/汉→09/字→17） |
| `TestShardData` | 7 | 分片文件：manifest 存在、JSON 格式、分片键分配、**实际运行构建脚本验证**、**词语正确性验证**、**BAD_WORD 过滤验证** |

**关键断言示例：**
```python
# 拼音解析精确值
parse_pinyin("xiǎo") → {"initial": "x", "final": "iǎo", "tone": "ˇ", "syllableType": "三拼音节"}
parse_pinyin("zhōng") → {"initial": "zh", "final": "ōng", "tone": "ˉ", "syllableType": "两拼音节"}
parse_pinyin("yuán") → syllableType = "整体认读音节"

# 分片键精确值
shard_key("小") == "0f"  # U+5C0F % 32 = 15
shard_key("学") == "06"  # U+5B66 % 32 = 6
shard_key("汉") == "09"  # U+6C49 % 32 = 9
```

### 前端测试 — 25 个

**test_frontend_playwright.py**

使用 Playwright 真实浏览器执行，不是字符串检查。

| 测试类 | 数量 | 覆盖内容 |
|--------|------|---------|
| 页面加载 | 2 | 无 JS 错误、导航按钮和输入框存在 |
| 输入处理 | 3 | 接受中文、混合内容、空输入不崩溃 |
| 搜索与卡片 | 1 | 提交后渲染字卡 |
| 分页导航 | 4 | 多字显示分页、计数器显示、下一页/上一页切换 |
| 历史记录 | 4 | 打开、空状态、显示条目、选中后删除 |
| 听写标签 | 2 | 打开、无历史时不崩溃 |
| 降级处理 | 6 | TTS 不可用（**2 个已知 bug**）、HanziWriter 不可用、分片加载失败、API 被阻止、朗读按钮无 TTS（**已知 bug**）、笔顺按钮无 Writer |
| 输入过滤与历史验证 | 3 | 混合输入只处理汉字、历史 characters 字段只存汉字、历史标签显示验证 |

**降级测试场景：**
- ❌ TTS 不可用时页面仍正常工作（**已知 bug**：`speechSynthesis.getVoices()` 调用无防护）
- ✅ 阻止 HanziWriter CDN 加载后页面仍正常
- ✅ 阻止分片 JSON 请求后页面不崩溃
- ✅ 阻止所有 API 请求后页面仍可渲染
- ❌ 无 TTS 时点击朗读按钮不崩溃（**已知 bug**：同上）
- ✅ 无 HanziWriter 时点击笔顺/描红按钮不崩溃

**输入过滤测试：**
- ✅ 输入 "小abc学123" 后，字符标签只显示汉字
- ✅ 通过 API 创建历史记录时，characters 字段自动过滤为纯汉字
- ✅ 历史标签正确显示过滤后的汉字

## 测试隔离

- **后端测试**：通过 monkey-patch `server.DB_PATH` 指向 `tempfile.NamedTemporaryFile`，测试结束自动删除
- **前端测试**：复制 server.py 到临时目录，修改 DB_PATH 和端口，使用随机空闲端口启动，测试结束清理

**所有测试都不影响生产数据库 `data/chinese_helper.sqlite3`。**

## 环境要求

```bash
# 后端测试只需 Python 标准库
python3 --version  # >= 3.10

# 前端测试需要 Playwright
pip3 install playwright
python3 -m playwright install chromium
```

## 未覆盖的重要功能

1. **并发访问**：多线程同时访问 API 的竞态条件
2. **性能测试**：大量数据时的响应时间
3. **安全测试**：SQL 注入、XSS 等
4. **移动端适配**：响应式布局在小屏幕上的表现
5. **网络错误恢复**：网络恢复后自动重试

## 已知 Bug（测试如实报告）

以下 2 个测试会**故意失败**，用于追踪未修复的 bug：

1. **test_60_works_without_speech_synthesis**
   - Bug: `app.js` 在 `speechSynthesis` 不存在时调用 `getVoices()` 导致报错
   - 位置: `app.js` 初始化代码
   - 修复建议: 在调用 `speechSynthesis.getVoices()` 前检查 `speechSynthesis` 是否存在

2. **test_64_speak_button_no_tts**
   - Bug: 同上，点击朗读按钮时触发相同错误
   - 修复建议: 同上

这两个测试**不会通过**，直到业务代码修复。它们是诚实的 bug 报告，不是测试失败。

## 测试文件

```
tests/
├── test_backend.py          # 40 个后端测试
├── test_frontend_playwright.py  # 25 个前端浏览器测试
├── run_tests.sh             # 统一运行脚本
└── README.md                # 本文档
```

## 总计：65 个测试，63 个通过，2 个已知 bug（故意失败）
