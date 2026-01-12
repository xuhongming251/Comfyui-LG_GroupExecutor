import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { queueManager } from "./queue_utils.js";
class GroupExecutorUI {
    static DOCK_MARGIN_X = 0;
    static DOCK_MARGIN_Y = 60;
    constructor() {
        this.container = null;
        this.isExecuting = false;
        this.isCancelling = false;
        this.groups = [];
        this.position = { x: 0, y: 0 };
        this.isDragging = false;
        this.dragOffset = { x: 0, y: 0 };
        this.DOCK_MARGIN_X = GroupExecutorUI.DOCK_MARGIN_X;
        this.DOCK_MARGIN_Y = GroupExecutorUI.DOCK_MARGIN_Y;
        this.createUI();
        this.attachEvents();
        this.container.instance = this;
    }
    createUI() {
        this.container = document.createElement('div');
        this.container.className = 'group-executor-ui';
        this.container.style.top = `${this.DOCK_MARGIN_Y}px`;
        this.container.style.right = `${this.DOCK_MARGIN_X}px`;
        this.container.innerHTML = `
            <div class="ge-header">
                <span class="ge-title">组执行管理器</span>
                <div class="ge-controls">
                    <button class="ge-server-manager-btn" title="服务器管理">⚙️</button>
                    <button class="ge-dock-btn" title="停靠位置">📌</button>
                    <button class="ge-minimize-btn" title="最小化">-</button>
                    <button class="ge-close-btn" title="关闭">×</button>
                </div>
            </div>
            <div class="ge-content">
                <div class="ge-mode-switch">
                    <button class="ge-mode-btn active" data-mode="multi">多组执行</button>
                    <button class="ge-mode-btn" data-mode="single">单组执行</button>
                </div>
                <div class="ge-multi-mode">
                    <div class="ge-row ge-config-row">
                        <select class="ge-config-select">
                            <option value="">选择配置</option>
                        </select>
                        <button class="ge-save-config" title="保存配置">💾</button>
                        <button class="ge-delete-config" title="删除配置">🗑️</button>
                    </div>
                    <div class="ge-row">
                        <label>组数量:</label>
                        <input type="number" class="ge-group-count" min="1" max="50" value="1">
                    </div>
                    <div class="ge-groups-container"></div>
                    <div class="ge-row">
                        <label>重复次数:</label>
                        <input type="number" class="ge-repeat-count" min="1" max="100" value="1">
                    </div>
                    <div class="ge-row">
                        <label>延迟(秒):</label>
                        <input type="number" class="ge-delay" min="0" max="300" step="0.1" value="0">
                    </div>
                    <div class="ge-status"></div>
                    <div class="ge-buttons">
                        <button class="ge-execute-btn">执行</button>
                        <button class="ge-cancel-btn" disabled>取消</button>
                    </div>
                </div>
                <div class="ge-single-mode" style="display: none;">
                    <div class="ge-search-container">
                        <input type="text" class="ge-search-input" placeholder="搜索组名称...">
                        <button class="ge-search-clear" title="清除搜索">×</button>
                    </div>
                    <div class="ge-groups-list"></div>
                </div>
            </div>
        `;
        const style = document.createElement('style');
        style.textContent = `
            .group-executor-ui {
                position: fixed;
                top: 20px;
                right: 20px;
                width: 300px !important;
                min-width: 300px;
                max-width: 300px;
                background: #2a2a2a;
                border: 1px solid #444;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                z-index: 1000;
                font-family: Arial, sans-serif;
                color: #fff;
                user-select: none;
            }
            .ge-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 12px;
                background: #333;
                border-radius: 8px 8px 0 0;
                cursor: move;
                width: 100%;
                box-sizing: border-box;
            }
            .ge-controls button {
                background: none;
                border: none;
                color: #fff;
                margin-left: 8px;
                cursor: pointer;
                font-size: 16px;
            }
            .ge-content {
                padding: 12px;
                display: flex;
                flex-direction: column;
                max-height: calc(100vh - 100px);
            }
            .ge-row {
                display: flex;
                align-items: center;
                margin-bottom: 12px;
            }
            .ge-row label {
                flex: 1;
                margin-right: 12px;
            }
            .ge-row input {
                width: 100px;
                padding: 4px 8px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
            }
            .ge-groups-container,
            .ge-groups-list {
                max-height: calc(50vh - 180px);
                overflow-y: auto;
                margin-bottom: 12px;
                padding-right: 8px;
            }
            .ge-groups-container::-webkit-scrollbar,
            .ge-groups-list::-webkit-scrollbar {
                width: 6px;
            }
            .ge-groups-container::-webkit-scrollbar-track,
            .ge-groups-list::-webkit-scrollbar-track {
                background: #2a2a2a;
                border-radius: 3px;
            }
            .ge-groups-container::-webkit-scrollbar-thumb,
            .ge-groups-list::-webkit-scrollbar-thumb {
                background: #555;
                border-radius: 3px;
            }
            .ge-groups-container::-webkit-scrollbar-thumb:hover,
            .ge-groups-list::-webkit-scrollbar-thumb:hover {
                background: #666;
            }
            .ge-group-item-container {
                display: flex;
                gap: 8px;
                align-items: center;
                margin-bottom: 8px;
            }
            .ge-group-select {
                flex: 1;
                padding: 4px 8px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
            }
            .ge-group-select:last-child {
                margin-bottom: 0;
            }
            .ge-group-item {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 10px;
                margin-bottom: 8px;
                background: #333;
                border-radius: 4px;
            }
            .ge-group-item:last-child {
                margin-bottom: 0;
            }
            .ge-group-name {
                flex: 1;
                margin-right: 8px;
            }
            .ge-group-controls {
                display: flex;
                gap: 10px;
                margin-left: auto;
            }
            .ge-buttons {
                display: flex;
                gap: 8px;
            }
            .ge-buttons button {
                flex: 1;
                padding: 8px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
            }
            .ge-execute-btn {
                background: #4CAF50;
                color: white;
            }
            .ge-execute-btn:disabled {
                background: #2a5a2d;
                cursor: not-allowed;
            }
            .ge-cancel-btn {
                background: #f44336;
                color: white;
            }
            .ge-cancel-btn:disabled {
                background: #7a2520;
                cursor: not-allowed;
            }
            .ge-status {
                margin: 12px 0;
                padding: 8px;
                background: #333;
                border-radius: 4px;
                min-height: 20px;
                text-align: center;
                position: relative;
                overflow: hidden;
            }
            .ge-status::before {
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                height: 100%;
                width: var(--progress, 0%);
                background: rgba(36, 145, 235, 0.8);
                transition: width 0.3s ease;
                z-index: 0;
            }
            .ge-status span {
                position: relative;
                z-index: 1;
            }
            .ge-minimized {
                width: auto !important;
                min-width: auto;
            }
            .ge-minimized .ge-content {
                display: none;
            }
            .ge-dock-menu {
                position: absolute;
                background: #333;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px 0;
                z-index: 1001;
                visibility: hidden;
                opacity: 0;
                transition: opacity 0.2s;
            }
            .ge-dock-menu.visible {
                visibility: visible;
                opacity: 1;
            }
            .ge-dock-menu button {
                display: block;
                width: 100%;
                padding: 4px 12px;
                background: none;
                border: none;
                color: #fff;
                text-align: left;
                cursor: pointer;
            }
            .ge-dock-menu button:hover {
                background: #444;
            }
            .ge-title {
                flex: 1;
                pointer-events: none;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .ge-config-row {
                display: flex;
                gap: 8px;
                margin-bottom: 12px;
            }
            .ge-config-select {
                flex: 1;
                padding: 4px 8px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
            }
            .ge-save-config,
            .ge-delete-config {
                background: #333;
                border: 1px solid #444;
                color: #fff;
                padding: 4px 8px;
                border-radius: 4px;
                cursor: pointer;
            }
            .ge-save-config:hover,
            .ge-delete-config:hover {
                background: #444;
            }
            .ge-delete-config:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .ge-mode-switch {
                display: flex;
                margin-bottom: 12px;
                gap: 8px;
            }
            .ge-mode-btn {
                flex: 1;
                padding: 8px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
                cursor: pointer;
            }
            .ge-mode-btn.active {
                background: #4CAF50;
                border-color: #4CAF50;
            }
            .ge-execute-single-btn,
            .ge-cancel-single-btn {
                padding: 6px 12px;
                font-size: 14px;
                min-width: 60px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
            }
            .ge-execute-single-btn {
                background: #4CAF50;
                color: white;
            }
            .ge-cancel-single-btn {
                background: #f44336;
                color: white;
                display: none;
            }
            .ge-execute-single-btn:disabled,
            .ge-cancel-single-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .ge-execute-single-btn:hover:not(:disabled) {
                background: #45a049;
            }
            .ge-cancel-single-btn:hover:not(:disabled) {
                background: #d32f2f;
            }
            .ge-search-container {
                display: flex;
                align-items: center;
                margin-bottom: 12px;
                gap: 8px;
            }
            .ge-search-input {
                flex: 1;
                padding: 8px 12px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
                font-size: 14px;
            }
            .ge-search-input:focus {
                outline: none;
                border-color: #666;
            }
            .ge-search-clear {
                background: #444;
                border: none;
                color: #fff;
                padding: 6px 10px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                display: none;
            }
            .ge-search-clear:hover {
                background: #555;
            }
            /* 服务器管理相关样式 */
            .ge-server-modal {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10001;
                display: none;
                justify-content: center;
                align-items: center;
            }
            .ge-server-modal.visible {
                display: flex;
            }
            .ge-server-dialog {
                background: #2a2a2a;
                border: 1px solid #444;
                border-radius: 8px;
                width: 600px;
                max-width: 90vw;
                max-height: 80vh;
                overflow: hidden;
                box-shadow: 0 4px 20px rgba(0,0,0,0.5);
                display: flex;
                flex-direction: column;
            }
            .ge-server-dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 16px;
                background: #333;
                border-bottom: 1px solid #444;
            }
            .ge-server-dialog-title {
                font-weight: bold;
                font-size: 16px;
            }
            .ge-server-dialog-close {
                background: none;
                border: none;
                color: #fff;
                font-size: 20px;
                cursor: pointer;
                padding: 0;
                width: 24px;
                height: 24px;
                line-height: 24px;
            }
            .ge-server-dialog-close:hover {
                background: #444;
                border-radius: 4px;
            }
            .ge-server-dialog-content {
                padding: 16px;
                overflow-y: auto;
                flex: 1;
            }
            .ge-server-dialog-footer {
                padding: 12px 16px;
                background: #333;
                border-top: 1px solid #444;
                display: flex;
                justify-content: flex-end;
                gap: 8px;
            }
            .ge-server-list {
                margin-bottom: 16px;
            }
            .ge-server-item {
                background: #333;
                border: 2px solid #444;
                border-radius: 4px;
                padding: 12px;
                margin-bottom: 8px;
                transition: border-color 0.2s;
            }
            .ge-server-item.default {
                border-color: #4CAF50;
                background: #2a3a2a;
            }
            .ge-server-item.offline {
                opacity: 0.6;
            }
            .ge-server-item-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }
            .ge-server-item-name {
                font-weight: bold;
                font-size: 14px;
            }
            .ge-server-item-default-badge {
                background: #4CAF50;
                color: white;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
                margin-left: 8px;
            }
            .ge-server-item-url {
                color: #aaa;
                font-size: 12px;
                margin-bottom: 8px;
                word-break: break-all;
            }
            .ge-server-item-actions {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .ge-server-item-btn {
                padding: 4px 8px;
                font-size: 12px;
                border: 1px solid #444;
                background: #333;
                color: #fff;
                border-radius: 4px;
                cursor: pointer;
            }
            .ge-server-item-btn:hover {
                background: #444;
            }
            .ge-server-item-btn.primary {
                background: #4CAF50;
                border-color: #4CAF50;
            }
            .ge-server-item-btn.primary:hover {
                background: #45a049;
            }
            .ge-server-item-btn.danger {
                background: #f44336;
                border-color: #f44336;
            }
            .ge-server-item-btn.danger:hover {
                background: #d32f2f;
            }
            .ge-server-item-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .ge-server-add-btn {
                width: 100%;
                padding: 10px;
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                margin-bottom: 16px;
            }
            .ge-server-add-btn:hover {
                background: #45a049;
            }
            .ge-server-form {
                background: #333;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 16px;
            }
            .ge-server-form-row {
                margin-bottom: 12px;
            }
            .ge-server-form-row:last-child {
                margin-bottom: 0;
            }
            .ge-server-form-label {
                display: block;
                margin-bottom: 4px;
                font-size: 12px;
                color: #aaa;
            }
            .ge-server-form-input {
                width: 100%;
                padding: 6px 8px;
                background: #2a2a2a;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
                font-size: 14px;
                box-sizing: border-box;
            }
            .ge-server-form-input:focus {
                outline: none;
                border-color: #666;
            }
            .ge-server-form-input.error {
                border-color: #f44336;
            }
            .ge-server-form-hint {
                font-size: 11px;
                color: #888;
                margin-top: 4px;
            }
            .ge-server-form-actions {
                display: flex;
                gap: 8px;
                justify-content: flex-end;
                margin-top: 16px;
            }
            .ge-server-form-btn {
                padding: 6px 12px;
                border: 1px solid #444;
                background: #333;
                color: #fff;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
            }
            .ge-server-form-btn:hover {
                background: #444;
            }
            .ge-server-form-btn.primary {
                background: #4CAF50;
                border-color: #4CAF50;
            }
            .ge-server-form-btn.primary:hover {
                background: #45a049;
            }
            .ge-server-form-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .ge-server-status {
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                margin-right: 6px;
            }
            .ge-server-status.online {
                background: #4CAF50;
            }
            .ge-server-status.offline {
                background: #f44336;
            }
            .ge-server-status.testing {
                background: #ff9800;
                animation: pulse 1s infinite;
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            .ge-group-server-select {
                flex: 1;
                padding: 4px 8px;
                background: #333;
                border: 1px solid #444;
                color: #fff;
                border-radius: 4px;
                font-size: 12px;
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(this.container);
        
        // 创建服务器管理模态对话框
        this.createServerManagerModal();
    }
    attachEvents() {
        const header = this.container.querySelector('.ge-header');
        header.addEventListener('mousedown', (e) => {
            if (!e.target.matches('.ge-controls button')) {
                this.isDragging = true;
                const rect = this.container.getBoundingClientRect();
                this.dragOffset = {
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top
                };
            }
        });
        document.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                const x = e.clientX - this.dragOffset.x;
                const y = e.clientY - this.dragOffset.y;
                this.container.style.left = `${x}px`;
                this.container.style.top = `${y}px`;
            }
        });
        document.addEventListener('mouseup', () => {
            this.isDragging = false;
        });
        const serverManagerBtn = this.container.querySelector('.ge-server-manager-btn');
        serverManagerBtn.addEventListener('click', () => {
            this.openServerManager();
        });
        
        const dockBtn = this.container.querySelector('.ge-dock-btn');
        dockBtn.addEventListener('click', () => {
            this.showDockMenu(dockBtn);
        });
        const minimizeBtn = this.container.querySelector('.ge-minimize-btn');
        minimizeBtn.addEventListener('click', () => {
            this.container.classList.toggle('ge-minimized');
            minimizeBtn.textContent = this.container.classList.contains('ge-minimized') ? '+' : '-';
        });
        const closeBtn = this.container.querySelector('.ge-close-btn');
        closeBtn.addEventListener('click', () => {
            this.container.remove();
        });
        const groupCountInput = this.container.querySelector('.ge-group-count');
        groupCountInput.addEventListener('change', async () => {
            await this.updateGroupSelects(parseInt(groupCountInput.value));
        });
        const executeBtn = this.container.querySelector('.ge-execute-btn');
        executeBtn.addEventListener('click', () => {
            this.executeGroups();
        });
        const cancelBtn = this.container.querySelector('.ge-cancel-btn');
        cancelBtn.addEventListener('click', () => {
            this.cancelExecution();
        });
        // 初始化服务器列表
        this.servers = [];
        this.defaultServerId = null;
        this.properties = this.properties || {};
        this.properties.groups = [];
        
        // 异步加载服务器列表，然后初始化组选择器
        this.updateServerSelects().then(() => {
            this.updateGroupSelects(1);
        }).catch(err => {
            console.error('[GroupExecutorUI] 初始化失败:', err);
            // 即使加载失败，也初始化组选择器（使用空服务器列表）
            this.updateGroupSelects(1);
        });
        
        window.addEventListener('resize', () => {
            this.ensureInViewport();
        });
        const deleteConfigBtn = this.container.querySelector('.ge-delete-config');
        const saveConfigBtn = this.container.querySelector('.ge-save-config');
        const configSelect = this.container.querySelector('.ge-config-select');
        const updateDeleteButton = () => {
            deleteConfigBtn.disabled = !configSelect.value;
        };
        configSelect.addEventListener('change', () => {
            updateDeleteButton();
            if (configSelect.value) {
                this.loadConfig(configSelect.value);
            }
        });
        saveConfigBtn.addEventListener('click', () => {
            this.saveCurrentConfig();
        });
        deleteConfigBtn.addEventListener('click', () => {
            const configName = configSelect.value;
            if (configName) {
                this.deleteConfig(configName);
            }
        });
        updateDeleteButton();
        this.loadConfigs();
        const modeBtns = this.container.querySelectorAll('.ge-mode-btn');
        modeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                this.switchMode(mode);
            });
        });
        this.updateSingleModeList();
        const searchInput = this.container.querySelector('.ge-search-input');
        const clearButton = this.container.querySelector('.ge-search-clear');
        
        searchInput.addEventListener('input', () => {
            clearButton.style.display = searchInput.value ? 'block' : 'none';
        });
    }
    showDockMenu(button) {
        const existingMenu = document.querySelector('.ge-dock-menu');
        if (existingMenu) {
            existingMenu.remove();
            return;
        }
        const menu = document.createElement('div');
        menu.className = 'ge-dock-menu';
        menu.innerHTML = `
            <button data-position="top-left">左上角</button>
            <button data-position="top-right">右上角</button>
            <button data-position="bottom-left">左下角</button>
            <button data-position="bottom-right">右下角</button>
        `;
        this.container.appendChild(menu);
        const buttonRect = button.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();
        menu.style.left = `${buttonRect.left - containerRect.left}px`;
        menu.style.top = `${buttonRect.bottom - containerRect.top + 5}px`;
        requestAnimationFrame(() => {
            menu.classList.add('visible');
        });
        menu.addEventListener('click', (e) => {
            const position = e.target.dataset.position;
            if (position) {
                this.dockTo(position);
                menu.classList.remove('visible');
                setTimeout(() => menu.remove(), 200);
            }
        });
        const closeMenu = (e) => {
            if (!menu.contains(e.target) && e.target !== button) {
                menu.classList.remove('visible');
                setTimeout(() => menu.remove(), 200);
                document.removeEventListener('click', closeMenu);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', closeMenu);
        }, 0);
    }
    dockTo(position) {
        const style = this.container.style;
        style.transition = 'all 0.3s ease';
        const marginX = this.DOCK_MARGIN_X;
        const marginY = this.DOCK_MARGIN_Y;
        switch (position) {
            case 'top-left':
                style.top = `${marginY}px`;
                style.left = `${marginX}px`;
                style.right = 'auto';
                style.bottom = 'auto';
                break;
            case 'top-right':
                style.top = `${marginY}px`;
                style.right = `${marginX}px`;
                style.left = 'auto';
                style.bottom = 'auto';
                break;
            case 'bottom-left':
                style.bottom = `${marginY}px`;
                style.left = `${marginX}px`;
                style.right = 'auto';
                style.top = 'auto';
                break;
            case 'bottom-right':
                style.bottom = `${marginY}px`;
                style.right = `${marginX}px`;
                style.left = 'auto';
                style.top = 'auto';
                break;
        }
        setTimeout(() => {
            style.transition = '';
        }, 300);
    }
    async updateGroupSelects(count) {
        const container = this.container.querySelector('.ge-groups-container');
        container.innerHTML = '';
        const groupNames = this.getGroupNames();
        
        // 如果服务器列表未加载，先加载
        if (!this.servers || this.servers.length === 0) {
            await this.updateServerSelects();
        }
        
        // 获取当前的组配置（如果有）
        const currentGroups = this.properties?.groups || [];
        
        for (let i = 0; i < count; i++) {
            // 创建组选择器容器
            const groupContainer = document.createElement('div');
            groupContainer.className = 'ge-group-item-container';
            
            // 组选择器
            const select = document.createElement('select');
            select.className = 'ge-group-select';
            select.setAttribute('data-group-index', i);
            select.innerHTML = `
                <option value="">选择组 #${i + 1}</option>
                ${groupNames.map(name => `<option value="${name}">${name}</option>`).join('')}
            `;
            
            // 如果有保存的组配置，恢复它
            if (currentGroups[i]) {
                if (typeof currentGroups[i] === 'string') {
                    // 旧格式：只有组名
                    select.value = currentGroups[i];
                } else if (currentGroups[i] && currentGroups[i].group_name) {
                    // 新格式：包含组名和服务器ID
                    select.value = currentGroups[i].group_name;
                }
            }
            
            // 服务器选择器
            const serverSelect = document.createElement('select');
            serverSelect.className = 'ge-group-server-select';
            serverSelect.setAttribute('data-group-index', i);
            
            // 初始化服务器选择器选项
            this.updateServerSelectOptions(serverSelect);
            
            // 如果有保存的配置，恢复服务器ID
            if (currentGroups[i]) {
                if (typeof currentGroups[i] === 'object' && currentGroups[i].server_id) {
                    serverSelect.value = currentGroups[i].server_id;
                } else if (this.defaultServerId) {
                    serverSelect.value = this.defaultServerId;
                }
            } else if (this.defaultServerId) {
                serverSelect.value = this.defaultServerId;
            }
            
            // 将选择器添加到容器
            groupContainer.appendChild(select);
            groupContainer.appendChild(serverSelect);
            container.appendChild(groupContainer);
            
            // 绑定组选择器变化事件，更新配置
            select.addEventListener('change', () => {
                this.updateGroupConfig();
            });
            
            // 绑定服务器选择器变化事件，更新配置
            serverSelect.addEventListener('change', () => {
                this.updateGroupConfig();
            });
        }
    }
    
    updateGroupConfig() {
        // 更新内部配置数据结构
        if (!this.properties) {
            this.properties = {};
        }
        if (!this.properties.groups) {
            this.properties.groups = [];
        }
        
        const groupSelects = this.container.querySelectorAll('.ge-group-select');
        const serverSelects = this.container.querySelectorAll('.ge-group-server-select');
        
        const groups = [];
        for (let i = 0; i < groupSelects.length; i++) {
            const groupSelect = Array.from(groupSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            const serverSelect = Array.from(serverSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            
            if (groupSelect && groupSelect.value) {
                groups.push({
                    group_name: groupSelect.value,
                    server_id: (serverSelect && serverSelect.value) || this.defaultServerId || null
                });
            } else {
                groups.push(null); // 保持索引对齐
            }
        }
        
        // 过滤掉null值，但保留索引信息
        this.properties.groups = groups;
    }
    getGroupNames() {
        return [...app.graph._groups].map(g => g.title).sort();
    }
    updateStatus(text, progress = null) {
        const status = this.container.querySelector('.ge-status');
        status.innerHTML = `<span>${text}</span>`;
        if (progress !== null) {
            status.style.setProperty('--progress', `${progress}%`);
        }
    }
    async executeGroups() {
        if (this.isExecuting) {
            console.warn('[GroupExecutorUI] 已有执行任务在进行中');
            return;
        }
        const executeBtn = this.container.querySelector('.ge-execute-btn');
        const cancelBtn = this.container.querySelector('.ge-cancel-btn');
        const groupSelects = [...this.container.querySelectorAll('.ge-group-select')];
        const serverSelects = [...this.container.querySelectorAll('.ge-group-server-select')];
        const repeatCount = parseInt(this.container.querySelector('.ge-repeat-count').value);
        const delaySeconds = parseFloat(this.container.querySelector('.ge-delay').value);
        
        // 更新配置
        this.updateGroupConfig();
        
        this.isExecuting = true;
        this.isCancelling = false;
        executeBtn.disabled = true;
        cancelBtn.disabled = false;
        
        // 构建执行列表，包含组名和服务器ID
        const executionList = [];
        for (let i = 0; i < groupSelects.length; i++) {
            const groupSelect = Array.from(groupSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            const serverSelect = Array.from(serverSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            
            if (groupSelect && groupSelect.value) {
                const groupName = groupSelect.value;
                const serverId = (serverSelect && serverSelect.value) || this.defaultServerId || null;
                console.log(`[GroupExecutorUI] 构建执行列表 - 组 #${i + 1}: "${groupName}", serverId:`, serverId);
                executionList.push({
                    group_name: groupName,
                    server_id: serverId
                });
            }
        }
        console.log(`[GroupExecutorUI] 执行列表构建完成，共 ${executionList.length} 个组:`, executionList);
        
        if (executionList.length === 0) {
            this.isExecuting = false;
            executeBtn.disabled = false;
            cancelBtn.disabled = true;
            app.ui.dialog.show('请至少选择一个组');
            return;
        }
        
        // repeat_count = 1 表示不重复，只执行一次
        // repeat_count > 1 表示重复执行
        const totalSteps = repeatCount === 1 ? executionList.length : repeatCount * executionList.length;
        let currentStep = 0;
        try {
            if (repeatCount === 1) {
                // 只执行一次，不进入循环
                for (let i = 0; i < executionList.length; i++) {
                    if (this.isCancelling) {
                        console.log('[GroupExecutorUI] 执行被用户取消');
                        await api.interrupt();
                        this.updateStatus("已取消");
                        break;
                    }
                    const execItem = executionList[i];
                    const groupName = execItem.group_name;
                    const serverId = execItem.server_id;
                    
                    console.log(`[GroupExecutorUI] 执行组 "${groupName}", serverId:`, serverId);
                    
                    currentStep++;
                    const progress = (currentStep / totalSteps) * 100;
                    const serverName = this.servers.find(s => s.id === serverId)?.name || serverId || '默认';
                    this.updateStatus(`${currentStep}/${totalSteps} - ${groupName} [${serverName}]`, progress);
                    
                    try {
                        // 如果 serverId 为 null 或 "local"，使用当前服务器执行（通过 api.queuePrompt）
                        // 否则使用后台执行模式
                        if (serverId && serverId !== "local") {
                            console.log(`[GroupExecutorUI] 使用后台执行模式，serverId: ${serverId}`);
                            await this.executeGroupOnServer(groupName, serverId);
                        } else {
                            console.log(`[GroupExecutorUI] 使用当前服务器执行（通过 api.queuePrompt），serverId: ${serverId || 'null'}`);
                            await this.executeGroup(groupName, serverId);
                        }
                        if (i < executionList.length - 1 && delaySeconds > 0) {
                            this.updateStatus(`等待 ${delaySeconds}s...`);
                            await this.delay(delaySeconds);
                        }
                    } catch (error) {
                        throw new Error(`执行组 "${groupName}" 失败: ${error.message}`);
                    }
                }
            } else {
                // repeat_count > 1，进入循环重复执行
                for (let repeat = 0; repeat < repeatCount; repeat++) {
                    for (let i = 0; i < executionList.length; i++) {
                        if (this.isCancelling) {
                            console.log('[GroupExecutorUI] 执行被用户取消');
                            await api.interrupt();
                            this.updateStatus("已取消");
                            break;
                        }
                        const execItem = executionList[i];
                        const groupName = execItem.group_name;
                        const serverId = execItem.server_id;
                        
                        console.log(`[GroupExecutorUI] 执行组 "${groupName}" (第${repeat + 1}/${repeatCount}次), serverId:`, serverId);
                        
                        currentStep++;
                        const progress = (currentStep / totalSteps) * 100;
                        const serverName = this.servers.find(s => s.id === serverId)?.name || serverId || '默认';
                        this.updateStatus(`${currentStep}/${totalSteps} - ${groupName} [${serverName}] (${repeat + 1}/${repeatCount})`, progress);
                        
                        try {
                            // 如果 serverId 为 null 或 "local"，使用当前服务器执行（通过 api.queuePrompt）
                            // 否则使用后台执行模式
                            if (serverId && serverId !== "local") {
                                console.log(`[GroupExecutorUI] 使用后台执行模式，serverId: ${serverId}`);
                                await this.executeGroupOnServer(groupName, serverId);
                            } else {
                                console.log(`[GroupExecutorUI] 使用当前服务器执行（通过 api.queuePrompt），serverId: ${serverId || 'null'}`);
                                await this.executeGroup(groupName, serverId);
                            }
                            if (i < executionList.length - 1 && delaySeconds > 0) {
                                this.updateStatus(`等待 ${delaySeconds}s...`);
                                await this.delay(delaySeconds);
                            }
                        } catch (error) {
                            throw new Error(`执行组 "${groupName}" 失败: ${error.message}`);
                        }
                    }
                    if (repeat < repeatCount - 1 && !this.isCancelling) {
                        await this.delay(delaySeconds);
                    }
                }
            }
            if (!this.isCancelling) {
                this.updateStatus("完成");
            }
        } catch (error) {
            console.error('[GroupExecutorUI] 执行错误:', error);
            this.updateStatus(`错误: ${error.message}`);
            app.ui.dialog.show(`执行错误: ${error.message}`);
        } finally {
            this.isExecuting = false;
            this.isCancelling = false;
            executeBtn.disabled = false;
            cancelBtn.disabled = true;
        }
    }
    async executeGroup(groupName, serverId = null) {
        console.log(`[GroupExecutorUI] executeGroup 被调用, groupName: "${groupName}", serverId:`, serverId);
        
        const group = app.graph._groups.find(g => g.title === groupName);
        if (!group) {
            throw new Error(`未找到名为 "${groupName}" 的组`);
        }
        
        // 如果 serverId 不为 null 且不是 "local"，使用后台执行模式
        if (serverId && serverId !== "local") {
            console.log(`[GroupExecutorUI] executeGroup: serverId 不为空且不是 "local"，转发到 executeGroupOnServer，serverId: ${serverId}`);
            return await this.executeGroupOnServer(groupName, serverId);
        }
        
        // 当前服务器执行：通过 api.queuePrompt 执行（serverId 为 null 或 "local"）
        console.log(`[GroupExecutorUI] executeGroup: serverId 为 ${serverId || 'null'}，使用当前服务器执行（通过 api.queuePrompt）`);
        try {
            // 1. 生成完整的 API prompt
            const graphToPromptResult = await app.graphToPrompt();
            // graphToPrompt 返回格式通常是 { output: {...}, workflow: {...}, extra: {...} }
            const fullPrompt = graphToPromptResult.output || graphToPromptResult.prompt || graphToPromptResult;
            const fullOutput = graphToPromptResult.output_output || graphToPromptResult.extra?.output || {};
            
            // 2. 获取组内的输出节点
            const outputNodes = [];
            for (const node of app.graph._nodes) {
                if (!node || !node.pos) continue;
                if (LiteGraph.overlapBounding(group._bounding, node.getBounding())) {
                    if (node.mode !== LiteGraph.NEVER && node.constructor.nodeData?.output_node === true) {
                        outputNodes.push(node);
                    }
                }
            }
            if (outputNodes.length === 0) {
                throw new Error(`组 "${groupName}" 中没有找到输出节点`);
            }
            const outputNodeIds = outputNodes.map(n => String(n.id));
            
            // 3. 筛选 prompt，只保留输出节点及其依赖
            const filteredPrompt = {};
            const nodesToInclude = new Set();
            
            // 递归收集所有依赖节点
            const collectNodes = (nodeId) => {
                const nodeIdStr = String(nodeId);
                if (nodesToInclude.has(nodeIdStr)) return;
                nodesToInclude.add(nodeIdStr);
                
                const node = fullPrompt[nodeIdStr];
                if (node && node.inputs) {
                    for (const inputValue of Object.values(node.inputs)) {
                        if (Array.isArray(inputValue) && inputValue.length >= 1) {
                            collectNodes(inputValue[0]);
                        }
                    }
                }
            };
            
            // 收集所有输出节点及其依赖
            for (const nodeId of outputNodeIds) {
                collectNodes(nodeId);
            }
            
            // 构建筛选后的 prompt
            for (const nodeId of nodesToInclude) {
                if (fullPrompt[nodeId]) {
                    filteredPrompt[nodeId] = fullPrompt[nodeId];
                }
            }
            
            // 4. 构建 output 参数
            const output = {};
            for (const nodeId of outputNodeIds) {
                if (filteredPrompt[nodeId]) {
                    // 优先使用完整 output 中的信息，否则使用空数组 [] 表示所有输出
                    if (fullOutput[nodeId] && Array.isArray(fullOutput[nodeId])) {
                        output[nodeId] = fullOutput[nodeId];
                    } else {
                        output[nodeId] = [];
                    }
                }
            }
            
            // 5. 通过 api.queuePrompt 提交
            // 优先使用 queueManager.queueOutputNodes，它会正确处理所有必需的字段
            try {
                // 将字符串 ID 转换为数字 ID
                const numericNodeIds = outputNodeIds.map(id => parseInt(id)).filter(id => !isNaN(id));
                await queueManager.queueOutputNodes(numericNodeIds);
                await this.waitForQueue();
                console.log(`[GroupExecutorUI] 已通过 queueManager.queueOutputNodes 执行组: ${groupName}`);
                
                // 组执行完成，尝试设置结果到文件系统
                await this.setGroupResultToFile(groupName);
            } catch (queueError) {
                console.warn(`[GroupExecutorUI] queueManager.queueOutputNodes 失败，尝试使用 api.queuePrompt:`, queueError);
                // 如果 queueManager 失败，使用 api.queuePrompt
                const promptToQueue = {
                    prompt: filteredPrompt,
                    output: output
                };
                
                // 如果 graphToPromptResult 包含 workflow 或 extra 字段，也包含它们
                if (graphToPromptResult.workflow) {
                    promptToQueue.workflow = graphToPromptResult.workflow;
                }
                if (graphToPromptResult.extra) {
                    promptToQueue.extra = graphToPromptResult.extra;
                }
                
                await api.queuePrompt(0, promptToQueue);
                await this.waitForQueue();
                console.log(`[GroupExecutorUI] 已通过 api.queuePrompt 执行组: ${groupName}`);
                
                // 组执行完成，尝试设置结果到文件系统
                await this.setGroupResultToFile(groupName);
            }
            
            console.log(`[GroupExecutorUI] 已通过 api.queuePrompt 执行组: ${groupName}`);
        } catch (error) {
            console.error(`[GroupExecutorUI] 通过 api.queuePrompt 执行失败:`, error);
            console.error(`[GroupExecutorUI] 错误详情:`, error.stack);
            throw error;
        }
    }
    
    async executeGroupOnServer(groupName, serverId) {
        console.log(`[GroupExecutorUI] executeGroupOnServer 被调用, groupName: "${groupName}", serverId:`, serverId);
        
        // 使用后台执行模式，向指定服务器发送请求
        try {
            // 1. 生成完整的 API prompt
            const { output: fullApiPrompt } = await app.graphToPrompt();
            
            // 2. 获取组内的输出节点
            const group = app.graph._groups.find(g => g.title === groupName);
            if (!group) {
                throw new Error(`未找到名为 "${groupName}" 的组`);
            }
            
            const outputNodes = [];
            for (const node of app.graph._nodes) {
                if (!node || !node.pos) continue;
                if (LiteGraph.overlapBounding(group._bounding, node.getBounding())) {
                    if (node.mode !== LiteGraph.NEVER && node.constructor.nodeData?.output_node === true) {
                        outputNodes.push(node);
                    }
                }
            }
            
            if (outputNodes.length === 0) {
                throw new Error(`组 "${groupName}" 中没有找到输出节点`);
            }
            
            const outputNodeIds = outputNodes.map(n => n.id);
            
            // 3. 构建执行列表
            const executionList = [{
                group_name: groupName,
                repeat_count: 1,
                delay_seconds: 0,
                output_node_ids: outputNodeIds,
                server_id: serverId
            }];
            
            // 4. 发送给后端
            const response = await api.fetchApi('/group_executor/execute_backend', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    node_id: `ui_${Date.now()}`,
                    execution_list: executionList,
                    api_prompt: fullApiPrompt
                })
            });
            
            if (!response.ok) {
                const text = await response.text();
                throw new Error(`服务器错误 ${response.status}: ${text.substring(0, 200)}`);
            }
            
            const result = await response.json();
            if (result.status !== "success") {
                throw new Error(result.message || "后台执行启动失败");
            }
            
            console.log(`[GroupExecutorUI] 已向服务器发送执行请求: ${groupName}`);
            
        } catch (error) {
            console.error(`[GroupExecutorUI] 向服务器发送执行请求失败:`, error);
            throw error;
        }
    }
    async cancelExecution() {
        if (!this.isExecuting) {
            console.warn('[GroupExecutorUI] 没有正在执行的任务');
            return;
        }
        try {
            this.isCancelling = true;
            this.updateStatus("已取消", 0);
            await api.interrupt();
        } catch (error) {
            console.error('[GroupExecutorUI] 取消执行时出错:', error);
            this.updateStatus(`取消失败: ${error.message}`, 0);
        }
    }
    async getQueueStatus() {
        try {
            const response = await fetch('/queue');
            const data = await response.json();
            return {
                isRunning: data.queue_running.length > 0,
                isPending: data.queue_pending.length > 0,
                runningCount: data.queue_running.length,
                pendingCount: data.queue_pending.length,
                rawRunning: data.queue_running,
                rawPending: data.queue_pending
            };
        } catch (error) {
            console.error('[GroupExecutor] 获取队列状态失败:', error);
            return {
                isRunning: false,
                isPending: false,
                runningCount: 0,
                pendingCount: 0,
                rawRunning: [],
                rawPending: []
            };
        }
    }
    async waitForQueue() {
        return new Promise((resolve, reject) => {
            const checkQueue = async () => {
                try {
                    const status = await this.getQueueStatus();
                    if (!status.isRunning && !status.isPending) {
                        setTimeout(resolve, 100);
                        return;
                    }
                    setTimeout(checkQueue, 500);
                } catch (error) {
                    console.warn(`[GroupExecutor] 检查队列状态失败:`, error);
                    setTimeout(checkQueue, 500);
                }
            };
            checkQueue();
        });
    }
    
    // 设置组执行结果到文件系统
    async setGroupResultToFile(groupName) {
        try {
            // 获取最新的 execution_id
            const response = await api.fetchApi('/group_executor/results/latest/id');
            if (!response.ok) {
                // 如果没有找到 execution_id，说明可能没有 GroupExecutorWaitAll 节点在等待
                console.log(`[GroupExecutorUI] 未找到执行任务，跳过设置结果: ${groupName}`);
                return;
            }
            
            const data = await response.json();
            if (data.status !== "success" || !data.execution_id) {
                console.log(`[GroupExecutorUI] 未找到执行ID，跳过设置结果: ${groupName}`);
                return;
            }
            
            const execution_id = data.execution_id;
            
            // 设置组结果
            const setResponse = await api.fetchApi('/group_executor/results/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    execution_id: execution_id,
                    group_name: groupName,
                    result_data: {
                        completed: true,
                        completed_at: new Date().toISOString()
                    }
                })
            });
            
            if (setResponse.ok) {
                const setData = await setResponse.json();
                if (setData.status === "success") {
                    console.log(`[GroupExecutorUI] 组 "${groupName}" 结果已设置到文件系统: ${execution_id}`);
                } else {
                    console.warn(`[GroupExecutorUI] 设置组结果失败: ${setData.message}`);
                }
            } else {
                console.warn(`[GroupExecutorUI] 设置组结果API调用失败: ${setResponse.status}`);
            }
        } catch (error) {
            // 静默失败，不影响主流程
            console.warn(`[GroupExecutorUI] 设置组结果到文件系统时出错:`, error);
        }
    }
    
    async delay(seconds) {
        if (seconds <= 0) return;
        return new Promise(resolve => setTimeout(resolve, seconds * 1000));
    }
    ensureInViewport() {
        const rect = this.container.getBoundingClientRect();
        const windowWidth = window.innerWidth;
        const windowHeight = window.innerHeight;
        if (this.container.style.right !== 'auto') {
            this.container.style.right = `${this.DOCK_MARGIN_X}px`;
        }
        if (this.container.style.left !== 'auto') {
            this.container.style.left = `${this.DOCK_MARGIN_X}px`;
        }
        if (this.container.style.top !== 'auto') {
            this.container.style.top = `${this.DOCK_MARGIN_Y}px`;
        }
        if (this.container.style.bottom !== 'auto') {
            this.container.style.bottom = `${this.DOCK_MARGIN_Y}px`;
        }
    }
    async loadConfigs() {
        try {
            const response = await api.fetchApi('/group_executor/configs', {
                method: 'GET'
            });
            const result = await response.json();
            if (result.status === "error") {
                throw new Error(result.message);
            }
            const select = this.container.querySelector('.ge-config-select');
            select.innerHTML = `
                <option value="">选择配置</option>
                ${result.configs.map(config => `<option value="${config.name}">${config.name}</option>`).join('')}
            `;
        } catch (error) {
            console.error('[GroupExecutor] 加载配置失败:', error);
            app.ui.dialog.show('加载配置失败: ' + error.message);
        }
    }
    async saveCurrentConfig() {
        const configName = prompt('请输入配置名称:', '新配置');
        if (!configName) return;
        
        // 更新当前配置
        this.updateGroupConfig();
        
        // 构建配置对象，包含服务器信息
        const groups = [];
        const groupSelects = this.container.querySelectorAll('.ge-group-select');
        const serverSelects = this.container.querySelectorAll('.ge-group-server-select');
        
        for (let i = 0; i < groupSelects.length; i++) {
            const groupSelect = Array.from(groupSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            const serverSelect = Array.from(serverSelects).find(s => parseInt(s.dataset.groupIndex) === i);
            
            if (groupSelect && groupSelect.value) {
                const groupConfig = {
                    group_name: groupSelect.value,
                    server_id: (serverSelect && serverSelect.value) || this.defaultServerId || null
                };
                groups.push(groupConfig);
            }
        }
        
        // 过滤掉空的组配置
        const validGroups = groups.filter(g => g && g.group_name);
        
        const config = {
            name: configName,
            groups: validGroups,
            repeatCount: parseInt(this.container.querySelector('.ge-repeat-count').value),
            delay: parseFloat(this.container.querySelector('.ge-delay').value)
        };
        try {
            const jsonString = JSON.stringify(config);
            JSON.parse(jsonString);
            const response = await api.fetchApi('/group_executor/configs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: jsonString
            });
            const result = await response.json();
            if (result.status === "error") {
                throw new Error(result.message);
            }
            await this.loadConfigs();
            app.ui.dialog.show('配置保存成功');
        } catch (error) {
            console.error('[GroupExecutor] 保存配置失败:', error);
            app.ui.dialog.show('保存配置失败: ' + error.message);
        }
    }
    async loadConfig(configName) {
        try {
            const response = await api.fetchApi(`/group_executor/configs/${configName}`, {
                method: 'GET',
                cache: 'no-store'
            });
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const config = await response.json();
            const groupCountInput = this.container.querySelector('.ge-group-count');
            
            // 处理旧格式配置（只有组名字符串）和新格式（包含group_name和server_id）
            const groups = config.groups || [];
            const groupCount = groups.length || 1;
            
            groupCountInput.value = groupCount;
            
            // 保存配置到属性中，以便updateGroupSelects恢复
            this.properties = this.properties || {};
            this.properties.groups = groups.map(group => {
                if (typeof group === 'string') {
                    // 旧格式：只有组名，使用默认服务器
                    return {
                        group_name: group,
                        server_id: this.defaultServerId || null
                    };
                } else if (group.group_name) {
                    // 新格式：包含组名和服务器ID
                    return group;
                }
                return null;
            }).filter(Boolean);
            
            // 先保存配置到properties，这样updateGroupSelects可以恢复
            this.properties = this.properties || {};
            this.properties.groups = groups.map(group => {
                if (typeof group === 'string') {
                    // 旧格式：只有组名，使用默认服务器
                    return {
                        group_name: group,
                        server_id: this.defaultServerId || null
                    };
                } else if (group && group.group_name) {
                    // 新格式：包含组名和服务器ID
                    return group;
                }
                return null;
            }).filter(Boolean);
            
            // 等待updateGroupSelects完成（它会自动从properties恢复配置）
            await this.updateGroupSelects(groupCount);
            
            this.container.querySelector('.ge-repeat-count').value = config.repeatCount || 1;
            this.container.querySelector('.ge-delay').value = config.delay || 0;
        } catch (error) {
            console.error('加载配置失败:', error);
            app.ui.dialog.show('加载配置失败: ' + error.message);
        }
    }
    async deleteConfig(configName) {
        if (!configName) return;
        if (!confirm(`确定要删除配置 "${configName}" 吗？`)) {
            return;
        }
        try {
            const response = await api.fetchApi(`/group_executor/configs/${configName}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            if (result.status === "error") {
                throw new Error(result.message);
            }
            await this.loadConfigs();
            app.ui.dialog.show('配置已删除');
        } catch (error) {
            console.error('[GroupExecutor] 删除配置失败:', error);
            app.ui.dialog.show('删除配置失败: ' + error.message);
        }
    }
    switchMode(mode) {
        const multiMode = this.container.querySelector('.ge-multi-mode');
        const singleMode = this.container.querySelector('.ge-single-mode');
        const modeBtns = this.container.querySelectorAll('.ge-mode-btn');
        
        modeBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        
        if (mode === 'multi') {
            multiMode.style.display = '';
            singleMode.style.display = 'none';
        } else {
            multiMode.style.display = 'none';
            singleMode.style.display = '';
            this.updateSingleModeList();
        }
    }
    updateSingleModeList() {
        const container = this.container.querySelector('.ge-groups-list');
        const searchInput = this.container.querySelector('.ge-search-input');
        const clearButton = this.container.querySelector('.ge-search-clear');
        const groupNames = this.getGroupNames();
        
        const filterGroups = (searchText) => {
            const normalizedSearch = searchText.toLowerCase();
            return groupNames.filter(name => 
                name.toLowerCase().includes(normalizedSearch)
            );
        };

        const renderGroups = (filteredGroups) => {
            container.innerHTML = filteredGroups.map(name => `
                <div class="ge-group-item" data-group="${name}">
                    <span class="ge-group-name">${name}</span>
                    <div class="ge-group-controls">
                        <button class="ge-execute-single-btn">执行</button>
                        <button class="ge-cancel-single-btn" disabled>取消</button>
                    </div>
                </div>
            `).join('');

            container.querySelectorAll('.ge-group-item').forEach(item => {
                const groupName = item.dataset.group;
                const executeBtn = item.querySelector('.ge-execute-single-btn');
                const cancelBtn = item.querySelector('.ge-cancel-single-btn');
                
                executeBtn.addEventListener('click', async () => {
                    executeBtn.disabled = true;
                    cancelBtn.disabled = false;
                    cancelBtn.style.display = 'block';
                    this.isExecuting = true;
                    this.isCancelling = false;
                    
                    try {
                        await this.executeGroup(groupName);
                        this.updateStatus(`组 "${groupName}" 执行完成`);
                    } catch (error) {
                        this.updateStatus(`执行失败: ${error.message}`);
                        console.error(error);
                    } finally {
                        this.isExecuting = false;
                        this.isCancelling = false;
                        executeBtn.disabled = false;
                        cancelBtn.disabled = true;
                        cancelBtn.style.display = 'none';
                    }
                });
                
                cancelBtn.addEventListener('click', async () => {
                    if (!this.isExecuting) return;
                    
                    try {
                        this.isCancelling = true;
                        this.updateStatus("正在取消...", 0);
                        await api.interrupt();
                        this.updateStatus("已取消", 0);
                    } catch (error) {
                        console.error('[GroupExecutorUI] 取消执行时出错:', error);
                        this.updateStatus(`取消失败: ${error.message}`, 0);
                    }
                });
            });
        };

        renderGroups(groupNames);

        searchInput.addEventListener('input', (e) => {
            const searchText = e.target.value;
            clearButton.style.display = searchText ? 'block' : 'none';
            const filteredGroups = filterGroups(searchText);
            renderGroups(filteredGroups);
        });

        clearButton.addEventListener('click', () => {
            searchInput.value = '';
            clearButton.style.display = 'none';
            renderGroups(groupNames);
        });
    }
    // ============ 服务器管理相关方法 ============
    
    createServerManagerModal() {
        // 创建服务器管理模态对话框
        const modal = document.createElement('div');
        modal.className = 'ge-server-modal';
        modal.innerHTML = `
            <div class="ge-server-dialog">
                <div class="ge-server-dialog-header">
                    <span class="ge-server-dialog-title">服务器配置管理</span>
                    <button class="ge-server-dialog-close">×</button>
                </div>
                <div class="ge-server-dialog-content">
                    <button class="ge-server-add-btn">+ 添加服务器</button>
                    <div class="ge-server-list"></div>
                </div>
                <div class="ge-server-dialog-footer">
                    <button class="ge-server-form-btn" id="ge-server-close-btn">关闭</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        this.serverModal = modal;
        
        // 绑定事件
        modal.querySelector('.ge-server-dialog-close').addEventListener('click', () => {
            this.closeServerManager();
        });
        modal.querySelector('#ge-server-close-btn').addEventListener('click', () => {
            this.closeServerManager();
        });
        modal.querySelector('.ge-server-add-btn').addEventListener('click', () => {
            this.openServerForm();
        });
        
        // 点击遮罩层关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeServerManager();
            }
        });
        
        // ESC键关闭
        this.serverModalEscHandler = (e) => {
            if (e.key === 'Escape' && this.serverModal.classList.contains('visible')) {
                this.closeServerManager();
            }
        };
        document.addEventListener('keydown', this.serverModalEscHandler);
    }
    
    async openServerManager() {
        this.serverModal.classList.add('visible');
        await this.loadServers();
    }
    
    closeServerManager() {
        this.serverModal.classList.remove('visible');
        // 如果有打开的编辑表单，关闭它
        const form = this.serverModal.querySelector('.ge-server-form');
        if (form) {
            form.remove();
        }
    }
    
    async loadServers() {
        try {
            const response = await api.fetchApi('/group_executor/servers', {
                method: 'GET'
            });
            const result = await response.json();
            
            if (result.status === 'error') {
                throw new Error(result.message);
            }
            
            this.servers = result.servers || [];
            this.defaultServerId = result.default_server || null;
            this.renderServerList();
        } catch (error) {
            console.error('[GroupExecutorUI] 加载服务器列表失败:', error);
            app.ui.dialog.show('加载服务器列表失败: ' + error.message);
        }
    }
    
    renderServerList() {
        const listContainer = this.serverModal.querySelector('.ge-server-list');
        listContainer.innerHTML = '';
        
        if (this.servers.length === 0) {
            listContainer.innerHTML = '<div style="text-align: center; color: #aaa; padding: 20px;">暂无服务器配置</div>';
            return;
        }
        
        // 先渲染默认服务器，然后渲染其他服务器
        const sortedServers = [...this.servers].sort((a, b) => {
            const aIsDefault = a.id === this.defaultServerId;
            const bIsDefault = b.id === this.defaultServerId;
            if (aIsDefault && !bIsDefault) return -1;
            if (!aIsDefault && bIsDefault) return 1;
            return 0;
        });
        
        sortedServers.forEach(server => {
            const isDefault = server.id === this.defaultServerId;
            const item = document.createElement('div');
            item.className = `ge-server-item ${isDefault ? 'default' : ''}`;
            item.innerHTML = `
                <div class="ge-server-item-header">
                    <div>
                        <span class="ge-server-status ${server.is_online !== false ? 'online' : 'offline'}" id="status-${server.id}"></span>
                        <span class="ge-server-item-name">${this.escapeHtml(server.name)}</span>
                        ${isDefault ? '<span class="ge-server-item-default-badge">✓ 默认</span>' : ''}
                    </div>
                </div>
                <div class="ge-server-item-url">${this.escapeHtml(server.url)}</div>
                <div class="ge-server-item-actions">
                    ${!isDefault ? `<button class="ge-server-item-btn primary" data-action="set-default" data-id="${server.id}">设为默认</button>` : ''}
                    <button class="ge-server-item-btn" data-action="test" data-id="${server.id}">测试连接</button>
                    <button class="ge-server-item-btn" data-action="edit" data-id="${server.id}">编辑</button>
                    <button class="ge-server-item-btn danger" data-action="delete" data-id="${server.id}" ${isDefault ? 'disabled' : ''}>删除</button>
                </div>
            `;
            listContainer.appendChild(item);
        });
        
        // 绑定按钮事件
        listContainer.querySelectorAll('.ge-server-item-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const action = btn.dataset.action;
                const serverId = btn.dataset.id;
                
                if (action === 'set-default') {
                    await this.setDefaultServer(serverId);
                } else if (action === 'test') {
                    await this.testConnection(serverId);
                } else if (action === 'edit') {
                    this.openServerForm(serverId);
                } else if (action === 'delete') {
                    await this.deleteServer(serverId);
                }
            });
        });
    }
    
    openServerForm(serverId = null) {
        // 如果有现有的表单，先移除
        const existingForm = this.serverModal.querySelector('.ge-server-form');
        if (existingForm) {
            existingForm.remove();
        }
        
        const server = serverId ? this.servers.find(s => s.id === serverId) : null;
        const isEdit = !!server;
        
        const form = document.createElement('div');
        form.className = 'ge-server-form';
        form.innerHTML = `
            <div class="ge-server-form-row">
                <label class="ge-server-form-label">服务器名称 *</label>
                <input type="text" class="ge-server-form-input" id="server-form-name" 
                       value="${server ? this.escapeHtml(server.name) : ''}" 
                       placeholder="例如：本地服务器">
                <div class="ge-server-form-hint">用于识别服务器的显示名称</div>
            </div>
            <div class="ge-server-form-row">
                <label class="ge-server-form-label">服务器URL *</label>
                <input type="text" class="ge-server-form-input" id="server-form-url" 
                       value="${server ? this.escapeHtml(server.url) : ''}" 
                       placeholder="例如：http://127.0.0.1:8188">
                <div class="ge-server-form-hint">ComfyUI服务器的完整URL，格式：http://ip:port</div>
            </div>
            <div class="ge-server-form-row">
                <label class="ge-server-form-label">认证Token (可选)</label>
                <input type="password" class="ge-server-form-input" id="server-form-token" 
                       value="${server && server.auth_token ? '***' : ''}" 
                       placeholder="如果需要认证，请输入Token">
                <div class="ge-server-form-hint">如果服务器需要认证，请输入Token</div>
            </div>
            <div class="ge-server-form-actions">
                <button class="ge-server-form-btn" id="server-form-cancel">取消</button>
                <button class="ge-server-form-btn" id="server-form-test">测试连接</button>
                <button class="ge-server-form-btn primary" id="server-form-save">保存</button>
            </div>
        `;
        
        const content = this.serverModal.querySelector('.ge-server-dialog-content');
        const addBtn = content.querySelector('.ge-server-add-btn');
        content.insertBefore(form, addBtn.nextSibling);
        
        // 如果是编辑模式且已有token，标记为已设置
        let tokenChanged = false;
        const tokenInput = form.querySelector('#server-form-token');
        if (server && server.auth_token) {
            tokenInput.placeholder = '已设置（留空表示不修改，输入新值表示更新）';
            tokenInput.addEventListener('input', () => {
                tokenChanged = true;
            });
        }
        
        // 绑定事件
        form.querySelector('#server-form-cancel').addEventListener('click', () => {
            form.remove();
        });
        
        form.querySelector('#server-form-test').addEventListener('click', async () => {
            await this.testServerUrl(form);
        });
        
        form.querySelector('#server-form-save').addEventListener('click', async () => {
            await this.saveServerForm(form, serverId, server);
        });
        
        // Enter键保存
        form.querySelectorAll('.ge-server-form-input').forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    form.querySelector('#server-form-save').click();
                }
            });
        });
    }
    
    async saveServerForm(form, serverId, oldServer) {
        const nameInput = form.querySelector('#server-form-name');
        const urlInput = form.querySelector('#server-form-url');
        const tokenInput = form.querySelector('#server-form-token');
        
        const name = nameInput.value.trim();
        const url = urlInput.value.trim();
        let token = tokenInput.value.trim();
        
        // 验证
        if (!name) {
            nameInput.classList.add('error');
            app.ui.dialog.show('服务器名称不能为空');
            return;
        }
        nameInput.classList.remove('error');
        
        if (!url) {
            urlInput.classList.add('error');
            app.ui.dialog.show('服务器URL不能为空');
            return;
        }
        
        // URL格式验证
        try {
            const urlObj = new URL(url);
            if (!['http:', 'https:'].includes(urlObj.protocol)) {
                throw new Error('URL必须使用http://或https://协议');
            }
        } catch (e) {
            urlInput.classList.add('error');
            app.ui.dialog.show('URL格式无效：' + e.message);
            return;
        }
        urlInput.classList.remove('error');
        
        // 如果是编辑模式，且token输入框显示的是"***"，表示未修改
        if (oldServer && oldServer.auth_token && token === '***') {
            token = null; // 不更新token
        } else if (token === '') {
            token = null; // 空字符串转为null
        }
        
        // 保存按钮禁用，显示加载状态
        const saveBtn = form.querySelector('#server-form-save');
        saveBtn.disabled = true;
        saveBtn.textContent = '保存中...';
        
        try {
            if (serverId) {
                // 更新服务器
                const updateData = { name, url };
                if (token !== null) {
                    updateData.auth_token = token;
                }
                
                const response = await api.fetchApi(`/group_executor/servers/${serverId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData)
                });
                
                const result = await response.json();
                if (result.status === 'error') {
                    throw new Error(result.message);
                }
                
                app.ui.dialog.show('服务器更新成功');
            } else {
                // 添加服务器
                const response = await api.fetchApi('/group_executor/servers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, url, auth_token: token })
                });
                
                const result = await response.json();
                if (result.status === 'error') {
                    throw new Error(result.message);
                }
                
                app.ui.dialog.show('服务器添加成功');
            }
            
            // 重新加载服务器列表
            await this.loadServers();
            
            // 如果这是第一个服务器或者是默认服务器，更新组选择器的服务器列表
            await this.updateServerSelects();
            
            // 关闭表单
            form.remove();
        } catch (error) {
            console.error('[GroupExecutorUI] 保存服务器失败:', error);
            app.ui.dialog.show('保存服务器失败: ' + error.message);
            saveBtn.disabled = false;
            saveBtn.textContent = '保存';
        }
    }
    
    async testServerUrl(form) {
        const urlInput = form.querySelector('#server-form-url');
        const tokenInput = form.querySelector('#server-form-token');
        const testBtn = form.querySelector('#server-form-test');
        
        const url = urlInput.value.trim();
        let token = tokenInput.value.trim();
        
        if (!url) {
            app.ui.dialog.show('请输入服务器URL');
            return;
        }
        
        // 如果token是"***"，表示已设置但未修改，需要从服务器获取
        let tokenToTest = token === '***' ? null : (token || null);
        
        testBtn.disabled = true;
        testBtn.textContent = '测试中...';
        
        try {
            const response = await api.fetchApi('/group_executor/servers/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, auth_token: tokenToTest })
            });
            
            const result = await response.json();
            if (result.success) {
                app.ui.dialog.show('连接成功！');
            } else {
                app.ui.dialog.show('连接失败: ' + result.message);
            }
        } catch (error) {
            console.error('[GroupExecutorUI] 测试连接失败:', error);
            app.ui.dialog.show('测试连接失败: ' + error.message);
        } finally {
            testBtn.disabled = false;
            testBtn.textContent = '测试连接';
        }
    }
    
    async deleteServer(serverId) {
        const server = this.servers.find(s => s.id === serverId);
        if (!server) return;
        
        if (!confirm(`确定要删除服务器 "${server.name}" 吗？\n\n注意：此操作不可恢复。`)) {
            return;
        }
        
        try {
            const response = await api.fetchApi(`/group_executor/servers/${serverId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            if (result.status === 'error') {
                throw new Error(result.message);
            }
            
            app.ui.dialog.show('服务器删除成功');
            
            // 重新加载服务器列表
            await this.loadServers();
            
            // 更新组选择器的服务器列表
            await this.updateServerSelects();
        } catch (error) {
            console.error('[GroupExecutorUI] 删除服务器失败:', error);
            app.ui.dialog.show('删除服务器失败: ' + error.message);
        }
    }
    
    async setDefaultServer(serverId) {
        try {
            const response = await api.fetchApi(`/group_executor/servers/${serverId}/set_default`, {
                method: 'POST'
            });
            
            const result = await response.json();
            if (result.status === 'error') {
                throw new Error(result.message);
            }
            
            app.ui.dialog.show('默认服务器设置成功');
            
            // 重新加载服务器列表
            await this.loadServers();
        } catch (error) {
            console.error('[GroupExecutorUI] 设置默认服务器失败:', error);
            app.ui.dialog.show('设置默认服务器失败: ' + error.message);
        }
    }
    
    async testConnection(serverId) {
        const statusEl = document.querySelector(`#status-${serverId}`);
        if (statusEl) {
            statusEl.className = 'ge-server-status testing';
        }
        
        try {
            const response = await api.fetchApi(`/group_executor/servers/${serverId}/test`, {
                method: 'POST'
            });
            
            const result = await response.json();
            if (result.success) {
                if (statusEl) {
                    statusEl.className = 'ge-server-status online';
                }
                app.ui.dialog.show('连接成功！');
            } else {
                if (statusEl) {
                    statusEl.className = 'ge-server-status offline';
                }
                app.ui.dialog.show('连接失败: ' + result.message);
            }
        } catch (error) {
            console.error('[GroupExecutorUI] 测试连接失败:', error);
            if (statusEl) {
                statusEl.className = 'ge-server-status offline';
            }
            app.ui.dialog.show('测试连接失败: ' + error.message);
        }
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    async updateServerSelects() {
        // 加载服务器列表（用于初始化）
        try {
            const response = await api.fetchApi('/group_executor/servers', {
                method: 'GET'
            });
            const result = await response.json();
            
            if (result.status === 'success') {
                this.servers = result.servers || [];
                this.defaultServerId = result.default_server || null;
                
                // 更新所有组选择器的服务器下拉框
                const serverSelects = this.container.querySelectorAll('.ge-group-server-select');
                serverSelects.forEach(select => {
                    const currentServerId = select.value || this.defaultServerId;
                    this.updateServerSelectOptions(select);
                    select.value = currentServerId || this.defaultServerId || '';
                });
                
                return true;
            }
            return false;
        } catch (error) {
            console.error('[GroupExecutorUI] 加载服务器列表失败:', error);
            // 使用默认值
            this.servers = [];
            this.defaultServerId = null;
            return false;
        }
    }
    
    updateServerSelectOptions(select) {
        const currentValue = select.value;
        select.innerHTML = '';
        
        if (this.servers && this.servers.length > 0) {
            this.servers.forEach(server => {
                const option = document.createElement('option');
                option.value = server.id;
                option.textContent = server.name + (server.id === this.defaultServerId ? ' (默认)' : '');
                if (server.id === currentValue || (!currentValue && server.id === this.defaultServerId)) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
        } else {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = '暂无服务器';
            select.appendChild(option);
        }
    }
}
// 监听后端发送的 queue_prompt_backend 事件，通过前端 API 提交 prompt
api.addEventListener("queue_prompt_backend", async ({ detail }) => {
    try {
        const prompt_id = detail.prompt_id;
        const prompt = detail.prompt;
        const output_node_ids = detail.output_node_ids || [];
        
        if (!prompt_id || !prompt) {
            console.error('[GroupExecutorUI] queue_prompt_backend 事件缺少必要参数');
            return;
        }
        
        console.log(`[GroupExecutorUI] 收到 queue_prompt_backend 事件: prompt_id=${prompt_id}, output_node_ids=${output_node_ids.join(',')}`);
        
        // 使用前端 API 提交 prompt，确保预览图能正确显示
        try {
            let promptToQueue = { prompt: prompt };
            
            // 如果有输出节点ID，需要构建 output 参数
            if (output_node_ids && output_node_ids.length > 0) {
                // 构建 output 对象：对于每个输出节点，使用空数组 [] 表示所有输出
                // ComfyUI 会自动处理空数组，将其视为所有输出
                const output = {};
                for (const nodeId of output_node_ids) {
                    const nodeIdStr = String(nodeId);
                    if (prompt[nodeIdStr]) {
                        // 使用空数组 [] 表示所有输出，这样 ComfyUI 会显示所有输出
                        output[nodeIdStr] = [];
                    }
                }
                
                promptToQueue.output = output;
            }
            
            // 使用 api.queuePrompt 提交 prompt
            await api.queuePrompt(0, promptToQueue);
            
            console.log(`[GroupExecutorUI] 已通过前端 API 提交 prompt: prompt_id=${prompt_id}`);
        } catch (error) {
            console.error(`[GroupExecutorUI] 通过前端 API 提交 prompt 失败:`, error);
            throw error;
        }
    } catch (error) {
        console.error('[GroupExecutorUI] 处理 queue_prompt_backend 事件失败:', error);
    }
});

app.registerExtension({
    name: "GroupExecutorUI",
    async setup() {
        // 等待UI初始化完成
        if (app.ui && app.ui.settings) {
            await app.ui.settings.setup;
        }
        
        // 注册右键菜单的函数
        const registerMenu = () => {
            // 尝试通过LGraphCanvas原型注册
            if (typeof LiteGraph !== 'undefined' && LiteGraph.LGraphCanvas && LiteGraph.LGraphCanvas.prototype) {
                const origMenu = LiteGraph.LGraphCanvas.prototype.getCanvasMenuOptions;
                if (origMenu && typeof origMenu === 'function') {
                    LiteGraph.LGraphCanvas.prototype.getCanvasMenuOptions = function() {
                        const options = origMenu.call(this) || [];
                        
                        // 检查是否已经添加过（防止重复添加）
                        const alreadyAdded = options.some(opt => 
                            opt && typeof opt === 'object' && opt.content === "⚡ 打开组执行器"
                        );
                        
                        if (!alreadyAdded) {
                            // 在菜单顶部添加组执行器选项（在第一个选项之后）
                            options.splice(1, 0, null); // 在第一个选项后添加分隔线
                            options.splice(2, 0, {
                                content: "⚡ 打开组执行器",
                                callback: () => {
                                    new GroupExecutorUI();
                                }
                            });
                        }
                        
                        return options;
                    };
                    console.log('[GroupExecutorUI] 右键菜单已注册');
                    return true;
                }
            }
            return false;
        };
        
        // 立即尝试注册
        let registered = registerMenu();
        
        // 如果失败，延迟再试（等待LiteGraph完全加载）
        if (!registered) {
            console.warn('[GroupExecutorUI] 立即注册失败，尝试延迟注册...');
            setTimeout(() => {
                if (!registerMenu()) {
                    console.error('[GroupExecutorUI] 右键菜单注册失败，请检查LiteGraph是否已加载');
                }
            }, 500);
        }
    }
});