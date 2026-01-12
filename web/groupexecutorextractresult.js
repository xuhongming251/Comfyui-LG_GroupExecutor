import { app } from "../../scripts/app.js";

// GroupExecutorExtractResult 节点UI
app.registerExtension({
    name: "GroupExecutorExtractResult",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "GroupExecutorExtractResult") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }
                
                // 初始化properties
                if (!this.properties) {
                    this.properties = {};
                }
                if (!this.properties.groupName) {
                    this.properties.groupName = "";
                }
                
                // 更新组选择器
                this.updateGroupWidget();
                
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
            
            // 更新组选择器widget
            nodeType.prototype.updateGroupWidget = function() {
                // 移除旧的组选择器
                this.widgets = this.widgets.filter(w => w.name !== "选择组");
                
                // 获取组名列表
                const groupNames = this.getGroupNames();
                const currentGroupName = this.properties.groupName || "";
                
                // 添加组选择器
                const widget = this.addWidget(
                    "combo",
                    "选择组",
                    currentGroupName,
                    (value) => {
                        this.properties.groupName = value;
                    },
                    {
                        values: groupNames
                    }
                );
                
                this.size = this.computeSize();
            };
            
            // 更新组列表
            nodeType.prototype.updateGroupList = function() {
                const groupNames = this.getGroupNames();
                const widget = this.widgets.find(w => w.name === "选择组");
                if (widget) {
                    widget.options.values = groupNames;
                }
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
                data.properties.groupName = this.properties.groupName || "";
                return data;
            };
            
            // 重写configure以恢复properties
            const originalConfigure = nodeType.prototype.configure;
            nodeType.prototype.configure = function(info) {
                if (originalConfigure) {
                    originalConfigure.apply(this, arguments);
                }
                if (info.properties) {
                    this.properties.groupName = info.properties.groupName || "";
                    if (!this.configuring) {
                        this.updateGroupWidget();
                    }
                }
            };
            
            // 计算节点大小
            const originalComputeSize = nodeType.prototype.computeSize;
            nodeType.prototype.computeSize = function(out) {
                const widgetHeight = 30;
                const padding = 20;
                const width = 250;
                const height = 2 * widgetHeight + padding;
                return [width, height];
            };
        }
    }
});
