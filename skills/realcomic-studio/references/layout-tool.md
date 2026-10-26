# 历史本地排版工具（新漫画页禁止使用）

本文件与脚本保留用于理解旧版本和历史格式，不是当前新漫画的制作路径。禁止用它拼格、叠加文字、补边或裁切来制作/修订新漫画页；其中 overlay、contain、cover、render 及气泡绘制仅是历史能力说明。新页须整页原生一体化、默认3:4，PDF仅将原页无改动转封装并保留PNG。


`scripts/comic_tool.py`只校验与排版已有图片，不联网、不生图。仅当前宿主有可写文件工作区、Python 3.10+和Pillow时使用；Work/Dots无需为了使用本插件连接Windows电脑。无脚本环境时使用当前宿主实际可用的导出能力；没有合成能力则交付已成图与页表，并标明尚未导出的文件。

这是基础矩形排版工具，不支持斜切/异形蒙版、层叠画格或人物突破边框。`box` 范围内的图会按 `contain`/`cover` 放置，不能用它实现角色跨格。所有新漫画页都使用内置图片工具整页原生生成；不要为了使用本脚本，把创意页改回横平竖直。

```powershell
python scripts/comic_tool.py check chapter.json
python scripts/comic_tool.py render chapter.json --out-dir output --prefix ch01 --dpi 150 --min-font-px 24
python scripts/comic_tool.py render chapter.json --out-dir output2 --font C:\Windows\Fonts\msyh.ttc
```

上面的Windows字体路径仅为Windows环境示例；其他环境使用当前宿主存在的字体，不把示例路径当成依赖。

`check` 允许未完成面板（`planned` 和空 `image`）。`render` 要求每格 `status: "approved"`、图片存在且可读。默认导出文件已存在时会报错，请换目录或前缀；不会覆盖源图片、JSON、字体或已有导出。渲染前先完成全部页面绘制，成功后输出逐页 PNG、栅格多页 PDF 和 JSON manifest。PDF 默认 150 DPI，可用正整数 `--dpi` 调整。

顶层 JSON：`schema_version: 1`、非空 `title`、`chapter_id`、`text_mode: "overlay" | "integrated"`、`reading_order: "ltr" | "rtl" | "vertical"`、`cast: [{"id":"hero","name":"角色名"}]`、`pages`。`integrated` 模式禁止气泡数据，避免重复文字。

每页：安全文件名 `id`（ASCII 字母/数字开头，后接字母/数字/下划线/连字符；拒绝系统保留名）、正整数 `width` / `height`、`background: "#RRGGBB"`、非空 `panels`。每格：全章唯一 `id`、全章唯一连续正整数 `order`、页内整数像素 `box: [x,y,w,h]`、相对 JSON 所在目录的 `image` 路径或 `null`、`status: "planned" | "generated" | "approved"`、`fit: "contain" | "cover"`、`bubbles: []`。格子不可重叠。页数组确定 PDF 页序；每页的 `order` 必须组成连续区间，页内按 `order` 绘制。

封面/正文/封底的计页与文字规则见[book-design.md](book-design.md)。可在项目页表记录`page_kind`与`story_page_number`，但本脚本不消费这些元数据、不自动增补封面封底，也不绘制页眉或页号；`check`通过不等于正文数量正确。需要导出完整册时，将已完成封面、正文和封底按实际顺序放入`pages`，并由制作方核对数量；`fit: "cover"`仅是裁切方式，不是封面类型。示例JSON只演示正文排版，不代表完整册默认省略封面封底。

每个气泡：`type: "speech" | "thought" | "caption" | "sfx"`、`speaker` 为 cast id 或 `narrator`、非空 `text`、本格相对坐标 `box: [x,y,w,h]`（0–1 且完整位于格内）、可选 `tail: [x,y]`（本格相对坐标）。脚本绘制气泡、旁白、思考泡、拟声、可选尾巴，并按字符自动换行和缩放字体；默认最小字号为 `max(12, ceil(页面宽度 × 0.02))`，1200 px 页为 24 px。可用 `--min-font-px` 指定至少 12 px；达不到最小字号会报错。中文默认尝试 Windows 微软雅黑/黑体及 Linux NotoSansCJK，找不到时需指定 `--font` 的绝对 TTF/OTF/TTC 路径。自选字体的中文字形覆盖需在导出的 PNG 中目视验收。

透明图先合成白底；JPEG 先按 EXIF 方向转正。`contain` 完整保留图片，空余部分填白；`cover` 中心裁切。manifest 记录源图片绝对路径、SHA-256、raw 与转正后尺寸、布局方式与裁切说明、实际页面尺寸、文字及字体像素、导出文件 SHA-256。阅读方向只作为元数据保存；格子位置与阅读顺序由输入 JSON 定义。PDF 为栅格页面，文字不可编辑或检索。此工具不检查画面内容、叙事质量和版权。

