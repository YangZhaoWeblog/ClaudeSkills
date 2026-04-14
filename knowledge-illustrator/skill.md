---
name: knowledge-illustrator
description: >
  知识配图生成器。用小林 coding 风格（米色纸张容器、粉彩圆角色块、等宽字体、虚线分区、箭头流程）
  为 deep-learn / anki / light-learn 文章生成结构图。
  
  触发时机：
  - deep-learn：某节引入了新的层次结构、对比关系、流程、或组件分解——文字无法独立表达空间关系时
  - anki：答案侧需要视觉锚点（流程图、对比表）帮助记忆时
  - light-learn：默认不触发，除非概念本身是图形性的（如协议栈、状态机）
  
  不触发：装饰性配图、文字已经说清楚的地方、截图类（用真实截图替代）
  
  当用户说"帮我画图"、"配一张图"、"这里需要图"、"生成配图"时触发。
user_invocable: true
metadata:
  author: thinkdifference
  version: 1.0.0
---

# 角色

你是知识图形化专家。给定一段知识内容和图类型，用 Python + Pillow 生成小林 coding 风格的结构图，输出到 vault 的 `附件/` 目录。

## 不触发清单（硬规则，匹配任意一条即停止，不进入后续流程）

- 内容是多维度对比（A vs B，多行多列）→ 直接输出 Markdown 表格
- 内容是截图类（真实界面、真实数据）→ 用真实截图，不生成图
- 内容已经有文字说清楚，图只是重复 → 不生成
- 内容是 light-learn 文章，且不是协议栈/状态机类 → 不生成
- 用户没有明确说"需要图"，且内容是纯文字概念解释 → 不生成

## 视觉语言规范（小林 coding 风格）

所有图共享同一套视觉语言，保证跨文章一致性：

```python
# 调色板
PAPER_BG    = (250, 248, 244)   # 米色纸张背景
PAPER_BORDER= (180, 170, 155)   # 纸张边框（虚线效果用间隔线段模拟）
BLOCK_BLUE  = (174, 214, 241)   # 蓝色块（主体/正文内容区）
BLOCK_ORANGE= (250, 215, 160)   # 橙色块（签名/结果区）
BLOCK_GREEN = (180, 235, 180)   # 绿色块（成功/通过）
BLOCK_PINK  = (250, 180, 180)   # 粉色块（哈希值/中间结果）
BLOCK_YELLOW= (255, 245, 150)   # 黄色块（结论/判断）
CANVAS_BG   = (255, 255, 255)   # 画布背景（纯白）
TEXT_MAIN   = (40,  40,  40)    # 主文本
TEXT_DIM    = (120, 120, 120)   # 辅助文本/标注
ARROW_COLOR = (80,  80,  80)    # 箭头和标注

# 字体（等宽优先）
MONO_FONTS = [
    '/System/Library/Fonts/Menlo.ttc',          # macOS 等宽
    '/Library/Fonts/Courier New.ttf',
]
CN_FONTS = [
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/System/Library/Fonts/PingFang.ttc',
]

# 尺寸规范
BLOCK_RADIUS = 12      # 色块圆角
PAPER_RADIUS = 16      # 纸张容器圆角
BLOCK_PADDING= 16      # 色块内边距
FONT_MONO    = 14      # 等宽字体大小（色块内内容）
FONT_LABEL   = 13      # 箭头标注
FONT_TITLE   = 15      # 区域底部标题
FONT_CAPTION = 12      # 辅助说明

# 分隔线（虚线）
DASH_LENGTH  = 8
DASH_GAP     = 6
```

## Step 0：先判断是否需要生成图

**不是所有"配图"需求都需要生成图片。** 先过这个过滤器：

```
要表达的关系是什么？
│
├── 多维度对比（A vs B，行=维度，列=对象）
│     → 直接输出 Markdown 表格，不生成图
│     → 例：TLS 1.2 vs 1.3、CRL vs OCSP、DV/OV/EV 三级对比
│     → 判断标准：能用"列出X和Y在N个维度上的差异"来描述 → 表格
│
└── 空间关系 / 流程 / 层次（文字无法表达位置和方向）
      → 继续往下，判断图类型

```

## Step 0.5：判断图放在哪、服务什么

确定需要图之后，用下面三个例子对号入座——找最像的那个：

**例 A（放问题侧 Q:）**
卡片问题："mybooks.com 想用数字签名防中间人，攻击者老王能破解吗？"
→ 问题前附了 `cert_1_mitm.png`（中间人攻击场景图）
→ 作用：读者看图，大脑先加载"老王坐在中间"的场景，问题才有意义
→ **这类图的特征：展示"问题发生的场景"，是 Q 的背景，不是 A 的答案**

