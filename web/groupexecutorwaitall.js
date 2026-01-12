import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

// GroupExecutorWaitAll 节点UI
app.registerExtension({
    name: "GroupExecutorWaitAll",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "GroupExecutorWaitAll") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }
                
                // 初始化properties
                if (!this.properties) {
                    this.properties = {};
                }
                if (!this.properties.groupCount) {
                    this.properties.groupCount = 1;
                }
                if (!this.properties.groupNames) {
                    this.properties.groupNames = [];
                }
                
                // 检查是否已经存在timeout_seconds控件，避免重复创建
                const existingTimeoutWidget = this.widgets.find(w => w.name === "timeout_seconds");
                if (!existingTimeoutWidget) {
                    // 使用ComfyWidgets创建timeout_seconds控件，确保正确绑定到节点输入
                    const timeoutWidget = ComfyWidgets["FLOAT"](this, "timeout_seconds", ["FLOAT", {
                        default: 300.0,
                        min: 0.0,
                        max: 3600.0,
                        step: 1.0
                    }], app);
                }
                
                // 添加组数量控件（如果还没有）
                const existingGroupCountWidget = this.widgets.find(w => w.name === "组数量");
                if (!existingGroupCountWidget) {
                    const groupCountWidget = this.addWidget(
                        "number",
                        "组数量",
                        this.properties.groupCount || 1,
                        (value) => {
                            this.properties.groupCount = Math.max(1, Math.min(50, parseInt(value) || 1));
                            this.updateGroupWidgets();
                        },
                        {
                            min: 1,
                            max: 50,
                            step: 1
                        }
                    );
                }
                
                // 更新组选择器
                this.updateGroupWidgets();
                
                // 监听组列表变化
                const self = this;
                const originalOnDrawBackground = app.canvas.onDrawBackground;
                app.canvas.onDrawBackground = function() {
                    if (originalOnDrawBackground) {
                        originalOnDrawBackground.apply(this, arguments);
                    }
                    self.updateGroupList();
                };
            };
            
            // 更新组选择器widgets
            nodeType.prototype.updateGroupWidgets = function() {
                // 保留组数量控件和timeout_seconds控件
                this.widgets = this.widgets.filter(w => 
                    w.name === "组数量" || 
                    w.name === "timeout_seconds"
                );
                
                const groupCount = this.properties.groupCount || 1;
                const currentGroups = this.properties.groupNames || [];
                
                // 确保groupNames数组长度正确
                while (currentGroups.length < groupCount) {
                    currentGroups.push("");
                }
                currentGroups.length = groupCount;
                this.properties.groupNames = currentGroups;
                
                // 获取组名列表
                const groupNames = this.getGroupNames();
                
                // 添加组选择器
                for (let i = 0; i < groupCount; i++) {
                    const widget = this.addWidget(
                        "combo",
                        `组 #${i + 1}`,
                        currentGroups[i] || "",
                        (value) => {
                            this.properties.groupNames[i] = value;
                        },
                        {
                            values: groupNames
                        }
                    );
                }
                
                this.size = this.computeSize();
            };
            
            // 更新组列表
            nodeType.prototype.updateGroupList = function() {
                const groupNames = this.getGroupNames();
                this.widgets.forEach(w => {
                    if (w.type === "combo" && w.name && w.name.startsWith("组 #")) {
                        w.options.values = groupNames;
                    }
                });
            };
            
            // 获取组名列表
            nodeType.prototype.getGroupNames = function() {
                return [...app.graph._groups].map(g => g.title).sort();
            };
            
            
            // 重写serialize以保存properties
            const originalSerialize = nodeType.prototype.serialize;
            nodeType.prototype.serialize = function() {
                const data = originalSerialize ? originalSerialize.apply(this, arguments) : {};
                if (!data.properties) {
                    data.properties = {};
                }
                data.properties.groupCount = this.properties.groupCount || 1;
                data.properties.groupNames = this.properties.groupNames || [];
                data.properties.timeout_seconds = this.properties.timeout_seconds || 300;
                return data;
            };
            
            // 重写configure以恢复properties
            const originalConfigure = nodeType.prototype.configure;
            nodeType.prototype.configure = function(info) {
                if (originalConfigure) {
                    originalConfigure.apply(this, arguments);
                }
                if (info.properties) {
                    this.properties.groupCount = info.properties.groupCount || 1;
                    this.properties.groupNames = info.properties.groupNames || [];
                    this.properties.timeout_seconds = info.properties.timeout_seconds || 300;
                    if (!this.configuring) {
                        this.updateGroupWidgets();
                    }
                }
            };
            
            // 计算节点大小
            const originalComputeSize = nodeType.prototype.computeSize;
            nodeType.prototype.computeSize = function(out) {
                const groupCount = this.properties.groupCount || 1;
                const widgetHeight = 30;
                const padding = 20;
                const width = 250;
                const height = (groupCount + 3) * widgetHeight + padding;
                return [width, height];
            };
        }
    }
});
