# 更新记录

## 2026-05-22

- 调整输入框，增加一键清空按钮。
- 修正笔顺动画、描红练习按钮文字居中问题。
- 笔顺动画按田字格实际尺寸创建，减少点击后字形偏移。
- 去掉浏览器端 `window.CHARACTER_DATA` 全局数据，精选字统一合并进 shard 分片。
- 为 HanziWriter CDN 脚本增加 `preconnect` 和 `preload`。
- 后端汉字过滤范围扩展到 CJK 扩展区，避免未来扩展数据源时丢失罕用字。
- 清理 `.gitignore` 中已经废弃的 `data/generated/fallback-data.js`。
- 更新 README，补充 Tab、一字一页分页、Web Speech 朗读、护眼配色和当前数据策略。
- 新增 `docs/design.md` 记录当前 MVP 的设计决策。
- 修正笔顺面板文案：区分“文本笔画名称未收录”和“动态笔顺可播放”，避免误判为笔顺异常。
