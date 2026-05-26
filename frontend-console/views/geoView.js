/**
 * 地理历史视图
 *
 * 子标签：地点树 | 地理关系 | 历史时期 | 地点历史 | 简易地图
 */
const geoView = {
  /** @type {Array} 地点树数据 */
  _locationTree: [],

  /** @type {Array} 地点列表 */
  _locations: [],

  /** @type {Array} 历史时期 */
  _eras: [],

  /** @type {Array} 地理关系边 */
  _edges: [],

  /** @type {Object|null} 当前选中的地点 */
  _selectedLocation: null,

  /** @type {boolean} API 是否可用 */
  _apiAvailable: false,

  /**
   * 进入视图时加载数据
   */
  async onEnter() {
    if (!_state.currentProjectId) {
      this._locations = []
      this._locationTree = []
      this._eras = []
      this._edges = []
      return
    }

    const projectId = _state.currentProjectId
    this._apiAvailable = true

    // 并发加载地点、时期、关系
    await Promise.all([
      this._loadLocations(projectId),
      this._loadEras(projectId),
      this._loadEdges(projectId),
    ])
  },

  /**
   * 从 API 加载地点列表和树
   */
  async _loadLocations(projectId) {
    try {
      const data = await api.geo.listLocations({ novel_id: projectId })
      this._locations = data.items || data || []
      this._buildTree()
    } catch {
      this._apiAvailable = false
      this._locations = []
      this._locationTree = this._buildDemoTree()
      toast("后端未连接，使用演示数据", "warning")
    }
  },

  /**
   * 从 API 加载历史时期
   */
  async _loadEras(projectId) {
    try {
      if (!this._apiAvailable) throw new Error("API 不可用")
      const data = await api.geo.listEras(projectId)
      this._eras = data.items || data || []
    } catch {
      this._eras = [
        { id: "era-1", name: "旧王朝时期", order_index: 1, summary: "王权鼎盛，商路繁荣" },
        { id: "era-2", name: "焚城前", order_index: 2, summary: "黑塔污染加剧，社会动荡" },
        { id: "era-3", name: "焚城后", order_index: 3, summary: "迁都与封锁，旧王都成禁区" },
        { id: "era-4", name: "主线开始时", order_index: 4, summary: "禁区被遗忘，王印重现" },
      ]
    }
  },

  /**
   * 从 API 加载地理关系边
   */
  async _loadEdges(projectId) {
    try {
      if (!this._apiAvailable) throw new Error("API 不可用")
      const data = await api.geo.listEdges({ novel_id: projectId })
      this._edges = data.items || data || []
    } catch {
      this._edges = [
        { id: "e1", source: "边境村", target: "王都", relation_type: "road_to", travel_time: "三日马车" },
        { id: "e2", source: "王都", target: "旧王都", relation_type: "road_to", travel_time: "半日/封锁", difficulty: "困难" },
        { id: "e3", source: "北境", target: "边境村", relation_type: "road_to", travel_time: "二日" },
      ]
    }
  },

  /**
   * 从 locations 数组构建树结构
   */
  _buildTree() {
    if (this._locations.length === 0) {
      this._locationTree = this._buildDemoTree()
      return
    }
    this._locationTree = this._nestedList(this._locations, null)
  },

  /**
   * 构建嵌套地点列表
   */
  _nestedList(items, parentId) {
    const children = items.filter((l) => (l.parent_location_id || l.parent_id) === parentId)
    return children.map((l) => ({
      id: l.id || l.location_id,
      name: l.name,
      level: l.location_level,
      children: this._nestedList(items, l.id || l.location_id),
    }))
  },

  /**
   * 构建演示地点树
   */
  _buildDemoTree() {
    return [
      {
        id: "world", name: "世界", level: "world", children: [
          {
            id: "kingdom", name: "王国", level: "kingdom", children: [
              { id: "capital", name: "王都", level: "city", children: [
                { id: "court", name: "王庭监察院", level: "district", children: [
                  { id: "archive", name: "地下档案室", level: "building" },
                ]},
                { id: "palace", name: "王宫", level: "building" },
              ]},
              { id: "old_capital", name: "旧王都", level: "city", children: [
                { id: "ruins", name: "外围废墟", level: "district" },
                { id: "seal", name: "地下封印区", level: "district" },
              ]},
              { id: "north", name: "北境", level: "region", children: [
                { id: "border_village", name: "边境村", level: "village" },
              ]},
            ]},
        ]},
    ]
  },

  // ============================================================
  // render()
  // ============================================================

  async render() {
    const subView = _state.currentSubView || "tree"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "tree" ? "active" : ""}" data-subview="tree" onclick="router.navigate('geo','tree')">地点树</span>
        <span class="subnav-item ${subView === "edges" ? "active" : ""}" data-subview="edges" onclick="router.navigate('geo','edges')">地理关系</span>
        <span class="subnav-item ${subView === "eras" ? "active" : ""}" data-subview="eras" onclick="router.navigate('geo','eras')">历史时期</span>
        <span class="subnav-item ${subView === "history" ? "active" : ""}" data-subview="history" onclick="router.navigate('geo','history')">地点历史</span>
        <span class="subnav-item ${subView === "map" ? "active" : ""}" data-subview="map" onclick="router.navigate('geo','map')">简易地图</span>
      </div>
    `

    if (subView === "tree") html += this._renderTree()
    else if (subView === "edges") html += this._renderEdges()
    else if (subView === "eras") html += this._renderEras()
    else if (subView === "history") html += this._renderHistory()
    else if (subView === "map") html += this._renderMap()

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  // ============================================================
  // 地点树
  // ============================================================

  _renderTree() {
    const treeHtml = this._renderTreeNodes(this._locationTree)
    return `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        小说世界的地点层级结构。点击地点可查看详情。
        ${!this._apiAvailable ? '<span style="color:var(--warning);">（使用演示数据）</span>' : ""}
      </p>
      ${this._locations.length === 0 && this._locationTree.length > 0 ? `
      <div style="margin-bottom:12px;">
        ${treeHtml}
      </div>
      ` : `
      <div style="margin-bottom:12px;">
        ${treeHtml}
      </div>
      `}
      <div style="margin-top:12px;">
        <button class="btn btn-primary" id="btn-new-location">新建地点</button>
        <button class="btn" onclick="router.navigate('geo','edges')">查看地理关系</button>
        <button class="btn" onclick="router.navigate('geo','history')">查看地点历史</button>
      </div>
    `
  },

  /**
   * 递归渲染树节点
   */
  _renderTreeNodes(nodes, depth = 0) {
    if (!nodes || nodes.length === 0) return '<p style="color:var(--text-dim);">暂无地点</p>'

    let html = '<ul class="tree" style="text-align:left;">'
    for (const node of nodes) {
      const levelStyles = {
        world: "color:var(--accent);font-weight:bold;",
        kingdom: "color:var(--text);font-weight:bold;",
        region: "color:var(--text);",
        city: "color:var(--text);",
        district: "color:var(--text-muted);",
        village: "color:var(--text-dim);",
        building: "color:var(--text-dim);font-size:12px;",
      }
      const style = levelStyles[node.level] || ""
      const hasChildren = node.children && node.children.length > 0

      html += '<li>'
      html += `<span class="tree-item clickable" style="${style}" data-location-id="${node.id}" onclick="geoView._onLocationClick('${node.id}')">`
      html += hasChildren ? "&#128193; " : "&#128204; "
      html += `${node.name}`
      if (node.level) html += ` <span style="color:var(--text-dim);font-size:11px;">(${node.level})</span>`
      html += "</span>"
      if (hasChildren) {
        html += this._renderTreeNodes(node.children, depth + 1)
      }
      html += "</li>"
    }
    html += "</ul>"
    return html
  },

  /**
   * 点击地点事件
   */
  _onLocationClick(locationId) {
    // 查找地点详情
    const findNode = (nodes) => {
      for (const n of nodes) {
        if (n.id === locationId) return n
        if (n.children) {
          const found = findNode(n.children)
          if (found) return found
        }
      }
      return null
    }

    const node = findNode(this._locationTree) || { id: locationId, name: locationId }
    this._selectedLocation = node

    // 更新右侧信息栏
    _state.rightPanel = {
      title: node.name,
      type: "location",
      content: `
        <div class="help-section">
          <h4>${node.name}</h4>
          <p>层级：${node.level || "未知"}</p>
          <p style="color:var(--text-dim);font-size:12px;margin-top:8px;">
            <strong>相关操作</strong><br>
            <a style="cursor:pointer;color:var(--accent);" onclick="router.navigate('geo','history')">查看地点历史</a><br>
            <a style="cursor:pointer;color:var(--accent);" onclick="router.navigate('geo','edges')">查看通行关系</a>
          </p>
        </div>
      `,
    }

    toast(`已选择：${node.name}`, "info")
  },

  // ============================================================
  // 地理关系
  // ============================================================

  _renderEdges() {
    if (!this._edges || this._edges.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128279;</div>
          <p>暂无地理关系</p>
          <p style="color:var(--text-dim);font-size:12px;">地点之间的通行路线和访问限制。</p>
        </div>
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">地点之间的通行路线和访问限制。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>起点</th>
            <th>关系</th>
            <th>终点</th>
            <th>用时</th>
            <th>难度</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const e of this._edges) {
      const srcName = typeof e.source === "object" ? (e.source.name || e.source.id) : (e.source || e.source_location_id || "")
      const tgtName = typeof e.target === "object" ? (e.target.name || e.target.id) : (e.target || e.target_location_id || "")
      const relMap = {
        road_to: "→ 道路",
        river_to: "→ 水路",
        inside: "⊂ 位于内部",
        north_of: "北",
        south_of: "南",
        near: "≈ 附近",
        hidden_path: "? 隐藏路径",
        blocked_path: "!! 封锁",
        borders: "| 接壤",
      }

      html += `
        <tr>
          <td>${srcName}</td>
          <td style="color:var(--accent);font-family:var(--font-mono);font-size:12px;">${relMap[e.relation_type] || e.relation_type}</td>
          <td>${tgtName}</td>
          <td style="color:var(--text-muted)">${e.travel_time || e.distance_label || "-"}</td>
          <td>${e.difficulty || "-"}</td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html += '<div style="margin-top:12px;"><button class="btn btn-primary" id="btn-new-edge">新建关系</button></div>'
    return html
  },

  // ============================================================
  // 历史时期
  // ============================================================

  _renderEras() {
    if (!this._eras || this._eras.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128197;</div>
          <p>暂无历史时期</p>
          <p style="color:var(--text-dim);font-size:12px;">小说的宏观历史时期设定。</p>
          <div style="margin-top:8px;"><button class="btn btn-primary" id="btn-new-era">新建时期</button></div>
        </div>
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">小说的宏观历史时期，按时间顺序排列。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>顺序</th>
            <th>名称</th>
            <th>摘要</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const era of this._eras) {
      html += `
        <tr>
          <td style="font-family:var(--font-mono);color:var(--text-dim);">${String(era.order_index || 0).padStart(3, "0")}</td>
          <td><strong>${era.name}</strong></td>
          <td style="color:var(--text-muted)">${era.summary || "-"}</td>
          <td><button class="btn btn-sm" onclick="toast('编辑历史时期功能开发中', 'info')">编辑</button></td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html += '<div style="margin-top:12px;"><button class="btn btn-primary" id="btn-new-era">新建时期</button></div>'
    return html
  },

  // ============================================================
  // 地点历史（新功能）
  // ============================================================

  _renderHistory() {
    // 地点历史时期状态变化卡片
    const demoHistory = [
      {
        location: "旧王都",
        eras: [
          { era: "旧王朝时期", state: "首都，商路中心，王权核心", tag: "繁荣" },
          { era: "焚城前", state: "黑塔辐射扩散，居民开始撤离", tag: "衰退" },
          { era: "焚城后", state: "废墟，官方禁区，监察院封锁", tag: "禁区" },
          { era: "主线开始时", state: "被遗忘的禁地，黑雾墙仍存在，档案被篡改", tag: "隐秘" },
        ],
      },
      {
        location: "王都(新)",
        eras: [
          { era: "旧王朝时期", state: "边陲小镇，非政治中心", tag: "普通" },
          { era: "焚城后", state: "新首都，王室东迁，快速扩建", tag: "崛起" },
          { era: "主线开始时", state: "王国政治中心，监察院总部所在地", tag: "权力" },
        ],
      },
      {
        location: "地下封印区",
        eras: [
          { era: "旧王朝时期", state: "王室秘密封印设施", tag: "机密" },
          { era: "焚城后", state: "被彻底封印，入口被销毁", tag: "封锁" },
          { era: "主线开始时", state: "仍被封存，仅有极少数人知道其存在", tag: "遗忘" },
        ],
      },
    ]

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        地点的历史时期状态变化。展示不同历史时期下同一地点的不同面貌。
        <span style="color:var(--warning);">${!this._apiAvailable ? "（使用演示数据）" : ""}</span>
      </p>
    `

    for (const loc of demoHistory) {
      html += `
        <div class="card" style="margin-bottom:12px;">
          <div class="card-title">${loc.location}</div>
          <div style="margin-top:8px;">
      `

      for (const era of loc.eras) {
        const tagColors = {
          繁荣: "var(--accent)",
          衰退: "var(--warning)",
          禁区: "var(--danger)",
          隐秘: "var(--info)",
          普通: "var(--text-dim)",
          崛起: "var(--accent)",
          权力: "var(--accent)",
          机密: "var(--info)",
          封锁: "var(--danger)",
          遗忘: "var(--text-dim)",
        }
        const tagColor = tagColors[era.tag] || "var(--text-muted)"

        html += `
          <div style="
            border-left: 3px solid ${tagColor};
            padding: 8px 12px;
            margin-bottom: 6px;
            background: var(--panel);
            border-radius: 0 4px 4px 0;
          ">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong style="color:${tagColor};font-size:13px;">${era.era}</strong>
              <span class="badge" style="background:${tagColor};color:var(--bg);font-size:11px;">${era.tag}</span>
            </div>
            <p style="color:var(--text-muted);font-size:13px;margin:4px 0 0 0;">${era.state}</p>
          </div>
        `
      }

      html += '</div></div>'
    }

    html += `
      <div style="margin-top:12px;">
        <p style="color:var(--text-dim);font-size:12px;">
          <strong>宏观历史问题清单：</strong><br>
          &#8226; 各时期的政权更迭对地点的影响<br>
          &#8226; 哪些地点的地位在不同时期发生了变化<br>
          &#8226; 哪些地点被遗忘或重新发现<br>
          &#8226; 历史事件在地理上留下的痕迹
        </p>
      </div>
    `

    return html
  },

  // ============================================================
  // 简易地图
  // ============================================================

  _renderMap() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128506;</div>
        <p>简易地图</p>
        <p style="color:var(--text-dim);font-size:12px;">地点之间的通行关系示意（ASCII 风格）。</p>
        <div style="margin-top:16px;font-family:var(--font-mono);font-size:13px;line-height:1.8;text-align:center;color:var(--text);background:var(--panel);padding:24px;border-radius:4px;border:1px solid var(--border);">
          <div style="color:var(--text-dim);margin-bottom:12px;font-size:11px;">旧王都地区 · 简易通行图</div>
          <div style="letter-spacing:1px;">
            <span style="color:var(--info);">[北境]</span><br>
            <span style="color:var(--text-dim);">  |  </span><br>
            <span style="color:var(--text-dim);">  | 三日马车</span><br>
            <span style="color:var(--text-dim);">  |  </span><br>
            <span style="color:var(--accent);">[边境村]</span><span style="color:var(--text-dim);"> ---- </span><span style="color:var(--info);">[王都]</span><span style="color:var(--text-dim);"> ---- 半日/封锁 ---- </span><span style="color:var(--danger);">[旧王都]</span><br>
            <span style="color:var(--text-dim);">                                               \ 隐藏入口</span><br>
            <span style="color:var(--text-dim);">                                    <span style="color:var(--warning);">[地下封印区]</span></span>
          </div>
          <div style="color:var(--text-dim);margin-top:12px;font-size:11px;">
            <span style="color:var(--danger);">&#9632;</span> 封锁路线
            <span style="color:var(--warning);">&#9632;</span> 隐藏区域
            <span style="color:var(--accent);">&#9632;</span> 重要地点
          </div>
        </div>
      </div>
    `
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    document.getElementById("btn-new-location")?.addEventListener("click", () => {
      toast("新建地点功能开发中", "info")
    })
    document.getElementById("btn-new-edge")?.addEventListener("click", () => {
      toast("新建地理关系功能开发中", "info")
    })
    document.getElementById("btn-new-era")?.addEventListener("click", () => {
      toast("新建历史时期功能开发中", "info")
    })
  },

  onLeave() {
    this._selectedLocation = null
  },
}

router.registerView("geo", geoView)
window.geoView = geoView


export default geoView
