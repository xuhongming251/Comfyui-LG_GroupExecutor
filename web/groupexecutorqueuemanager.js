import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "GroupExecutorQueueManager",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (api.fetchApi._isGroupExecutorQueueManager) {
            return;
        }

        const originalFetchApi = api.fetchApi;

        function collectRelatedNodes(prompt, nodeId, relevantNodes) {
            if (!prompt[nodeId] || relevantNodes.has(nodeId)) return;
            relevantNodes.add(nodeId);

            const node = prompt[nodeId];
            if (node.inputs) {
                Object.values(node.inputs).forEach(input => {
                    if (input && input.length > 0) {
                        collectRelatedNodes(prompt, input[0], relevantNodes);
                    }
                });
            }
        }

        const newFetchApi = async function(url, options = {}) {

            if (url === '/prompt' && options.method === 'POST') {
                const requestData = JSON.parse(options.body);

                if (requestData.extra_data?.isGroupExecutorRequest) {
                    return originalFetchApi.call(api, url, options);
                }

                const prompt = requestData.prompt;

                const hasGroupExecutor = Object.values(prompt).some(node => 
                    node.class_type === "GroupExecutorSender"
                );

                if (hasGroupExecutor) {

                    const relevantNodes = new Set();
                    
                    for (const [nodeId, node] of Object.entries(prompt)) {
                        if (node.class_type === "GroupExecutorSender") {
                            collectRelatedNodes(prompt, nodeId, relevantNodes);
                        }
                    }

                    const filteredPrompt = {};
                    for (const nodeId of relevantNodes) {
                        if (prompt[nodeId]) {
                            filteredPrompt[nodeId] = prompt[nodeId];
                        }
                    }

                    const modifiedOptions = {
                        ...options,
                        body: JSON.stringify({
                            ...requestData,
                            prompt: filteredPrompt,
                            extra_data: {
                                ...requestData.extra_data,
                                isGroupExecutorRequest: true
                            }
                        })
                    };

                    return originalFetchApi.call(api, url, modifiedOptions);
                }
            }

            return originalFetchApi.call(api, url, options);
        };

        newFetchApi._isGroupExecutorQueueManager = true;

        api.fetchApi = newFetchApi;
    }
}); 



api.addEventListener("img-send", async ({ detail }) => {
    if (detail.images.length === 0) return;

    const filenames = detail.images.map(data => data.filename).join(', ');

    for (const node of app.graph._nodes) {
        if (node.type === "LG_ImageReceiver" || node.type === "LG_ImageReceiverPlus") {
            let isLinked = false;

            const linkWidget = node.widgets.find(w => w.name === "link_id");
            if (linkWidget && linkWidget.value === detail.link_id) {
                isLinked = true;
            }

            if (isLinked) {
                // 找到图像文件名 widget
                const imageWidget = node.widgets.find(w => w.name === "image");
                if (imageWidget) {
                    // 对于 LG_ImageReceiverPlus，使用第一个文件名（上传按钮通常只支持单个文件）
                    const filenameToSet = node.type === "LG_ImageReceiverPlus" 
                        ? detail.images[0]?.filename || filenames.split(',')[0]
                        : filenames;
                    
                    // 对于 LG_ImageReceiverPlus，保存文件类型信息（用于 mask editor）
                    if (node.type === "LG_ImageReceiverPlus") {
                        // 保存文件类型信息
                        if (!node._comfy_file_type) {
                            node._comfy_file_type = {};
                        }
                        const fileType = detail.images[0]?.type || "temp";
                        node._comfy_file_type[filenameToSet] = fileType;
                        
                        // 设置节点的 images 属性，包含类型信息（mask editor 可能需要）
                        node.images = detail.images.map(img => ({
                            filename: img.filename,
                            type: img.type || "temp",
                            subfolder: img.subfolder || ""
                        }));
                    }
                    
                    // 更新 widget 值
                    imageWidget.value = filenameToSet;
                    
                    // 如果是上传按钮（文件输入框），也更新输入框的值
                    const input = node.el?.querySelector(`input[name="${imageWidget.name}"]`);
                    if (input) {
                        input.value = filenameToSet;
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    
                    if (imageWidget.callback) {
                        imageWidget.callback(filenameToSet);
                    }
                }

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
    }
});

app.registerExtension({
    name: "Comfy.LG_Image",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "LG_ImageReceiver" || nodeData.name === "LG_ImageReceiverPlus") {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
            };
        }
    },
});