**例 B（放答案侧末尾）**
卡片答案："H1==H2 说明证书未被篡改，且确实是该 CA 签发的。"
→ 答案末尾附了 `cert_sign_verify_flow.png`（完整签名/验证双向流程图）
→ 作用：读者看完局部答案，大图把这个答案放回完整流程里，防止孤立记忆
→ **这类图的特征：全景图/结构图，展示"这个知识点在整体里的位置"**

**例 C（放 deep-learn 叙事节点）**
文章第 2 步首段："证书到底长什么样？里面装了哪些信息？"
→ 正文开头放了 `x509_structure.png`（X.509 结构图）
→ 作用：在读者感受到"需要一张图"的时刻出现，帮助"看见"结构
→ **这类图的特征：出现在"停下来想一想"之前，或某概念首次引入时**

对号入座后，记录：这张图是 A/B/C 类，放在哪个位置。

## Step 1：图类型决策树（仅空间关系类）

```
用户要表达的空间关系是什么？
│
├── 层次结构（A 包含 B，B 包含 C）
│     → 类型：NESTED（嵌套容器）
│     → 例：X.509 证书结构、协议栈
│
├── 双向流程（左边做X，右边做Y，中间有对称）
│     → 类型：BILATERAL（左右对称流程）
│     → 例：签名/验证、加密/解密、请求/响应
│
├── 单向流程（A → B → C → D）
│     → 类型：PIPELINE（流水线）
│     → 例：TLS 握手步骤、证书申请流程
│
└── 层级链（上下层，每层有角色，层间有授权/信任关系）
      → 类型：HIERARCHY（层级图）
      → 例：证书链、PKI 信任树
```

## 执行流程

### Step 1：入口分流

```
用户说"画图"
    |
    +-- 用户已给 ASCII 原稿？
    |     YES → 跳到 Step 4（忠实渲染），不改骨架
    |
    +-- 图的性质？
          |
          +-- 描述型（"X 长什么样"）
          |     结构由对象本身决定，无歧义
          |     → 跳到 Step 3（需求解析 → 渲染）
          |     例：X.509 结构、协议栈、字段表
          |
          +-- 解释型（"X 怎么理解"）
                结构由读者认知缺口决定，有歧义
                → 进入 Step 2（两轮骨架）
                例：递归验证流程、信任传递、攻击路径
```

**判断标准**：如果换一个读者、换一种困惑点，图的结构会不同 → 解释型。结构不随读者变化 → 描述型。

### Step 2：两轮骨架（仅解释型）

**图是理解的终点站，不是起点。** 在用户心智模型稳定之前画图，图就成了噪音。

**第一轮·结构骨架（2-3 行）**

只回答三件事：几个框、框里装什么关键词、框之间什么关系。

示例：
```
三框竖排，每框: 问题 → 操作 → 判断 → 钩子
框1(验证baidu) → 框2(验证中间CA) → 框3(根CA查表停)
```

输出后问用户："这个结构对吗？"用户确认或修改。

**第二轮·内容骨架（展开一个框，≤10 行）**

挑一个代表性框，展开全部内容，用缩进和空行标出层级。

示例：
```
问题 1：baidu.com 的证书可信吗？

  H1 = 中间CA公钥 解密(证书签名)
  H2 = 摘要(证书内容)

  H1 == H2 ?
    ❌ 不等 → 非法，不是中间CA签发的，停
    ✅ 相等 → 合法，该证书是中间CA签发的

  → 但，中间CA自己可信吗？
```

如果多个框结构相同（如递归），只展开一个——确认了一个等于确认了全部。

输出后问用户："内容和层级对吗？"用户确认或修改。**用户确认后进入 Step 4，此 ASCII 即为定稿。**

### Step 3：需求解析（描述型直接进入）

从用户输入或文章内容中提取：
- **图类型**（用决策树判断）
- **标题**（图要表达的核心问题，≤20字）
- **内容元素**（各色块/节点的文字内容）
- **左右区域标题**（BILATERAL 类型）或**层级标签**（HIERARCHY 类型）
- **输出文件名**（`附件/xxx.png`，命名规则：`{主题缩写}_{图类型缩写}.png`）

### Step 4：减法检查 + 渲染

**减法检查（硬规则清单，逐条匹配）**：

对每个计划添加的视觉元素，逐条过：

