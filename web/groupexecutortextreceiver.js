import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "Comfy.LG_TextReceiver",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "LG_TextReceiver") {
            // 监听节点创建事件
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                
                // 找到文本 widget
                const textWidget = this.widgets?.find(w => w.name === "text");
                if (textWidget && textWidget.options?.multiline) {
                    // 标记这个 widget 支持实时编辑
                    textWidget._isTextReceiver = true;
                    
                    // 为文本输入框添加事件监听，允许人工编辑
                    setTimeout(() => {
                        const textarea = this.el?.querySelector(`textarea[name="${textWidget.name}"]`);
                        if (textarea) {
                            // 监听用户输入，允许人工编辑
                            textarea.addEventListener("input", (e) => {
                                // 用户编辑时，更新 widget 值
                                textWidget.value = e.target.value;
                                if (textWidget.callback) {
                                    textWidget.callback(e.target.value);
                                }
                                // 标记节点需要重绘
                                this.setDirtyCanvas(true, true);
                            });
                            
                            // 监听 change 事件（当用户完成编辑时）
                            textarea.addEventListener("change", (e) => {
                                textWidget.value = e.target.value;
                                if (textWidget.callback) {
                                    textWidget.callback(e.target.value);
                                }
                                this.setDirtyCanvas(true, true);
                            });
                        }
                    }, 100);
                }
            };
            
            // 监听执行完成事件
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                
                // 确保文本内容已更新到 UI
                const textWidget = this.widgets?.find(w => w.name === "text");
                if (textWidget) {
                    setTimeout(() => {
                        const textarea = this.el?.querySelector(`textarea[name="${textWidget.name}"]`);
                        if (textarea && textarea.value !== textWidget.value) {
                            textarea.value = textWidget.value || "";
                            textarea.dispatchEvent(new Event('input', { bubbles: true }));
                            this.setDirtyCanvas(true, true);
                        }
                    }, 50);
                }
            };
        }
    },
});

// 增强 text-send 事件处理，确保实时更新
api.addEventListener("text-send", async ({ detail }) => {
    if (!detail.text) return;

    for (const node of app.graph._nodes) {
        if (node.type === "LG_TextReceiver") {
            const linkWidget = node.widgets?.find(w => w.name === "link_id");
            if (!linkWidget || linkWidget.value !== detail.link_id) {
                continue;
            }

            const textWidget = node.widgets?.find(w => w.name === "text");
            if (textWidget) {
                // 检查用户是否正在编辑
                const textarea = node.el?.querySelector(`textarea[name="${textWidget.name}"]`);
                const isFocused = document.activeElement === textarea;
                
                // 更新 widget 值
                const oldValue = textWidget.value || "";
                textWidget.value = detail.text;
                
                // 如果用户没有正在编辑，立即更新 UI
                if (!isFocused) {
                    // 更新 textarea 内容（如果存在且值不同）
                    if (textarea && textarea.value !== detail.text) {
                        textarea.value = detail.text;
                        // 触发 input 事件，确保其他监听器也能响应
                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    // 触发回调
                    if (textWidget.callback) {
                        textWidget.callback(detail.text);
                    }
                } else {
                    // 用户正在编辑时，仍然更新 widget 值，但不强制更新 UI
                    // 这样用户在失去焦点后能看到最新值
                    if (textWidget.callback) {
                        textWidget.callback(detail.text);
                    }
                    // 可选：在用户编辑时不更新 UI，避免打断用户输入
                    // 但我们仍然更新 widget 值，以便后续使用
                }
                
                // 标记节点需要重绘
                node.setDirtyCanvas(true, true);
            }
        }
    }
});
