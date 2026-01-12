import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "Comfy.LG_ImageReceiverPlus",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "LG_ImageReceiverPlus") {
            // 监听节点创建事件
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                
                // 标记节点支持实时更新
                this._isImageReceiverPlus = true;
                
                // 为 mask_file widget 添加变化监听，以便在编辑遮罩后自动更新
                setTimeout(() => {
                    const maskWidget = this.widgets?.find(w => w.name === "mask_file");
                    if (maskWidget) {
                        // 监听 mask_file 的变化
                        const input = this.el?.querySelector(`input[name="${maskWidget.name}"]`);
                        if (input) {
                            input.addEventListener("change", (e) => {
                                // 更新 widget 值
                                maskWidget.value = e.target.value || "";
                                
                                // 当 mask_file 更新时，标记节点需要重新执行
                                this.setDirtyCanvas(true, true);
                                if (this.setDirty && typeof this.setDirty === 'function') {
                                    this.setDirty(true);
                                }
                                
                                // 触发回调以确保值已更新
                                if (maskWidget.callback) {
                                    maskWidget.callback(maskWidget.value);
                                }
                                
                                // 标记节点已更改，以便重新执行
                                if (this.graph) {
                                    if (this.graph.setDirty && typeof this.graph.setDirty === 'function') {
                                        this.graph.setDirty(true);
                                    }
                                }
                                
                                console.log('[LG_ImageReceiverPlus] mask_file 已更新，节点已标记为需要重新执行:', maskWidget.value);
                            });
                            
                            input.addEventListener("input", (e) => {
                                // 实时更新 widget 值
                                maskWidget.value = e.target.value || "";
                                if (maskWidget.callback) {
                                    maskWidget.callback(maskWidget.value);
                                }
                            });
                        }
                    }
                }, 100);
            };
            
            // 监听执行完成事件
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                
                // 在执行完成后，确保 mask_file 已正确加载
                const maskWidget = this.widgets?.find(w => w.name === "mask_file");
                if (maskWidget && maskWidget.value) {
                    // 如果 mask_file 有值，确保它会被使用
                    console.log('[LG_ImageReceiverPlus] 执行完成，mask_file:', maskWidget.value);
                }
            };
            
            // 添加右键菜单支持 mask editor
            // ComfyUI 会自动为有 MASK 输出的节点添加 mask editor 选项
            // 我们需要确保节点输出类型正确，并添加 getExtraMenuOptions 方法
            const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
            nodeType.prototype.getExtraMenuOptions = function (_, options) {
                const result = getExtraMenuOptions ? getExtraMenuOptions.apply(this, arguments) : [];
                
                // 检查是否有图像和遮罩输出
                const imageWidget = this.widgets?.find(w => w.name === "image");
                const hasImage = imageWidget && imageWidget.value;
                const hasMaskOutput = this.outputs && this.outputs.some(out => 
                    out && (out.name === "masks" || out.type === "MASK")
                );
                
                if (hasImage && hasMaskOutput) {
                    // 添加分隔线和 mask editor 选项
                    result.push(null);
                    result.push({
                        content: "Open in MaskEditor",
                        callback: () => {
                            if (!imageWidget || !imageWidget.value) {
                                if (app.ui && app.ui.dialog) {
                                    app.ui.dialog.show("请先加载图像");
                                }
                                return;
                            }
                            
                            const filename = imageWidget.value;
                            
                            // 获取文件类型（如果已保存，使用保存的值，否则默认为 temp）
                            let fileType = "temp"; // 默认从 temp 目录
                            if (this._comfy_file_type && this._comfy_file_type[filename]) {
                                fileType = this._comfy_file_type[filename];
                            } else if (this.images && Array.isArray(this.images)) {
                                const imgData = this.images.find(img => img && img.filename === filename);
                                if (imgData && imgData.type) {
                                    fileType = imgData.type;
                                }
                            }
                            
                            // 确保节点有 images 属性，并且包含正确的类型信息
                            if (!this.images || !Array.isArray(this.images) || this.images.length === 0) {
                                this.images = [{
                                    filename: filename,
                                    type: fileType,
                                    subfolder: ""
                                }];
                            } else {
                                // 更新 images 数组中的类型信息
                                this.images = this.images.map(img => {
                                    if (img && img.filename === filename) {
                                        return {
                                            ...img,
                                            type: fileType
                                        };
                                    }
                                    return img;
                                });
                            }
                            
                                            // 保存节点引用，用于 mask editor 保存时更新
                            const currentNode = this;
                            const currentImageFilename = filename;
                            
                            // 使用 ComfyUI 的标准方式打开 mask editor
                            try {
                                // 方法1: 直接调用 maskEditor.open（如果存在）
                                if (app.ui && app.ui.maskEditor && typeof app.ui.maskEditor.open === 'function') {
                                    // 监听 mask editor 保存事件（通过多种方式）
                                    
                                    // 方法1: 监听 saveMask 事件
                                    const handleMaskSave = (event) => {
                                        if (event.detail && event.detail.node === currentNode) {
                                            const savedMaskFile = event.detail.filename || event.detail.maskFilename;
                                            if (savedMaskFile) {
                                                updateNodeAfterMaskSave(currentNode, savedMaskFile);
                                            }
                                        }
                                    };
                                    
                                    // 监听多种可能的事件
                                    document.addEventListener('mask-saved', handleMaskSave, { once: true });
                                    document.addEventListener('mask-save', handleMaskSave, { once: true });
                                    
                                    // 方法2: 包装 maskEditor 的保存方法（如果存在）
                                    if (app.ui.maskEditor.saveMask && typeof app.ui.maskEditor.saveMask === 'function') {
                                        const originalSaveMask = app.ui.maskEditor.saveMask;
                                        app.ui.maskEditor.saveMask = function(...args) {
                                            const result = originalSaveMask.apply(this, args);
                                            // 尝试从参数中获取保存的文件名
                                            setTimeout(() => {
                                                const savedMaskFile = args[0] || args[1];
                                                if (savedMaskFile) {
                                                    updateNodeAfterMaskSave(currentNode, savedMaskFile);
                                                } else {
                                                    // 如果没有文件名，尝试从 mask editor 的状态中获取
                                                    updateNodeAfterMaskSave(currentNode, null);
                                                }
                                            }, 200);
                                            return result;
                                        };
                                    }
                                    
                                    // 方法3: 监听对话框关闭事件，检查是否有新文件保存
                                    const checkMaskFileOnClose = () => {
                                        setTimeout(() => {
                                            // 尝试查找最近保存的遮罩文件
                                            const maskWidget = currentNode.widgets?.find(w => w.name === "mask_file");
                                            if (!maskWidget || !maskWidget.value) {
                                                // 如果 mask_file 为空，尝试自动查找
                                                updateNodeAfterMaskSave(currentNode, null);
                                            }
                                        }, 500);
                                    };
                                    
                                    // 保存打开时的节点状态
                                    const originalMaskFile = currentNode.widgets?.find(w => w.name === "mask_file")?.value || "";
                                    
                                    // 打开 mask editor
                                    const maskEditorInstance = app.ui.maskEditor.open(this);
                                    
                                    // 如果 mask editor 有返回实例，尝试监听其保存事件
                                    if (maskEditorInstance && typeof maskEditorInstance.on === 'function') {
                                        maskEditorInstance.on('save', (data) => {
                                            if (data && data.filename) {
                                                updateNodeAfterMaskSave(currentNode, data.filename);
                                            }
                                        });
                                    }
                                    
                                    // 设置定时检查（在 mask editor 关闭时）
                                    const checkInterval = setInterval(() => {
                                        const maskEditorDialog = document.querySelector('.mask-editor-dialog, [class*="maskEditor"], [class*="mask-editor"]');
                                        if (!maskEditorDialog || !document.contains(maskEditorDialog)) {
                                            clearInterval(checkInterval);
                                            // mask editor 已关闭，检查是否有新的遮罩文件
                                            setTimeout(() => {
                                                const currentMaskFile = currentNode.widgets?.find(w => w.name === "mask_file")?.value || "";
                                                // 如果 mask_file 有变化，说明已经更新
                                                if (currentMaskFile && currentMaskFile !== originalMaskFile) {
                                                    console.log('[LG_ImageReceiverPlus] 检测到 mask_file 已更新:', currentMaskFile);
                                                    // 触发节点重新执行
                                                    currentNode.setDirtyCanvas(true, true);
                                                    if (currentNode.setDirty && typeof currentNode.setDirty === 'function') {
                                                        currentNode.setDirty(true);
                                                    }
                                                } else {
                                                    // 如果 mask_file 没有变化，尝试检查是否有新文件保存
                                                    checkMaskFileOnClose();
                                                }
                                            }, 300);
                                        }
                                    }, 500);
                                    
                                    // 最多检查 5 分钟
                                    setTimeout(() => {
                                        clearInterval(checkInterval);
                                    }, 300000);
                                    
                                    return;
                                }
                                
                                // 方法2: 通过双击节点（ComfyUI 的标准行为）
                                if (this.onDblClick && typeof this.onDblClick === 'function') {
                                    this.onDblClick();
                                    return;
                                }
                                
                                // 方法3: 通过 canvas 的 openMaskEditor 方法
                                if (app.canvas && app.canvas.openMaskEditor && typeof app.canvas.openMaskEditor === 'function') {
                                    app.canvas.openMaskEditor(this);
                                    return;
                                }
                                
                            } catch (e) {
                                console.error('[LG_ImageReceiverPlus] 打开 Mask Editor 失败:', e);
                                if (app.ui && app.ui.dialog) {
                                    app.ui.dialog.show("无法打开 Mask Editor: " + e.message);
                                }
                            }
                        }
                    });
                }
                
                return result;
            };
        }
    },
});