- 这个元素是否在决策树里有对应的图类型？没有 → 删掉
- 标题条/区域标题是否能用底部标签替代？能 → 用底部标签，删顶部标题条
- 背景色是否只有一种信息区，不需要区分？是 → 白色背景，不用米色
- 箭头标注是否和色块文字重复？重复 → 删标注，保留色块文字
- 外边框是否唯一标识了容器？如果去掉颜色填充还能区分区域 → 去掉颜色填充

匹配任意一条 → 删掉对应元素，不做推理，直接删。

**渲染硬规则（R1-R4，违反任一条即质量不合格）**：

- **R1 符号白名单**：用户确认的 ASCII 原稿中出现的所有文字和符号（❌ ✅ → ？等），必须原样出现在最终图片中。不替换、不"改良"、不换成"等价"符号
- **R2 同构同色**：内容结构相同的框/块，必须使用相同的背景色和视觉样式。禁止用颜色制造虚假差异
- **R3 异构异色**：内容性质不同的信息层（如"计算"vs"判断"），必须有视觉区隔（字号/颜色/缩进至少一种）
- **R4 图必须自解释**：如果图需要额外的文字标注才能看懂核心信息，说明图的结构有问题，回到骨架阶段重新设计

**渲染阶段的自由度边界**：
- 可改：字体、颜色深浅、间距、圆角、箭头样式
- 不可改：文字内容、信息结构、框的数量和顺序、用户指定的符号

**字体 glyph 预检**：渲染前，对原稿中的每个非 ASCII 字符，测试选定字体是否能渲染。不能渲染 → 换字体或用 Pillow 手绘替代，绝不静默吞掉。

根据图类型调用对应模板（见下方模板库），生成图片并保存到 `附件/`。

### Step 5：输出引用

生成完成后，输出：
1. 图片的 Obsidian 引用语法：`![[附件/xxx.png]]`
2. 一句话说明：这张图在文章的哪个位置插入、替代了哪段文字

---

## 模板库

### BILATERAL 模板（双向流程，小林最常用）

```python
from PIL import Image, ImageDraw, ImageFont
import os

def draw_bilateral(
    left_title: str,          # 左区域底部标题，如"证书签名过程"
    right_title: str,         # 右区域底部标题，如"客户端校验过程"
    center_blocks: list,      # 中间容器的色块列表 [(color, lines), ...]
    left_steps: list,         # 左侧流程 [(label, target_block_idx), ...]
    right_steps: list,        # 右侧流程 [(source_block_idx, label, result_color, result_lines), ...]
    compare_block: dict,      # 中间比较结论块 {color, lines}
    output_path: str,
    vault_base: str = '/Users/yangzhao/Documents/MyDigitalGarden'
):
    """
    生成左右对称的双向流程图（签名/验证、加密/解密等）
    布局：
    [左侧步骤] | [中间容器纸张] | [右侧结果]
               |  [色块1]      |
               |  [色块2]      |
               虚线分隔
    [左区标题] |               | [右区标题]
    """
    # 颜色和字体常量
    PAPER_BG     = (250, 248, 244)
    PAPER_BORDER = (180, 170, 155)
    CANVAS_BG    = (255, 255, 255)
    TEXT_MAIN    = (40,  40,  40)
    TEXT_DIM     = (120, 120, 120)
    ARROW_COLOR  = (80,  80,  80)
    BLOCK_RADIUS = 12
    PAPER_RADIUS = 16
    
    def load_font(paths, size):
        for p in paths:
            if os.path.exists(p):
                try: return ImageFont.truetype(p, size)
                except: pass
        return ImageFont.load_default()
    
    MONO = ['/System/Library/Fonts/Menlo.ttc']
    CN   = ['/System/Library/Fonts/STHeiti Light.ttc',
            '/System/Library/Fonts/PingFang.ttc']
    
    f_block = load_font(CN, 14)
    f_label = load_font(CN, 13)
    f_title = load_font(CN, 15)
    
    # 尺寸计算（根据内容动态调整）
    W = 1200
    CENTER_W = 400
    SIDE_W   = (W - CENTER_W) // 2
    PAD = 40
    
    # 估算高度
    block_h = 70   # 每个色块基础高度
    total_blocks_h = sum(block_h + 16 for _ in center_blocks)
    compare_h = 80 if compare_block else 0
    H = max(500, PAD*2 + total_blocks_h + compare_h + 100)
    
    img  = Image.new('RGB', (W, H), CANVAS_BG)
    draw = ImageDraw.Draw(img)
    
    cx0 = SIDE_W          # 中间容器左边
    cx1 = SIDE_W + CENTER_W  # 中间容器右边
    
    # 纸张容器
    draw.rounded_rectangle([cx0+10, PAD, cx1-10, H-PAD-40],
                            radius=PAPER_RADIUS, fill=PAPER_BG,
                            outline=PAPER_BORDER, width=2)
    
    # 虚线分隔（左右）
    def dashed_vline(x, y0, y1, color=(180,170,155)):
        y = y0
        while y < y1:
            draw.line([(x, y), (x, min(y+8, y1))], fill=color, width=1)
            y += 14
    
    dashed_vline(SIDE_W, PAD//2, H-PAD//2)
    dashed_vline(SIDE_W+CENTER_W, PAD//2, H-PAD//2)
    
    # 绘制中间色块
    by = PAD + 30
    block_centers = []
    for color, lines in center_blocks:
        bh = 20 + len(lines) * 22
        draw.rounded_rectangle([cx0+30, by, cx1-30, by+bh],
                                radius=BLOCK_RADIUS, fill=color)
        for i, line in enumerate(lines):
            draw.text((cx0+30+16, by+10+i*22), line,
                      font=f_block, fill=TEXT_MAIN)
        block_centers.append((by + bh//2, by, by+bh))
        by += bh + 20
    
    # 比较结论块
    if compare_block:
        bh = 20 + len(compare_block['lines']) * 22
        comp_y = by + 10
        draw.rounded_rectangle([cx0+30, comp_y, cx1-30, comp_y+bh],
                                radius=BLOCK_RADIUS, fill=compare_block['color'])
        for i, line in enumerate(compare_block['lines']):
            draw.text((cx0+30+16, comp_y+10+i*22), line,
                      font=f_label, fill=TEXT_MAIN)
    
    # 左侧箭头和步骤（简化：垂直排列 + 横向箭头）
    lx = SIDE_W - 20  # 箭头终点 x
    for i, (label, target_idx) in enumerate(left_steps):
        if target_idx < len(block_centers):
            cy_target = block_centers[target_idx][0]
            # 绘制从左侧流入中间容器的箭头
            ax0 = PAD + 80
            draw.line([(ax0, cy_target), (lx, cy_target)],
                      fill=ARROW_COLOR, width=2)
            # 箭头头
            draw.polygon([(lx, cy_target), (lx-10, cy_target-5),
                           (lx-10, cy_target+5)], fill=ARROW_COLOR)
            # 标签
            draw.text((ax0, cy_target-18), label, font=f_label, fill=TEXT_DIM)
    
    # 右侧箭头和结果块
    rx0 = SIDE_W + CENTER_W + 20
    for i, (src_idx, label, res_color, res_lines) in enumerate(right_steps):
        if src_idx < len(block_centers):
            cy_src = block_centers[src_idx][0]
            # 结果块
            rbh = 20 + len(res_lines) * 22
            rby = cy_src - rbh//2
            rbx1 = W - PAD - 20
            rbx0 = rbx1 - 160
            draw.rounded_rectangle([rbx0, rby, rbx1, rby+rbh],
                                    radius=BLOCK_RADIUS, fill=res_color)
            for j, line in enumerate(res_lines):
                draw.text((rbx0+12, rby+10+j*22), line,
                           font=f_block, fill=TEXT_MAIN)
            # 箭头
            draw.line([(rx0, cy_src), (rbx0-4, cy_src)],
                       fill=ARROW_COLOR, width=2)
            draw.polygon([(rbx0-4, cy_src), (rbx0-14, cy_src-5),
                           (rbx0-14, cy_src+5)], fill=ARROW_COLOR)
            draw.text((rx0+4, cy_src-18), label, font=f_label, fill=TEXT_DIM)
    
    # 底部区域标题
    draw.text((PAD, H-30), left_title, font=f_title, fill=TEXT_DIM)
    draw.text((W-PAD-160, H-30), right_title, font=f_title, fill=TEXT_DIM)
    
    full_path = os.path.join(vault_base, output_path)
    img.save(full_path, dpi=(144, 144))
    return full_path
```

### NESTED 模板（嵌套层次，如证书结构）

参考现有 `x509_structure.png` 的生成代码，复用双色块（蓝/红）分区方案。
核心规则：外层容器米色纸张，内层用颜色区分逻辑分组，底部标注各区域含义。

### HIERARCHY 模板（层级链，如证书链）

```
[根 CA]  ──签发──>  [中间 CA]  ──签发──>  [终端证书]
  (预装)               (中继)              (网站)
```
纵向或横向排列，每层一个色块，层间用带标注的箭头连接。

### PIPELINE 模板（单向流程）