// 辅助函数：在 mask editor 保存后更新节点
function updateNodeAfterMaskSave(node, savedMaskFile = null) {
    if (!node || node.type !== "LG_ImageReceiverPlus") {
        return;
    }
    
    const imageWidget = node.widgets?.find(w => w.name === "image");
    if (!imageWidget || !imageWidget.value) {
        return;
    }
    
    const imageFilename = imageWidget.value;
    
    // 如果没有提供保存的文件名，尝试查找最近保存的遮罩文件
    if (!savedMaskFile) {
        // mask editor 通常会保存遮罩文件，文件名通常是 "painted-masked-{timestamp}.png"
        // 或者基于原图像文件名生成
        const baseName = imageFilename.replace(/\.[^.]+$/, ""); // 去掉扩展名
        
        // 尝试从节点属性中获取
        if (node._maskEditorSaveResult) {
            savedMaskFile = node._maskEditorSaveResult;
        } else {
            // 如果无法获取，尝试构建可能的文件名
            // 注意：这个可能需要用户手动输入文件名
            console.log('[LG_ImageReceiverPlus] 无法自动获取保存的遮罩文件名，请手动输入遮罩文件名');
            return;
        }
    }
    
    const maskWidget = node.widgets?.find(w => w.name === "mask_file");
    if (maskWidget && savedMaskFile) {
        // 更新 mask_file widget
        maskWidget.value = savedMaskFile;
        
        // 更新输入框
        const input = node.el?.querySelector(`input[name="${maskWidget.name}"]`);
        if (input) {
            input.value = savedMaskFile;
            // 先触发 input 事件
            input.dispatchEvent(new Event('input', { bubbles: true }));
            // 然后触发 change 事件（这会触发上面添加的监听器）
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        
        // 触发回调
        if (maskWidget.callback) {
            maskWidget.callback(savedMaskFile);
        }
        
        // 标记节点需要重新执行
        node.setDirtyCanvas(true, true);
        if (node.setDirty && typeof node.setDirty === 'function') {
            node.setDirty(true);
        }
        
        // 确保节点被标记为已更改，以便重新执行
        if (node.graph) {
            if (node.graph.setDirty && typeof node.graph.setDirty === 'function') {
                node.graph.setDirty(true);
            }
        }
        
        console.log('[LG_ImageReceiverPlus] 已更新遮罩文件:', savedMaskFile);
    }
}

// 监听 mask editor 保存事件（如果 ComfyUI 有提供）
api.addEventListener("mask-save", async ({ detail }) => {
    if (!detail || !detail.node) {
        return;
    }
    
    const node = detail.node;
    if (node && node.type === "LG_ImageReceiverPlus") {
        // 保存遮罩文件名
        const savedMaskFile = detail.filename || detail.maskFilename;
        if (savedMaskFile) {
            node._maskEditorSaveResult = savedMaskFile;
            // 更新节点
            updateNodeAfterMaskSave(node, savedMaskFile);
        }
    }
});

// 监听节点执行事件，确保 mask_file 更新后节点会重新执行
api.addEventListener("executed", async ({ detail }) => {
    if (!detail || !detail.node) {
        return;
    }
    
    // 检查是否是 LG_ImageReceiverPlus 节点
    for (const node of app.graph._nodes) {
        if (node.type === "LG_ImageReceiverPlus" && node.id === detail.node) {
            // 节点已执行，确保 mask_file 已正确加载
            const maskWidget = node.widgets?.find(w => w.name === "mask_file");
            if (maskWidget && maskWidget.value) {
                console.log('[LG_ImageReceiverPlus] 节点执行完成，mask_file:', maskWidget.value);
            }
        }
    }
});

// 增强 img-send 事件处理，确保实时更新 LG_ImageReceiverPlus
api.addEventListener("img-send", async ({ detail }) => {
    if (detail.images.length === 0) return;

    // 使用第一个文件名（上传按钮通常只支持单个文件）
    const firstFilename = detail.images[0]?.filename;
    if (!firstFilename) return;

    for (const node of app.graph._nodes) {
        if (node.type === "LG_ImageReceiverPlus") {
            const linkWidget = node.widgets?.find(w => w.name === "link_id");
            if (!linkWidget || linkWidget.value !== detail.link_id) {
                continue;
            }

            const imageWidget = node.widgets?.find(w => w.name === "image");
            if (imageWidget) {
                // 更新上传按钮显示的文件名
                imageWidget.value = firstFilename;
                
                // 保存文件类型信息（用于 mask editor）
                if (!node._comfy_file_type) {
                    node._comfy_file_type = {};
                }
                // 从 detail.images 中获取文件类型，默认为 temp
                const fileType = detail.images[0]?.type || "temp";
                node._comfy_file_type[firstFilename] = fileType;
                
                // 设置节点的 images 属性，包含类型信息（mask editor 可能需要）
                if (!node.images) {
                    node.images = [];
                }
                node.images = detail.images.map(img => ({
                    filename: img.filename,
                    type: img.type || "temp",
                    subfolder: img.subfolder || ""
                }));
                
                // 找到文件输入框并更新值
                const input = node.el?.querySelector(`input[name="${imageWidget.name}"]`);
                if (input) {
                    input.value = firstFilename;
                    // 触发 change 事件
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
                
                // 触发回调
                if (imageWidget.callback) {
                    imageWidget.callback(firstFilename);
                }
                
                // 标记节点需要重绘
                node.setDirtyCanvas(true, true);
            }

            // 实时预览图像
            Promise.all(detail.images.map(imageData => {
                return new Promise((resolve) => {
                    const img = new Image();
                    img.onload = () => resolve(img);
                    img.src = `/view?filename=${encodeURIComponent(imageData.filename)}&type=${imageData.type}${app.getPreviewFormatParam()}`;
                });
            })).then(loadedImages => {
                node.imgs = loadedImages;
                app.canvas.setDirty(true);
            });
        }
    }
});