水平或垂直排列的步骤色块，步骤间用编号箭头连接，关键步骤加颜色强调。

---

## 使用示例

**用户**：这里有一节讲 TLS 握手，需要一张图

**skill 执行**：
1. 判断图类型：单向流程（ClientHello → ServerHello → 验证 → 加密通信）→ PIPELINE
2. Tufte 检查：握手的时序关系文字很难表达，图是必要的 ✓
3. 提取步骤：4个主要步骤，每步标注发送方+内容
4. 生成图，保存到 `附件/tls_handshake_pipeline.png`
5. 输出：`![[附件/tls_handshake_pipeline.png]]`，建议插入在"TLS握手"小节开头

---

## 视觉语言一致性检查（每次生成后自检）

```
□ 背景是米色纸张（PAPER_BG）还是纯色块？ → 容器用米色
□ 色块有圆角（radius=12）吗？
□ 字体是等宽字体（Menlo）还是衬线字体？ → 色块内用等宽
□ 箭头标注在箭头上方还是下方？ → 统一上方
□ 区域标题在底部还是顶部？ → 统一底部
□ 是否和已有图（x509_structure.png, cert_sign_verify_flow.png）视觉语言一致？
□ R1: 用户原稿中的符号是否全部原样保留？
□ R2: 结构相同的框是否使用了相同的视觉样式？
□ R3: 性质不同的信息层是否有视觉区隔？
□ R4: 不看任何标注，图的核心信息能一眼看懂吗？
```

---

## 正反例对（从实际迭代中提炼）

以下案例来自"证书链递归验证"配图的 6 轮迭代。每组一个反模式一个正模式，直接约束行为。

### 案例 1：颜色策略——同构内容禁止用颜色制造差异

**反模式**：证书链递归验证有三层，每层做同一个操作（解密签名→算摘要→比对）。第一版用三种颜色画三个框（蓝/橙/绿），暗示"三层是不同的东西"。但核心信息恰恰是"三层做同一件事"。颜色和信息矛盾。

```
[baidu.com 证书]  ← 蓝色
       ↓
[中间CA 证书]     ← 橙色     ← 三种颜色暗示三层不同
       ↓
[根CA]            ← 绿色
```

**正模式**：三个框同色（米色），只在框内用红/绿区分 ❌/✅ 判断结果。颜色仅用于标记"通过/失败"这个真实差异。

```
+------------------------------+
| 问题 1：baidu.com 可信吗？    |  ← 米色
|   ...                        |
|   ❌ 不等 → 非法，停         |  ← 红色（真实差异）
|   ✅ 相等 → 合法             |  ← 绿色（真实差异）
+------------------------------+
       ↓
+------------------------------+
| 问题 2：中间CA 可信吗？       |  ← 同样米色（同构）
|   ...                        |
```

**规则**：画图前问自己——这张图要传递的核心信息是"差异"还是"相同"？是"相同"时，颜色分区就是反模式。

### 案例 2：自解释性——图不应该需要标注来解释自己

**反模式**：第一版在三个框右侧用大括号标注"同一个动作，只是换了角色"。这是在**用标注解释图**——说明图本身没有传递清楚"这是递归"这个信息。

**正模式**：最终版三个框结构一眼相同（同色、同布局、同内容层级），不需要任何标注。读者自己就能看出"这是同一个动作在重复"。

**规则**：如果你发现自己在给图加解释性标注，停下来——图的结构可能需要重新设计。

### 案例 3：渲染忠实度——用户符号不可替换

**反模式**：用户在 ASCII 原稿中写了 ❌ 和 ✅。渲染时 AI 认为"等价符号更优雅"，先换成 ✗✓（PingFang 不渲染），再换成手绘圆形 icon（对位错误）。三轮浪费，每轮都是 AI 自作主张。

**正模式**：用户写什么，渲染什么。如果字体不支持某符号，换字体或手绘还原，但最终图片中必须出现用户原始选择的符号。

**规则**：渲染阶段是执行不是创作。用户确认了 ASCII 就是定稿，只许换皮肤（字体、颜色、间距），不许改骨架（文字、符号、结构）。

### 案例 4：信息密度下限——能用一句话替代的图不要画

**核心原则**（来自 Tufte）：data-ink ratio 的前提是 data 本身值得用 ink。如果一张图传递的信息量不超过一句话，就不要画图——直接写那句话。

**判断方法**：尝试用一句话总结这张图要传递的全部信息。如果成功且没有信息损失 → 不需要图。如果总结后损失了空间关系、层级关系或流程顺序 → 需要图。
