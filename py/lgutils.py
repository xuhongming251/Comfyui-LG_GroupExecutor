from server import PromptServer
import os
import json
import threading
import time
import uuid
import asyncio
import random
from aiohttp import web
import aiohttp
import execution
import nodes
from datetime import datetime
from urllib.parse import urlparse

# 尝试导入 requests，如果失败则使用 aiohttp
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("[GroupExecutor] 警告: requests 库未安装，远程服务器功能可能受限")

CATEGORY_TYPE = "🎈LAOGOU/Group"

class AnyType(str):
    """用于表示任意类型的特殊类，在类型比较时总是返回相等"""
    def __eq__(self, _) -> bool:
        return True

    def __ne__(self, __value: object) -> bool:
        return False

any_typ = AnyType("*")

# ============ 后台执行辅助函数 ============

def recursive_add_nodes(node_id, old_output, new_output):
    """从输出节点递归收集所有依赖节点（与前端 queueManager.recursiveAddNodes 逻辑一致）"""
    current_id = str(node_id)
    current_node = old_output.get(current_id)
    
    if not current_node:
        return new_output
    
    if current_id not in new_output:
        new_output[current_id] = current_node
        inputs = current_node.get("inputs", {})
        for input_value in inputs.values():
            if isinstance(input_value, list) and len(input_value) >= 1:
                # input_value 格式: [source_node_id, output_index]
                recursive_add_nodes(input_value[0], old_output, new_output)
    
    return new_output

def filter_prompt_for_nodes(full_prompt, output_node_ids):
    """从完整的 API prompt 中筛选出指定输出节点及其依赖"""
    filtered_prompt = {}
    for node_id in output_node_ids:
        recursive_add_nodes(str(node_id), full_prompt, filtered_prompt)
    return filtered_prompt

class GroupExecutorBackend:
    """后台执行管理器"""
    
    def __init__(self):
        self.running_tasks = {}
        self.task_lock = threading.Lock()
        self.interrupted_prompts = set()  # 记录被中断的 prompt_id
        self._setup_interrupt_handler()
    
    def _setup_interrupt_handler(self):
        """设置中断处理器，监听 execution_interrupted 消息"""
        try:
            server = PromptServer.instance
            backend_instance = self
            
            # 保存原始的 send_sync 方法
            original_send_sync = server.send_sync
            
            def patched_send_sync(event, data, sid=None):
                # 调用原始方法
                original_send_sync(event, data, sid)
                
                # 监听 execution_interrupted 事件
                if event == "execution_interrupted":
                    prompt_id = data.get("prompt_id")
                    if prompt_id:
                        backend_instance.interrupted_prompts.add(prompt_id)
                        # 取消所有后台任务
                        backend_instance._cancel_all_on_interrupt()
            
            server.send_sync = patched_send_sync
        except Exception as e:
            print(f"[GroupExecutor] 设置中断监听器失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _cancel_all_on_interrupt(self):
        """响应全局中断，取消所有正在运行的后台任务"""
        with self.task_lock:
            for node_id, task_info in list(self.running_tasks.items()):
                if task_info.get("status") == "running" and not task_info.get("cancel"):
                    task_info["cancel"] = True
    
    def execute_in_background(self, node_id, execution_list, full_api_prompt):
        """启动后台执行线程
        
        Args:
            node_id: 节点 ID
            execution_list: 执行列表，每项包含 group_name, repeat_count, delay_seconds, output_node_ids
            full_api_prompt: 前端生成的完整 API prompt（已经是正确格式）
        """
        with self.task_lock:
            if node_id in self.running_tasks and self.running_tasks[node_id].get("status") == "running":
                return False
            
            thread = threading.Thread(
                target=self._execute_task,
                args=(node_id, execution_list, full_api_prompt),
                daemon=True
            )
            thread.start()
            
            self.running_tasks[node_id] = {
                "thread": thread,
                "status": "running",
                "cancel": False
            }
            return True
    
    def cancel_task(self, node_id):
        """取消任务"""
        with self.task_lock:
            if node_id in self.running_tasks:
                self.running_tasks[node_id]["cancel"] = True
                
                # 中断当前正在执行的任务
                try:
                    server = PromptServer.instance
                    server.send_sync("interrupt", {})
                except Exception as e:
                    print(f"[GroupExecutor] 发送中断信号失败: {e}")
                
                return True
            return False
    
    def _execute_task(self, node_id, execution_list, full_api_prompt):
        """后台执行任务的核心逻辑
        
        Args:
            node_id: 节点 ID
            execution_list: 执行列表，每项包含 group_name, repeat_count, delay_seconds, output_node_ids, server_id
            full_api_prompt: 前端生成的完整 API prompt
        """
        try:
            # 收集所有组名
            group_names = []
            for exec_item in execution_list:
                group_name = exec_item.get("group_name", "")
                if group_name and group_name != "__delay__":
                    if group_name not in group_names:
                        group_names.append(group_name)
            
            # 检查是否有非本地服务器的执行项
            has_remote_server = any(item.get("server_id") for item in execution_list if item.get("group_name") != "__delay__")
            
            # 为每个组生成独立的 execution_id（不再共享同一个ID）
            group_execution_ids = {}  # 存储每个组对应的 execution_id
            
            for exec_item in execution_list:
                # 检查取消标志
                if self.running_tasks.get(node_id, {}).get("cancel"):
                    print(f"[GroupExecutor] 任务被取消")
                    break
                
                group_name = exec_item.get("group_name", "")
                repeat_count = int(exec_item.get("repeat_count", 1))
                delay_seconds = float(exec_item.get("delay_seconds", 0))
                output_node_ids = exec_item.get("output_node_ids", [])
                server_id = exec_item.get("server_id", None)  # 获取服务器ID
                
                # 处理延迟
                if group_name == "__delay__":
                    if delay_seconds > 0 and not self.running_tasks.get(node_id, {}).get("cancel"):
                        # 分段延迟，以便能快速响应取消
                        delay_steps = int(delay_seconds * 2)  # 每 0.5 秒检查一次
                        for _ in range(delay_steps):
                            if self.running_tasks.get(node_id, {}).get("cancel"):
                                break
                            time.sleep(0.5)
                    continue
                
                if not group_name or not output_node_ids:
                    print(f"[GroupExecutor] 跳过无效执行项: group_name={group_name}, output_node_ids={output_node_ids}")
                    continue
                
                # 为每个组生成独立的 execution_id
                if group_name not in group_execution_ids:
                    # 生成唯一的 execution_id：使用 node_id、组名和时间戳
                    safe_group_name = "".join(c for c in group_name if c.isalnum() or c in ('_', '-'))
                    execution_id = f"exec_{node_id}_{safe_group_name}_{int(time.time() * 1000)}"
                    group_execution_ids[group_name] = execution_id
                    
                    # 注册该组的 execution_id（只对非本地服务器）
                    if has_remote_server and server_id:
                        _group_result_manager.register_execution(execution_id, [group_name], server_id)
                        print(f"[GroupExecutor] 为组 '{group_name}' 生成独立的 execution_id: {execution_id}")
                
                # 获取该组的 execution_id
                execution_id = group_execution_ids[group_name]
                
                # 执行逻辑：repeat_count = 1 时只执行一次（不重复），> 1 时才循环
                if repeat_count == 1:
                    # 只执行一次，不进入循环
                    # 检查取消标志
                    if self.running_tasks.get(node_id, {}).get("cancel"):
                        continue
                    
                    # 从完整 prompt 中筛选出该组需要的节点
                    prompt = filter_prompt_for_nodes(full_api_prompt, output_node_ids)
                    
                    if not prompt:
                        print(f"[GroupExecutor] 筛选 prompt 失败")
                        continue
                    
                    # 设置线程局部存储的组名（用于本地执行时节点获取组名）
                    try:
                        from .trans import set_current_group_name
                        set_current_group_name(group_name)
                    except:
                        pass
                    
                    # 处理随机种子：为每个有 seed 参数的节点生成新的随机值
                    # 同时将组名添加到所有节点的 inputs 中（用于远程执行时节点获取组名）
                    for node_id_str, node_data in prompt.items():
                        if "seed" in node_data.get("inputs", {}):
                            new_seed = random.randint(0, 0xffffffffffffffff)
                            prompt[node_id_str]["inputs"]["seed"] = new_seed
                        # 也处理 noise_seed（某些节点使用这个名称）
                        if "noise_seed" in node_data.get("inputs", {}):
                            new_seed = random.randint(0, 0xffffffffffffffff)
                            prompt[node_id_str]["inputs"]["noise_seed"] = new_seed
                        # 将组名添加到节点的 inputs 中（用于 Remote 节点获取组名）
                        if group_name:
                            prompt[node_id_str]["inputs"]["_execution_group_name"] = group_name
                    
                    # 提交到队列（支持指定服务器）
                    # 如果是本地服务器（server_id 为 None），通过 WebSocket 事件通知前端提交 prompt
                    # 这样可以确保预览图能正确显示
                    if server_id is None:
                        # 本地执行：通过 WebSocket 事件通知前端提交 prompt
                        prompt_id = self._queue_prompt_via_frontend(prompt, output_node_ids)
                    else:
                        # 远程执行：直接提交到远程服务器
                        prompt_id = self._queue_prompt(prompt, server_id)
                        # 非本地服务器执行时，保存状态文件（按组名，覆盖式保存）
                        if prompt_id:
                            try:
                                _group_result_manager.save_status_by_group(
                                    group_name,
                                    server_id,
                                    prompt_id=prompt_id,
                                    started_at=time.time()
                                )
                            except Exception as e:
                                print(f"[GroupExecutor] 保存组状态文件失败: {e}")
                    
                    if prompt_id:
                        # 等待执行完成（返回是否检测到中断）
                        was_interrupted = self._wait_for_completion(prompt_id, node_id, server_id)
                        
                        # 如果等待期间检测到中断，继续下一个组
                        if was_interrupted:
                            continue
                        
                        # 组执行完成，更新状态文件（只对非本地服务器）
                        if server_id is not None:
                            try:
                                _group_result_manager.set_group_result(
                                    execution_id, 
                                    group_name, 
                                    {
                                        "completed": True,
                                        "completed_at": time.time(),
                                        "prompt_id": prompt_id
                                    },
                                    server_id=server_id
                                )
                                # 更新按组名的状态文件（标记为已完成）
                                try:
                                    _group_result_manager.update_status_by_group_completed(
                                        group_name,
                                        prompt_id=prompt_id,
                                        server_id=server_id
                                    )
                                except Exception as e:
                                    print(f"[GroupExecutor] 更新组状态文件失败: {e}")
                            except Exception as e:
                                print(f"[GroupExecutor] 设置组结果失败: {e}")
                    else:
                        print(f"[GroupExecutor] 提交 prompt 失败")
                else:
                    # repeat_count > 1，进入循环重复执行
                    for i in range(repeat_count):
                        # 检查取消标志
                        if self.running_tasks.get(node_id, {}).get("cancel"):
                            break
                        
                        print(f"[GroupExecutor] 执行组 '{group_name}' ({i+1}/{repeat_count})")
                        
                        # 从完整 prompt 中筛选出该组需要的节点
                        prompt = filter_prompt_for_nodes(full_api_prompt, output_node_ids)
                        
                        if not prompt:
                            print(f"[GroupExecutor] 筛选 prompt 失败")
                            continue
                        
                        # 设置线程局部存储的组名（用于本地执行时节点获取组名）
                        try:
                            from .trans import set_current_group_name
                            set_current_group_name(group_name)
                        except:
                            pass
                        
                        # 处理随机种子：为每个有 seed 参数的节点生成新的随机值
                        # 同时将组名添加到所有节点的 inputs 中（用于远程执行时节点获取组名）
                        for node_id_str, node_data in prompt.items():
                            if "seed" in node_data.get("inputs", {}):
                                new_seed = random.randint(0, 0xffffffffffffffff)
                                prompt[node_id_str]["inputs"]["seed"] = new_seed
                            # 也处理 noise_seed（某些节点使用这个名称）
                            if "noise_seed" in node_data.get("inputs", {}):
                                new_seed = random.randint(0, 0xffffffffffffffff)
                                prompt[node_id_str]["inputs"]["noise_seed"] = new_seed
                            # 将组名添加到节点的 inputs 中（用于 Remote 节点获取组名）
                            if group_name:
                                prompt[node_id_str]["inputs"]["_execution_group_name"] = group_name
                        
                        # 提交到队列（支持指定服务器）
                        # 如果是本地服务器（server_id 为 None），通过 WebSocket 事件通知前端提交 prompt
                        # 这样可以确保预览图能正确显示
                        if server_id is None:
                            # 本地执行：通过 WebSocket 事件通知前端提交 prompt
                            prompt_id = self._queue_prompt_via_frontend(prompt, output_node_ids)
                        else:
                            # 远程执行：直接提交到远程服务器
                            prompt_id = self._queue_prompt(prompt, server_id)
                            # 非本地服务器执行时，保存状态文件（按组名，只在第一次执行时保存，覆盖式保存）
                            if prompt_id and i == 0:
                                try:
                                    _group_result_manager.save_status_by_group(
                                        group_name,
                                        server_id,
                                        prompt_id=prompt_id,
                                        started_at=time.time()
                                    )
                                except Exception as e:
                                    print(f"[GroupExecutor] 保存组状态文件失败: {e}")
                        
                        if prompt_id:
                            # 等待执行完成（返回是否检测到中断）
                            was_interrupted = self._wait_for_completion(prompt_id, node_id, server_id)
                            
                            # 如果等待期间检测到中断，立即退出
                            if was_interrupted:
                                break
                            
                            # 组执行完成，更新状态文件（只在最后一次执行时更新，避免重复，只对非本地服务器）
                            if i == repeat_count - 1 and server_id is not None:
                                try:
                                    _group_result_manager.set_group_result(
                                        execution_id, 
                                        group_name, 
                                        {
                                            "completed": True,
                                            "completed_at": time.time(),
                                            "prompt_id": prompt_id,
                                            "repeat_count": repeat_count
                                        },
                                        server_id=server_id
                                    )
                                    # 更新按组名的状态文件（标记为已完成）
                                    try:
                                        _group_result_manager.update_status_by_group_completed(
                                            group_name,
                                            prompt_id=prompt_id,
                                            server_id=server_id
                                        )
                                    except Exception as e:
                                        print(f"[GroupExecutor] 更新组状态文件失败: {e}")
                                except Exception as e:
                                    print(f"[GroupExecutor] 设置组结果失败: {e}")
                        else:
                            print(f"[GroupExecutor] 提交 prompt 失败")
                        
                        # 延迟（支持中断）- 只在重复执行时才有延迟
                        if delay_seconds > 0 and i < repeat_count - 1:
                            if not self.running_tasks.get(node_id, {}).get("cancel"):
                                # 分段延迟，以便能快速响应取消
                                delay_steps = int(delay_seconds * 2)  # 每 0.5 秒检查一次
                                for _ in range(delay_steps):
                                    if self.running_tasks.get(node_id, {}).get("cancel"):
                                        break
                                    time.sleep(0.5)
            
            if self.running_tasks.get(node_id, {}).get("cancel"):
                print(f"[GroupExecutor] 任务已取消")
            else:
                print(f"[GroupExecutor] 任务执行完成")
            
        except Exception as e:
            print(f"[GroupExecutor] 后台执行出错: {e}")
            import traceback
            traceback.print_exc()
        finally:
            with self.task_lock:
                if node_id in self.running_tasks:
                    was_cancelled = self.running_tasks[node_id].get("cancel", False)
                    self.running_tasks[node_id]["status"] = "cancelled" if was_cancelled else "completed"
    
    def _queue_prompt_via_frontend(self, prompt, output_node_ids):
        """通过 WebSocket 事件通知前端提交 prompt（用于本地执行，确保预览图正确显示）
        
        Args:
            prompt: 要执行的 prompt
            output_node_ids: 输出节点ID列表
        
        Returns:
            prompt_id: 如果成功返回 prompt_id，否则返回 None
        """
        try:
            server = PromptServer.instance
            prompt_id = str(uuid.uuid4())
            
            # 通过 WebSocket 事件通知前端提交 prompt
            # 这样前端会使用 api.queuePrompt 来提交，确保预览图能正确显示
            server.send_sync("queue_prompt_backend", {
                "prompt_id": prompt_id,
                "prompt": prompt,
                "output_node_ids": output_node_ids
            }, sid=None)
            
            print(f"[GroupExecutor] 已通过前端提交 prompt: prompt_id={prompt_id}")
            return prompt_id
            
        except Exception as e:
            print(f"[GroupExecutor] 通过前端提交 prompt 失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _queue_prompt(self, prompt, server_id=None):
        """提交 prompt 到队列
        
        Args:
            prompt: 要执行的 prompt
            server_id: 服务器ID，如果为None则使用本地服务器
        
        Returns:
            prompt_id: 如果成功返回 prompt_id，否则返回 None
        """
        try:
            # 如果指定了服务器ID，向远程服务器发送请求
            if server_id:
                server_config = _server_config_manager.get_server(server_id)
                if not server_config:
                    print(f"[GroupExecutor] 未找到服务器配置: {server_id}")
                    return None
                
                # 向远程服务器发送请求
                try:
                    return self._queue_prompt_to_remote(prompt, server_config)
                except Exception as e:
                    # 捕获远程请求异常，打印错误并返回None
                    print(f"[GroupExecutor] 向远程服务器发送请求失败: {e}")
                    return None
            
            # 本地执行
            server = PromptServer.instance
            prompt_id = str(uuid.uuid4())
            
            # 验证 prompt（validate_prompt 是异步函数，需要在事件循环中运行）
            try:
                loop = server.loop
                # 在事件循环中运行异步函数
                valid = asyncio.run_coroutine_threadsafe(
                    execution.validate_prompt(prompt_id, prompt, None),
                    loop
                ).result(timeout=30)
            except Exception as validate_error:
                print(f"[GroupExecutor] Prompt 验证出错: {validate_error}")
                import traceback
                traceback.print_exc()
                return None
            
            if not valid[0]:
                print(f"[GroupExecutor] Prompt 验证失败: {valid[1]}")
                return None
            
            # 提交到队列
            number = server.number
            server.number += 1
            
            # 获取输出节点列表
            outputs_to_execute = list(valid[2])
            
            # 尝试获取所有连接的客户端ID，使用第一个客户端ID来确保执行结果能正确发送到前端
            # 如果无法获取客户端ID，则使用 None（会发送给所有客户端）
            client_id = None
            try:
                # 尝试从服务器获取所有连接的客户端
                # ComfyUI 的 WebSocket 客户端通常存储在 server.web_sockets 或类似的属性中
                if hasattr(server, 'web_sockets') and server.web_sockets:
                    # 获取第一个 WebSocket 连接的客户端ID
                    client_id = list(server.web_sockets.keys())[0] if server.web_sockets else None
                elif hasattr(server, 'clients') and server.clients:
                    # 获取第一个客户端ID
                    client_id = list(server.clients.keys())[0] if server.clients else None
                elif hasattr(server, '_clients') and server._clients:
                    # 尝试另一种方式获取客户端
                    client_id = list(server._clients.keys())[0] if server._clients else None
                elif hasattr(server, 'sockets') and server.sockets:
                    # 尝试从 sockets 获取
                    client_id = list(server.sockets.keys())[0] if server.sockets else None
            except Exception as e:
                # 如果获取客户端ID失败，使用 None（会发送给所有客户端）
                print(f"[GroupExecutor] 获取客户端ID失败，使用 None: {e}")
                client_id = None
            
            # 格式: (number, prompt_id, prompt, client_id, outputs_to_execute, extra_data)
            # 使用获取到的 client_id，如果为 None 则发送给所有连接的客户端
            # 注意：即使 client_id 为 None，ComfyUI 也应该能够将执行结果发送给所有客户端
            
            # 尝试使用 ComfyUI 的内部 API 来提交 prompt，确保执行结果能正确显示
            # 如果无法使用内部 API，则回退到直接使用 prompt_queue.put
            try:
                # 尝试使用 server.queue_prompt 方法（如果存在）
                if hasattr(server, 'queue_prompt'):
                    # 使用内部 API 提交 prompt
                    result = server.queue_prompt(prompt_id, prompt, client_id, outputs_to_execute)
                    print(f"[GroupExecutor] 通过内部 API 提交 prompt: prompt_id={prompt_id}, client_id={client_id}")
                    return prompt_id
            except Exception as api_error:
                # 如果内部 API 不可用，使用直接方式
                print(f"[GroupExecutor] 内部 API 不可用，使用直接方式: {api_error}")
            
            # 直接使用 prompt_queue.put 提交
            server.prompt_queue.put((number, prompt_id, prompt, client_id, outputs_to_execute, {}))
            
            print(f"[GroupExecutor] 已提交 prompt 到队列: prompt_id={prompt_id}, client_id={client_id}")
            
            return prompt_id
            
        except Exception as e:
            print(f"[GroupExecutor] 提交队列失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _queue_prompt_to_remote(self, prompt, server_config):
        """向远程服务器发送 prompt 请求
        
        Args:
            prompt: 要执行的 prompt
            server_config: 服务器配置字典，包含 url, auth_token 等
        
        Returns:
            prompt_id: 如果成功返回 prompt_id，否则返回 None
        """
        if not HAS_REQUESTS:
            print(f"[GroupExecutor] 错误: requests 库未安装，无法向远程服务器发送请求")
            return None
        
        try:
            
            url = server_config.get("url", "").rstrip('/')
            auth_token = server_config.get("auth_token")
            
            if not url:
                print(f"[GroupExecutor] 服务器URL为空")
                return None
            
            # 准备请求头
            headers = {"Content-Type": "application/json"}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            # 发送 prompt 到远程服务器
            prompt_url = f"{url}/prompt"
            
            # 使用 requests 同步发送（在后台线程中运行）
            response = requests.post(
                prompt_url,
                json={"prompt": prompt},
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                prompt_id = result.get("prompt_id")
                if prompt_id:
                    print(f"[GroupExecutor] 已向远程服务器 {server_config.get('name', url)} 提交 prompt: {prompt_id}")
                    return prompt_id
                else:
                    error_msg = f"远程服务器返回的响应中没有 prompt_id: {response.text[:200]}"
                    print(f"[GroupExecutor] {error_msg}")
                    raise Exception(error_msg)
            else:
                error_msg = f"服务器错误 {response.status_code}: {response.text[:200]}"
                print(f"[GroupExecutor] 远程服务器返回错误: {error_msg}")
                raise Exception(error_msg)
                
        except requests.exceptions.RequestException as e:
            # 捕获网络请求异常
            error_msg = f"网络请求失败: {str(e)}"
            print(f"[GroupExecutor] {error_msg}")
            import traceback
            traceback.print_exc()
            raise Exception(error_msg)
        except Exception as e:
            # 捕获其他异常（包括我们抛出的异常）
            print(f"[GroupExecutor] 向远程服务器发送请求失败: {e}")
            import traceback
            traceback.print_exc()
            # 重新抛出异常，让调用者处理
            raise
    
    def _wait_for_completion(self, prompt_id, node_id, server_id=None):
        """等待 prompt 执行完成，同时响应取消请求
        
        Args:
            prompt_id: prompt ID
            node_id: 节点 ID
            server_id: 服务器ID，如果为None则使用本地服务器
        
        返回: True 如果检测到中断，False 正常完成
        """
        try:
            # 如果指定了服务器ID，使用远程等待逻辑
            if server_id:
                return self._wait_for_remote_completion(prompt_id, node_id, server_id)
            
            # 本地执行等待逻辑
            server = PromptServer.instance
            
            while True:
                # 检查这个 prompt 是否被中断
                if prompt_id in self.interrupted_prompts:
                    # 设置任务取消标志
                    with self.task_lock:
                        if node_id in self.running_tasks:
                            self.running_tasks[node_id]["cancel"] = True
                    # 从中断集合中移除
                    self.interrupted_prompts.discard(prompt_id)
                    return True  # 返回中断状态
                
                # 检查是否被取消
                if self.running_tasks.get(node_id, {}).get("cancel"):
                    # 从队列中删除这个 prompt（如果还在队列中）
                    try:
                        def should_delete(item):
                            return len(item) >= 2 and item[1] == prompt_id
                        server.prompt_queue.delete_queue_item(should_delete)
                    except Exception as del_error:
                        print(f"[GroupExecutor] 删除队列项时出错: {del_error}")
                    return True  # 返回中断状态
                
                # 检查是否在历史记录中（表示已完成）
                if prompt_id in server.prompt_queue.history:
                    # 检查是否是因为中断而完成的
                    if prompt_id in self.interrupted_prompts:
                        self.interrupted_prompts.discard(prompt_id)
                        return True
                    return False  # 正常完成
                
                # 检查是否还在队列中
                running, pending = server.prompt_queue.get_current_queue()
                
                in_queue = False
                for item in running:
                    if len(item) >= 2 and item[1] == prompt_id:
                        in_queue = True
                        break
                
                if not in_queue:
                    for item in pending:
                        if len(item) >= 2 and item[1] == prompt_id:
                            in_queue = True
                            break
                
                if not in_queue and prompt_id not in server.prompt_queue.history:
                    # 可能已经执行完成但还没更新历史记录，再等一会
                    time.sleep(0.5)
                    # 再次检查
                    if prompt_id in server.prompt_queue.history:
                        # 检查是否是因为中断完成的
                        if prompt_id in self.interrupted_prompts:
                            self.interrupted_prompts.discard(prompt_id)
                            return True
                        return False
                    if not in_queue:
                        return False
                
                time.sleep(0.5)
                
        except Exception as e:
            print(f"[GroupExecutor] 等待执行完成时出错: {e}")
            return False
    
    def _wait_for_remote_completion(self, prompt_id, node_id, server_id):
        """等待远程服务器上的 prompt 执行完成
        
        Args:
            prompt_id: prompt ID
            node_id: 节点 ID
            server_id: 服务器ID
        
        返回: True 如果检测到中断，False 正常完成
        """
        if not HAS_REQUESTS:
            print(f"[GroupExecutor] 错误: requests 库未安装，无法检查远程服务器状态")
            return False
        
        try:
            
            server_config = _server_config_manager.get_server(server_id)
            if not server_config:
                print(f"[GroupExecutor] 未找到服务器配置: {server_id}")
                return False
            
            url = server_config.get("url", "").rstrip('/')
            auth_token = server_config.get("auth_token")
            
            if not url:
                print(f"[GroupExecutor] 服务器URL为空")
                return False
            
            # 准备请求头
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            queue_url = f"{url}/queue"
            
            while True:
                # 检查是否被取消
                if self.running_tasks.get(node_id, {}).get("cancel"):
                    # 尝试中断远程执行
                    try:
                        interrupt_url = f"{url}/interrupt"
                        requests.post(interrupt_url, headers=headers, timeout=5)
                    except:
                        pass
                    return True
                
                # 检查远程队列状态
                try:
                    response = requests.get(queue_url, headers=headers, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        queue_running = data.get("queue_running", [])
                        queue_pending = data.get("queue_pending", [])
                        queue_history = data.get("queue_history", [])
                        
                        # 检查是否在运行或等待队列中
                        in_queue = False
                        for item in queue_running:
                            if isinstance(item, list) and len(item) >= 2 and item[1] == prompt_id:
                                in_queue = True
                                break
                        
                        if not in_queue:
                            for item in queue_pending:
                                if isinstance(item, list) and len(item) >= 2 and item[1] == prompt_id:
                                    in_queue = True
                                    break
                        
                        # 检查是否在历史记录中
                        in_history = False
                        for item in queue_history:
                            if isinstance(item, list) and len(item) >= 2 and item[1] == prompt_id:
                                in_history = True
                                break
                        
                        if in_history:
                            # 已完成
                            return False
                        
                        if not in_queue and not in_history:
                            # 可能已完成但历史记录还没更新，再等一会
                            time.sleep(0.5)
                            # 再次检查
                            response = requests.get(queue_url, headers=headers, timeout=5)
                            if response.status_code == 200:
                                data = response.json()
                                queue_history = data.get("queue_history", [])
                                for item in queue_history:
                                    if isinstance(item, list) and len(item) >= 2 and item[1] == prompt_id:
                                        return False
                            # 如果还是不在队列中，可能已完成
                            return False
                except Exception as e:
                    # 捕获所有异常（包括 requests.exceptions.RequestException）
                    print(f"[GroupExecutor] 检查远程队列状态失败: {e}")
                    # 继续等待
                
                time.sleep(0.5)
                
        except Exception as e:
            print(f"[GroupExecutor] 等待远程执行完成时出错: {e}")
            import traceback
            traceback.print_exc()
            return False

# 全局后台执行器实例
_backend_executor = GroupExecutorBackend()

# ============ 组执行结果管理器（基于文件系统） ============

# 状态文件存储目录
try:
    import folder_paths
    STATUS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status")
except:
    STATUS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status")
os.makedirs(STATUS_DIR, exist_ok=True)

class GroupResultManager:
    """基于文件系统的组执行结果管理器"""
    
    def __init__(self, status_dir=None):
        self.status_dir = status_dir or STATUS_DIR
        self.lock = threading.Lock()
        os.makedirs(self.status_dir, exist_ok=True)
        # 远程结果文件存储目录
        self.remote_results_dir = os.path.join(self.status_dir, "remote_results")
        os.makedirs(self.remote_results_dir, exist_ok=True)
    
    def _get_status_file(self, execution_id):
        """获取状态文件路径"""
        # 使用安全的文件名（移除特殊字符）
        safe_id = "".join(c for c in execution_id if c.isalnum() or c in ('_', '-'))
        return os.path.join(self.status_dir, f"{safe_id}.json")
    
    def _get_status_file_by_group(self, group_name):
        """按组名获取状态文件路径（用于非本地服务器执行）"""
        # 使用安全的文件名（移除特殊字符）
        safe_name = "".join(c for c in group_name if c.isalnum() or c in ('_', '-', ' '))
        safe_name = safe_name.replace(' ', '_')  # 将空格替换为下划线
        return os.path.join(self.status_dir, f"{safe_name}.json")
    
    def _clear_group_result_files(self, group_name):
        """清除该组的所有历史结果文件（包括图像和文本结果文件）
        
        Args:
            group_name: 组名
        """
        try:
            # 生成安全的组名（与文件命名规则一致）
            safe_group_name = "".join(c for c in group_name if c.isalnum() or c in ('_', '-', ' '))
            safe_group_name = safe_group_name.replace(' ', '_')
            
            deleted_count = 0
            
            # 清除图像结果文件（在 remote_results 目录中）
            if os.path.exists(self.remote_results_dir):
                for filename in os.listdir(self.remote_results_dir):
                    # 匹配格式：{group_name}_{link_id}_{index}.png 或 {group_name}_{link_id}_{index}_preview.jpg
                    if filename.startswith(f"{safe_group_name}_") and (filename.endswith('.png') or filename.endswith('_preview.jpg')):
                        file_path = os.path.join(self.remote_results_dir, filename)
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f"[GroupResultManager] 删除图像结果文件失败: {file_path}, 错误: {e}")
            
            # 清除文本结果文件（在 status_dir 目录中，格式：{group_name}_{link_id}.json）
            if os.path.exists(self.status_dir):
                for filename in os.listdir(self.status_dir):
                    # 匹配格式：{group_name}_{link_id}.json（排除组状态文件本身，即 {group_name}.json）
                    if filename.startswith(f"{safe_group_name}_") and filename.endswith('.json') and filename != f"{safe_group_name}.json":
                        file_path = os.path.join(self.status_dir, filename)
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f"[GroupResultManager] 删除文本结果文件失败: {file_path}, 错误: {e}")
            
            if deleted_count > 0:
                print(f"[GroupResultManager] 已清除组 '{group_name}' 的 {deleted_count} 个历史结果文件（包括图像和文本）")
        except Exception as e:
            print(f"[GroupResultManager] 清除组历史结果文件失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_status(self, execution_id):
        """从组名配置文件中加载状态（通过查找包含该execution_id的组名配置文件）"""
        # 从组名配置文件中查找包含该execution_id的文件
        if not os.path.exists(self.status_dir):
            return None
        
        try:
            for filename in os.listdir(self.status_dir):
                if filename.endswith('.json') and not filename.endswith('.tmp'):
                    # 跳过exec_ui开头的文件（不再使用）
                    if filename.startswith('exec_ui_'):
                        continue
                    
                    status_file = os.path.join(self.status_dir, filename)
                    try:
                        with open(status_file, 'r', encoding='utf-8') as f:
                            status = json.load(f)
                            if status.get("execution_id") == execution_id:
                                # 找到匹配的组名配置文件，返回其groups信息
                                return {
                                    "execution_id": execution_id,
                                    "groups": status.get("groups", {}),
                                    "completed": status.get("completed", False),
                                    "completed_at": status.get("completed_at"),
                                    "timestamp": status.get("timestamp", 0)
                                }
                    except:
                        continue
        except Exception as e:
            print(f"[GroupResultManager] 从组名配置文件读取状态失败: {e}")
        
        return None
    
    def _save_status(self, execution_id, status_data):
        """保存状态到文件"""
        status_file = self._get_status_file(execution_id)
        try:
            # 使用临时文件确保原子性写入
            temp_file = status_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)
            # 原子性替换
            if os.path.exists(status_file):
                os.remove(status_file)
            os.rename(temp_file, status_file)
            return True
        except Exception as e:
            print(f"[GroupResultManager] 保存状态文件失败: {e}")
            # 清理临时文件
            temp_file = status_file + ".tmp"
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    print(f"[GroupResultManager] 删除临时文件失败: {e}")
            return False
    
    def _is_local_server(self, server_id):
        """检查是否是本地服务器"""
        return server_id is None or server_id == "local" or server_id == ""
    
    def register_execution(self, execution_id, group_names, server_id=None):
        """注册一个执行任务，为每个组记录独立的 execution_id（只对非本地服务器保存到组名配置文件）
        
        Args:
            execution_id: 执行ID（现在每个组有独立的ID）
            group_names: 组名列表（通常只包含一个组名）
            server_id: 服务器ID，如果为None或"local"（本地服务器）则不保存配置文件
        """
        # 只对非本地服务器保存配置文件
        if self._is_local_server(server_id):
            return
        
        with self.lock:
            # 为每个组保存独立的 execution_id
            for group_name in group_names:
                group_status_file = self._get_status_file_by_group(group_name)
                group_status_data = None
                if os.path.exists(group_status_file):
                    try:
                        with open(group_status_file, 'r', encoding='utf-8') as f:
                            group_status_data = json.load(f)
                    except:
                        pass
                
                # 构建优化后的组状态数据（只包含单个组的信息）
                merged_group_data = {
                    "group_name": group_name,
                    "execution_id": execution_id,  # 每个组有独立的 execution_id
                    "completed": False,  # 初始状态为未完成
                    "created_at": time.time()
                }
                
                # 保留组名配置文件中的其他字段
                if group_status_data:
                    if "server_id" in group_status_data:
                        merged_group_data["server_id"] = group_status_data["server_id"]
                    if "started_at" in group_status_data:
                        merged_group_data["started_at"] = group_status_data["started_at"]
                    if "prompt_id" in group_status_data:
                        merged_group_data["prompt_id"] = group_status_data["prompt_id"]
                    if "completed_at" in group_status_data:
                        merged_group_data["completed_at"] = group_status_data["completed_at"]
                    if "completed" in group_status_data:
                        merged_group_data["completed"] = group_status_data["completed"]
                
                # 保存合并后的组状态文件
                try:
                    temp_file = group_status_file + ".tmp"
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(merged_group_data, f, ensure_ascii=False, indent=2)
                    if os.path.exists(group_status_file):
                        os.remove(group_status_file)
                    os.rename(temp_file, group_status_file)
                except Exception as e:
                    print(f"[GroupResultManager] 保存合并后的组状态文件失败 ({group_name}): {e}")
    
    def set_group_result(self, execution_id, group_name, result_data, server_id=None):
        """设置某个组的执行结果（只对非本地服务器保存到组名配置文件）
        
        Args:
            execution_id: 执行ID
            group_name: 组名
            result_data: 结果数据
            server_id: 服务器ID，如果为None或"local"（本地服务器）则不保存配置文件
        """
        # 只对非本地服务器保存配置文件
        if self._is_local_server(server_id):
            return True
        
        with self.lock:
            # 直接更新当前组的配置文件（优化后的结构，只包含单个组的信息）
            group_status_file = self._get_status_file_by_group(group_name)
            group_status_data = None
            if os.path.exists(group_status_file):
                try:
                    with open(group_status_file, 'r', encoding='utf-8') as f:
                        group_status_data = json.load(f)
                except:
                    pass
            
            # 构建优化后的组状态数据（只包含单个组的信息，去掉groups字段）
            merged_group_data = {
                "group_name": group_name,
                "execution_id": execution_id,
                "completed": True,  # 当前组已完成
                "completed_at": result_data.get("completed_at", time.time()),
                "created_at": time.time()
            }
            
            # 保留组名配置文件中的其他字段（如server_id, prompt_id等）
            if group_status_data:
                if "server_id" in group_status_data:
                    merged_group_data["server_id"] = group_status_data["server_id"]
                if "started_at" in group_status_data:
                    merged_group_data["started_at"] = group_status_data["started_at"]
                if "created_at" in group_status_data:
                    merged_group_data["created_at"] = group_status_data["created_at"]
            
            # 如果result_data中有prompt_id，使用它；否则保留现有的
            if result_data.get("prompt_id"):
                merged_group_data["prompt_id"] = result_data["prompt_id"]
            elif group_status_data and group_status_data.get("prompt_id"):
                merged_group_data["prompt_id"] = group_status_data["prompt_id"]
            
            # 保存合并后的组状态文件
            try:
                temp_file = group_status_file + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(merged_group_data, f, ensure_ascii=False, indent=2)
                if os.path.exists(group_status_file):
                    os.remove(group_status_file)
                os.rename(temp_file, group_status_file)
                print(f"[GroupResultManager] 已更新组状态文件: {group_status_file}")
            except Exception as e:
                print(f"[GroupResultManager] 保存合并后的组状态文件失败 ({group_name}): {e}")
            
            print(f"[GroupResultManager] 组 '{group_name}' 完成: {execution_id}")
            return True
    
    def get_group_result(self, execution_id=None, group_name=None):
        """获取某个组的执行结果（从组名配置文件直接读取）
        
        Args:
            execution_id: 执行ID（可选，如果提供则验证是否匹配）
            group_name: 组名（必需）
        """
        if not group_name:
            return None
            
        with self.lock:
            # 直接从组名配置文件读取
            status_file = self._get_status_file_by_group(group_name)
            if not os.path.exists(status_file):
                return None
            
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    status_data = json.load(f)
                
                # 如果提供了 execution_id，检查是否匹配
                if execution_id and status_data.get("execution_id") != execution_id:
                    return None
                
                # 检查是否已完成
                if status_data.get("completed", False):
                    # 返回结果数据（包含 completed, completed_at, prompt_id, execution_id 等信息）
                    return {
                        "completed": status_data.get("completed", False),
                        "completed_at": status_data.get("completed_at"),
                        "prompt_id": status_data.get("prompt_id"),
                        "execution_id": status_data.get("execution_id")  # 返回该组的 execution_id
                    }
            except:
                pass
            
            return None
    
    def get_group_execution_id(self, group_name):
        """获取某个组的 execution_id（从组名配置文件读取）"""
        with self.lock:
            status_file = self._get_status_file_by_group(group_name)
            if not os.path.exists(status_file):
                return None
            
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    status_data = json.load(f)
                return status_data.get("execution_id")
            except:
                pass
            
            return None
    
    def get_all_results(self, execution_id):
        """获取所有组的执行结果（遍历所有包含相同execution_id的组名配置文件）"""
        with self.lock:
            if not os.path.exists(self.status_dir):
                return None
            
            results = {}
            try:
                # 遍历所有组名配置文件
                for filename in os.listdir(self.status_dir):
                    if filename.endswith('.json') and not filename.endswith('.tmp'):
                        # 跳过exec_ui开头的文件（不再使用）
                        if filename.startswith('exec_ui_'):
                            continue
                        
                        status_file = os.path.join(self.status_dir, filename)
                        try:
                            with open(status_file, 'r', encoding='utf-8') as f:
                                status_data = json.load(f)
                            
                            # 检查 execution_id 是否匹配，且已完成
                            if status_data.get("execution_id") == execution_id and status_data.get("completed", False):
                                group_name = status_data.get("group_name")
                                if group_name:
                                    # 返回结果数据
                                    results[group_name] = {
                                        "completed": status_data.get("completed", False),
                                        "completed_at": status_data.get("completed_at"),
                                        "prompt_id": status_data.get("prompt_id")
                                    }
                        except:
                            continue
            except Exception as e:
                print(f"[GroupResultManager] 获取所有结果失败: {e}")
            
            return results if results else None
    
    def is_completed(self, execution_id):
        """检查执行是否完成（检查所有包含相同execution_id的组是否都完成）"""
        with self.lock:
            if not os.path.exists(self.status_dir):
                return False
            
            # 查找所有包含相同execution_id的组名配置文件
            group_files = []
            try:
                for filename in os.listdir(self.status_dir):
                    if filename.endswith('.json') and not filename.endswith('.tmp'):
                        if filename.startswith('exec_ui_'):
                            continue
                        
                        status_file = os.path.join(self.status_dir, filename)
                        try:
                            with open(status_file, 'r', encoding='utf-8') as f:
                                status_data = json.load(f)
                            if status_data.get("execution_id") == execution_id:
                                group_files.append(status_data)
                        except:
                            continue
            except:
                return False
            
            if not group_files:
                return False
            
            # 检查是否所有组都已完成
            return all(group_data.get("completed", False) for group_data in group_files)
    
    def wait_for_completion(self, execution_id, timeout=None):
        """等待执行完成（通过轮询文件）"""
        start_time = time.time()
        check_interval = 0.5  # 每0.5秒检查一次
        
        while True:
            if self.is_completed(execution_id):
                return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            time.sleep(check_interval)
    
    def clear_execution(self, execution_id):
        """清除执行结果（删除状态文件）"""
        with self.lock:
            status_file = self._get_status_file(execution_id)
            if os.path.exists(status_file):
                try:
                    os.remove(status_file)
                    return True
                except Exception as e:
                    print(f"[GroupResultManager] 删除状态文件失败: {e}")
                    return False
            return False
    
    def get_latest_execution_id(self):
        """获取最新的execution_id（按时间戳排序，从组名配置文件中查找）"""
        with self.lock:
            if not os.path.exists(self.status_dir):
                return None
            
            latest_id = None
            latest_time = 0
            
            try:
                for filename in os.listdir(self.status_dir):
                    if filename.endswith('.json') and not filename.endswith('.tmp'):
                        # 跳过exec_ui开头的文件（不再使用）
                        if filename.startswith('exec_ui_'):
                            continue
                        
                        # 从组名配置文件中查找
                        status_file = os.path.join(self.status_dir, filename)
                        try:
                            with open(status_file, 'r', encoding='utf-8') as f:
                                status = json.load(f)
                                if "execution_id" in status:
                                    # 使用 created_at 字段，如果没有则使用 timestamp（向后兼容）
                                    created_at = status.get("created_at", status.get("timestamp", 0))
                                    if created_at > latest_time:
                                        latest_time = created_at
                                        latest_id = status.get("execution_id")
                        except:
                            continue
            except Exception as e:
                print(f"[GroupResultManager] 获取最新执行ID失败: {e}")
            
            return latest_id
    
    def save_status_by_group(self, group_name, server_id, prompt_id=None, started_at=None, execution_id=None, groups=None):
        """按组名保存状态文件（覆盖式保存，用于非本地服务器执行）
        
        Args:
            group_name: 组名
            server_id: 服务器ID，如果为None或"local"（本地服务器）则不保存配置文件
            prompt_id: prompt ID（可选）
            started_at: 开始时间（可选，默认为当前时间）
            execution_id: 执行ID（可选，用于合并execution_id相关信息）
            groups: 组信息字典（可选，用于合并execution_id相关信息）
        """
        # 只对非本地服务器保存配置文件
        if self._is_local_server(server_id):
            return False
        
        with self.lock:
            status_file = self._get_status_file_by_group(group_name)
            
            # 尝试加载现有状态，以便合并数据
            existing_data = None
            if os.path.exists(status_file):
                try:
                    with open(status_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except:
                    pass
            
            # 构建状态数据，合并现有数据（优化后的结构，只包含单个组的信息）
            # 如果提供了 prompt_id，表示新任务开始，completed 应该为 False
            # 如果没有提供 prompt_id，则从现有数据中继承 completed 状态
            if prompt_id:
                # 新任务开始，设置为未完成
                completed_status = False
                completed_at_value = None
                # 新任务开始时，清除该组的所有历史结果文件
                self._clear_group_result_files(group_name)
            else:
                # 没有提供新的 prompt_id，从现有数据继承
                completed_status = existing_data.get("completed", False) if existing_data else False
                completed_at_value = existing_data.get("completed_at") if existing_data else None
            
            # 计算 started_at 的值
            started_at_value = started_at if started_at else (existing_data.get("started_at") if existing_data else time.time())
            
            status_data = {
                "group_name": group_name,
                "server_id": server_id,
                "completed": completed_status,
                "started_at": started_at_value,
                "completed_at": completed_at_value,
                "prompt_id": prompt_id if prompt_id else (existing_data.get("prompt_id") if existing_data else None),
                "created_at": started_at_value  # created_at 应该使用 started_at 的值（组配置启动时间）
            }
            
            # 如果提供了execution_id，合并到状态数据中
            if execution_id:
                status_data["execution_id"] = execution_id
            elif existing_data and "execution_id" in existing_data:
                status_data["execution_id"] = existing_data["execution_id"]
            
            try:
                # 使用临时文件确保原子性写入
                temp_file = status_file + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(status_data, f, ensure_ascii=False, indent=2)
                # 原子性替换（覆盖式保存）
                if os.path.exists(status_file):
                    os.remove(status_file)
                os.rename(temp_file, status_file)
                print(f"[GroupResultManager] 保存组状态文件: {status_file}")
                return True
            except Exception as e:
                print(f"[GroupResultManager] 保存组状态文件失败: {e}")
                # 清理临时文件
                temp_file = status_file + ".tmp"
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception as e:
                        print(f"[GroupResultManager] 删除临时文件失败: {e}")
                return False
    
    def update_status_by_group_completed(self, group_name, prompt_id=None, server_id=None):
        """更新按组名的状态文件，标记为已完成（只对非本地服务器）
        
        Args:
            group_name: 组名
            prompt_id: prompt ID（可选）
            server_id: 服务器ID，如果为None或"local"（本地服务器）则不更新配置文件
        """
        # 只对非本地服务器更新配置文件
        if self._is_local_server(server_id):
            return False
        
        with self.lock:
            status_file = self._get_status_file_by_group(group_name)
            if not os.path.exists(status_file):
                print(f"[GroupResultManager] 状态文件不存在: {status_file}")
                return False
            
            try:
                # 读取现有状态
                with open(status_file, 'r', encoding='utf-8') as f:
                    status_data = json.load(f)
                
                # 获取 execution_id
                execution_id = status_data.get("execution_id")
                
                # 更新状态（优化后的结构，只包含单个组的信息）
                status_data["completed"] = True
                status_data["completed_at"] = time.time()
                if prompt_id:
                    status_data["prompt_id"] = prompt_id
                
                # 移除旧的groups字段（如果存在）
                if "groups" in status_data:
                    del status_data["groups"]
                
                # 保存状态
                temp_file = status_file + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(status_data, f, ensure_ascii=False, indent=2)
                # 原子性替换
                if os.path.exists(status_file):
                    os.remove(status_file)
                os.rename(temp_file, status_file)
                print(f"[GroupResultManager] 更新组状态文件（已完成）: {status_file}")
                
                # 在组任务完成时，根据 execution_id 和组名，确保图片和蒙版已保存到文件中
                if execution_id:
                    self._ensure_images_saved_for_group(group_name, execution_id)
                
                return True
            except Exception as e:
                print(f"[GroupResultManager] 更新组状态文件失败: {e}")
                import traceback
                traceback.print_exc()
                # 清理临时文件
                temp_file = status_file + ".tmp"
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                return False
    
    def _ensure_images_saved_for_group(self, group_name, execution_id):
        """在组任务完成时，根据 execution_id 和组名，确保图片和蒙版已保存到文件中
        
        Args:
            group_name: 组名
            execution_id: 执行ID
        """
        try:
            # 生成安全的组名（与文件命名规则一致）
            safe_group_name = "".join(c for c in group_name if c.isalnum() or c in ('_', '-', ' '))
            safe_group_name = safe_group_name.replace(' ', '_')
            
            # 生成安全的 execution_id（用于文件名）
            safe_execution_id = "".join(c for c in execution_id if c.isalnum() or c in ('_', '-'))
            
            # 检查 remote_results 目录中是否存在该组的图片文件
            if not os.path.exists(self.remote_results_dir):
                print(f"[GroupResultManager] 远程结果目录不存在: {self.remote_results_dir}")
                return
            
            # 查找所有匹配的图片文件（格式：{group_name}_{link_id}_{index}.png）
            image_files = []
            for filename in os.listdir(self.remote_results_dir):
                # 匹配格式：{group_name}_{link_id}_{index}.png
                if filename.startswith(f"{safe_group_name}_") and filename.endswith('.png') and not filename.endswith('_preview.jpg'):
                    image_files.append(filename)
            
            if image_files:
                print(f"[GroupResultManager] 组 '{group_name}' (execution_id={execution_id}) 完成，已找到 {len(image_files)} 个图片文件")
                # 图片文件已经在执行过程中由 LG_RemoteImageSenderPlus 保存
                # 这里只需要确认文件存在即可
                for filename in image_files:
                    file_path = os.path.join(self.remote_results_dir, filename)
                    if os.path.exists(file_path):
                        print(f"[GroupResultManager] 确认图片文件已保存: {filename}")
                    else:
                        print(f"[GroupResultManager] 警告: 图片文件不存在: {filename}")
            else:
                print(f"[GroupResultManager] 组 '{group_name}' (execution_id={execution_id}) 完成，但未找到图片文件")
        except Exception as e:
            print(f"[GroupResultManager] 确保图片保存失败: {e}")
            import traceback
            traceback.print_exc()
    
    def load_status_by_group(self, group_name):
        """按组名加载状态文件
        
        Args:
            group_name: 组名
        
        Returns:
            dict: 状态数据，如果不存在返回 None
        """
        with self.lock:
            status_file = self._get_status_file_by_group(group_name)
            if not os.path.exists(status_file):
                return None
            
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[GroupResultManager] 读取组状态文件失败: {e}")
                return None
    
    def is_group_completed(self, group_name):
        """检查组任务是否完成（按组名读取状态文件）
        
        Args:
            group_name: 组名
        
        Returns:
            bool: 如果完成返回 True，如果未完成或状态文件不存在返回 False
        """
        status = self.load_status_by_group(group_name)
        if status is None:
            return False
        return status.get("completed", False)

# 全局结果管理器实例
_group_result_manager = GroupResultManager()

# ============ 节点定义 ============

class GroupExecutorSingle:
    """单组执行节点"""
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "group_name": ("STRING", {"default": "", "multiline": False}),
                "repeat_count": ("INT", {"default": 1, "min": 1, "max": 100, "step": 1}),
                "delay_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 60.0, "step": 0.1}),
            },
            "optional": {
                "signal": ("SIGNAL",),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID"
            }
        }
    
    RETURN_TYPES = ("SIGNAL",)
    FUNCTION = "execute_group"
    CATEGORY = CATEGORY_TYPE

    def execute_group(self, group_name, repeat_count, delay_seconds, signal=None, unique_id=None):
        try:
            current_execution = {
                "group_name": group_name,
                "repeat_count": repeat_count,
                "delay_seconds": delay_seconds
            }
            
            # 如果有信号输入
            if signal is not None:
                if isinstance(signal, list):
                    signal.append(current_execution)
                    return (signal,)
                else:
                    result = [signal, current_execution]
                    return (result,)

            return (current_execution,)

        except Exception as e:
            print(f"[GroupExecutorSingle {unique_id}] 错误: {e}")
            import traceback
            traceback.print_exc()
            return ({"error": str(e)},)

class GroupExecutorSender:
    """执行信号发送节点"""
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "signal": ("SIGNAL",),
                "execution_mode": (["前端执行", "后台执行"], {"default": "后台执行"}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            }
        }
    
    RETURN_TYPES = () 
    FUNCTION = "execute"
    CATEGORY = CATEGORY_TYPE
    OUTPUT_NODE = True

    def execute(self, signal, execution_mode, unique_id=None, prompt=None, extra_pnginfo=None):
        try:
            if not signal:
                raise ValueError("没有收到执行信号")

            execution_list = signal if isinstance(signal, list) else [signal]

            if execution_mode == "后台执行":
                # 后台执行模式：通知前端生成 API prompt 并发送给后端
                PromptServer.instance.send_sync(
                    "execute_group_list_backend", {
                        "node_id": unique_id,
                        "execution_list": execution_list
                    }
                )
                
            else:
                # 前端执行模式（原有方式）
                PromptServer.instance.send_sync(
                    "execute_group_list", {
                        "node_id": unique_id,
                        "execution_list": execution_list
                    }
                )
            
            return ()  

        except Exception as e:
            print(f"[GroupExecutor] 执行错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return ()

class GroupExecutorRepeater:
    """执行列表重复处理节点"""
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "signal": ("SIGNAL",),
                "repeat_count": ("INT", {
                    "default": 1, 
                    "min": 1, 
                    "max": 100,
                    "step": 1
                }),
                "group_delay": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 300.0,
                    "step": 0.1
                }),
            },
        }
    
    RETURN_TYPES = ("SIGNAL",)
    FUNCTION = "repeat"
    CATEGORY = CATEGORY_TYPE

    def repeat(self, signal, repeat_count, group_delay):
        try:
            if not signal:
                raise ValueError("没有收到执行信号")

            execution_list = signal if isinstance(signal, list) else [signal]

            # repeat_count = 1 表示不重复，只返回原始列表
            # repeat_count > 1 表示重复执行
            if repeat_count == 1:
                # 不重复，直接返回原始列表
                return (execution_list,)
            
            # repeat_count > 1，进入循环重复
            repeated_list = []
            for i in range(repeat_count):
                repeated_list.extend(execution_list)

                # 在重复之间添加延迟（最后一次不需要延迟）
                if i < repeat_count - 1:
                    repeated_list.append({
                        "group_name": "__delay__",
                        "repeat_count": 1,
                        "delay_seconds": group_delay
                    })
            
            return (repeated_list,)

        except Exception as e:
            print(f"重复处理错误: {str(e)}")
            return ([],)

class GroupExecutorWaitAll:
    """等待所有组异步运行结果的节点"""
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "timeout_seconds": ("FLOAT", {"default": 300.0, "min": 0.0, "max": 3600.0, "step": 1.0}),
            },
            "optional": {
                "signal": ("SIGNAL",),
                "any_input": ("*",),   # 👈 任意类型输入
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            }
        }
    
    RETURN_TYPES = ("SIGNAL", "BOOLEAN")
    RETURN_NAMES = ("signal", "completed")
    FUNCTION = "wait_all"
    CATEGORY = CATEGORY_TYPE
    OUTPUT_NODE = True  # 标记为输出节点，确保在组中单独存在时也能被执行
    
    @classmethod
    def _get_group_list(cls, unique_id=None, prompt=None, extra_pnginfo=None):
        """从节点的配置中获取组名列表"""
        group_list = []
        if prompt and unique_id:
            # 从prompt中获取当前节点的配置
            node_data = prompt.get(str(unique_id), {})
            node_inputs = node_data.get("inputs", {})
            
            # 尝试从properties中获取组名列表
            # 前端会将组名列表存储在properties中
            if "group_names" in node_inputs:
                group_names_str = node_inputs.get("group_names", "")
                if group_names_str:
                    group_list = [name.strip() for name in group_names_str.split('\n') if name.strip()]
        
        # 如果从prompt中获取不到，尝试从extra_pnginfo中获取
        if not group_list and extra_pnginfo:
            workflow = extra_pnginfo.get("workflow", {})
            nodes = workflow.get("nodes", [])
            for node in nodes:
                node_id = node.get("id")
                # 兼容字符串和整数类型的ID
                if str(node_id) == str(unique_id) or node_id == unique_id:
                    props = node.get("properties", {})
                    if "groupNames" in props:
                        group_names_list = props.get("groupNames", [])
                        if isinstance(group_names_list, list):
                            group_list = [name for name in group_names_list if name]
                        elif isinstance(group_names_list, str):
                            group_list = [name.strip() for name in group_names_list.split('\n') if name.strip()]
                    # 也尝试旧的字段名
                    elif "group_names" in props:
                        group_names_list = props.get("group_names", [])
                        if isinstance(group_names_list, list):
                            group_list = [name for name in group_names_list if name]
                        elif isinstance(group_names_list, str):
                            group_list = [name.strip() for name in group_names_list.split('\n') if name.strip()]
                    break
        
        return group_list
    
    @classmethod
    def IS_CHANGED(cls, timeout_seconds, signal=None, any_input=None, unique_id=None, prompt=None, extra_pnginfo=None):
        """让节点每次都执行"""
        return time.time()
    
    def _get_execution_id(self, prompt=None, unique_id=None):
        """自动获取execution_id：使用unique_id和时间戳生成唯一的execution_id，确保每次运行都有不同的ID"""
        # 使用unique_id和时间戳生成唯一的execution_id
        # 这样可以确保每次运行都有不同的ID，支持多次运行
        timestamp = int(time.time() * 1000)
        if unique_id:
            execution_id = f"exec_{unique_id}_{timestamp}"
        else:
            execution_id = f"exec_{timestamp}"
        
        return execution_id
    
    def wait_all(self, timeout_seconds, signal=None, any_input=None, unique_id=None, prompt=None, extra_pnginfo=None):
        try:
            # 从节点的properties中获取组名列表
            # 这些组名是通过前端UI选择的
            group_list = self._get_group_list(unique_id, prompt, extra_pnginfo)
            
            if not group_list:
                raise ValueError("组名列表不能为空，请在前端UI中选择组")
            
            # 按组名读取配置文件来判断任务是否结束
            # 检查每个组的配置文件，判断是否完成
            start_time = time.time()
            check_interval = 0.5  # 每0.5秒检查一次
            completed = False
            
            print(f"[GroupExecutorWaitAll] 开始按组名等待任务完成，组: {group_list}")
            
            while True:
                # 检查所有组是否都完成（按组名读取状态文件）
                all_completed = True
                for group_name in group_list:
                    group_completed = _group_result_manager.is_group_completed(group_name)
                    if not group_completed:
                        all_completed = False
                        break
                
                if all_completed:
                    completed = True
                    print(f"[GroupExecutorWaitAll] 所有组执行完成，组: {group_list}")
                    break
                
                # 检查超时
                if timeout_seconds and (time.time() - start_time) > timeout_seconds:
                    print(f"[GroupExecutorWaitAll] 等待超时，组: {group_list}")
                    break
                
                # 等待一段时间后再次检查
                time.sleep(check_interval)
            
            # 返回信号和完成状态
            if signal is not None:
                return (signal, completed)
            else:
                return ({"group_names": group_list, "completed": completed}, completed)
        
        except Exception as e:
            print(f"[GroupExecutorWaitAll {unique_id}] 错误: {e}")
            import traceback
            traceback.print_exc()
            return ({"error": str(e)}, False)

class GroupExecutorExtractResult:
    """从所有结果提取某个组结果的节点"""
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "optional": {
                "signal": ("SIGNAL",),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            }
        }
    
    RETURN_TYPES = ("SIGNAL", "STRING")
    RETURN_NAMES = ("signal", "result_json")
    FUNCTION = "extract_result"
    CATEGORY = CATEGORY_TYPE
    OUTPUT_NODE = True  # 标记为输出节点，确保在组中单独存在时也能被执行
    
    def _get_execution_id(self, prompt=None, unique_id=None):
        """自动获取execution_id：使用unique_id和时间戳生成唯一的execution_id，确保每次运行都有不同的ID"""
        # 使用unique_id和时间戳生成唯一的execution_id
        # 这样可以确保每次运行都有不同的ID，支持多次运行
        timestamp = int(time.time() * 1000)
        if unique_id:
            execution_id = f"exec_{unique_id}_{timestamp}"
        else:
            execution_id = f"exec_{timestamp}"
        
        return execution_id
    
    def extract_result(self, signal=None, unique_id=None, prompt=None, extra_pnginfo=None):
        try:
            # 从节点的properties中获取组名
            # 组名是通过前端UI选择的
            group_name = ""
            if prompt and unique_id:
                # 从prompt中获取当前节点的配置
                node_data = prompt.get(str(unique_id), {})
                node_inputs = node_data.get("inputs", {})
                
                # 尝试从properties中获取组名
                if "group_name" in node_inputs:
                    group_name = node_inputs.get("group_name", "")
            
            # 如果从prompt中获取不到，尝试从extra_pnginfo中获取
            if not group_name and extra_pnginfo:
                workflow = extra_pnginfo.get("workflow", {})
                nodes = workflow.get("nodes", [])
                for node in nodes:
                    node_id = node.get("id")
                    # 兼容字符串和整数类型的ID
                    if str(node_id) == str(unique_id) or node_id == unique_id:
                        props = node.get("properties", {})
                        if "groupName" in props:
                            group_name = props.get("groupName", "")
                        # 也尝试旧的字段名
                        elif "group_name" in props:
                            group_name = props.get("group_name", "")
                        break
            
            if not group_name:
                raise ValueError("组名不能为空，请在前端UI中选择组")
            
            # 通过组名获取该组的 execution_id（每个组有独立的ID）
            execution_id = _group_result_manager.get_group_execution_id(group_name)
            if execution_id:
                # 如果找到了 execution_id，使用它来获取结果（验证匹配）
                result = _group_result_manager.get_group_result(execution_id, group_name)
            else:
                # 如果找不到 execution_id，尝试通过组名直接获取结果
                result = _group_result_manager.get_group_result(group_name=group_name)
                if result:
                    execution_id = result.get("execution_id")
            
            if result is None:
                # 检查组状态文件是否存在
                status = _group_result_manager.load_status_by_group(group_name)
                if status is None:
                    raise ValueError(f"组 '{group_name}' 的执行记录不存在，请先执行组任务")
                else:
                    raise ValueError(f"组 '{group_name}' 的结果尚未就绪，请等待执行完成")
            
            # 将结果转换为JSON字符串
            import json
            result_json = json.dumps(result, ensure_ascii=False, indent=2)
            
            print(f"[GroupExecutorExtractResult] 提取组 '{group_name}' 的结果: {execution_id}")
            
            # 返回信号和结果
            if signal is not None:
                return (signal, result_json)
            else:
                return ({"execution_id": execution_id, "group_name": group_name, "result": result}, result_json)
        
        except Exception as e:
            print(f"[GroupExecutorExtractResult {unique_id}] 错误: {e}")
            import traceback
            traceback.print_exc()
            error_result = {"error": str(e)}
            import json
            return (error_result, json.dumps(error_result, ensure_ascii=False))

CONFIG_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "group_configs")
os.makedirs(CONFIG_DIR, exist_ok=True)

# 服务器配置文件路径
SERVERS_CONFIG_FILE = os.path.join(CONFIG_DIR, "servers.json")

# ============ 服务器配置管理 ============

class ServerConfigManager:
    """服务器配置管理器"""
    
    def __init__(self):
        self.config_file = SERVERS_CONFIG_FILE
        self._lock = threading.Lock()
        self._ensure_default_config()
    
    def _ensure_default_config(self):
        """确保配置文件存在，如果不存在则创建默认配置"""
        if not os.path.exists(self.config_file):
            default_config = {
                "version": "1.0",
                "default_server": "local",
                "servers": [
                    {
                        "id": "local",
                        "name": "本地服务器",
                        "url": "http://127.0.0.1:8188",
                        "auth_token": None,
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }
                ]
            }
            self._save_config(default_config)
    
    def _load_config(self):
        """加载服务器配置"""
        try:
            with self._lock:
                if not os.path.exists(self.config_file):
                    self._ensure_default_config()
                
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 验证配置格式
                if "servers" not in config:
                    config["servers"] = []
                if "default_server" not in config:
                    config["default_server"] = None
                
                return config
        except Exception as e:
            print(f"[ServerConfigManager] 加载配置失败: {e}")
            # 返回默认配置
            return {
                "version": "1.0",
                "default_server": None,
                "servers": []
            }
    
    def _save_config(self, config):
        """保存服务器配置"""
        try:
            with self._lock:
                # 确保目录存在
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ServerConfigManager] 保存配置失败: {e}")
            raise
    
    def get_all_servers(self):
        """获取所有服务器配置"""
        config = self._load_config()
        servers = config.get("servers", [])
        default_id = config.get("default_server")
        
        # 标记默认服务器
        for server in servers:
            server["is_default"] = (server.get("id") == default_id)
        
        return servers, default_id
    
    def get_server(self, server_id):
        """获取指定服务器配置"""
        config = self._load_config()
        servers = config.get("servers", [])
        
        for server in servers:
            if server.get("id") == server_id:
                return server
        return None
    
    def add_server(self, name, url, auth_token=None):
        """添加新服务器配置"""
        # 验证URL格式
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("无效的URL格式，必须包含协议（http://或https://）和主机地址")
        except Exception as e:
            raise ValueError(f"URL格式错误: {e}")
        
        config = self._load_config()
        servers = config.get("servers", [])
        
        # 检查名称是否已存在
        for server in servers:
            if server.get("name") == name:
                raise ValueError(f"服务器名称 '{name}' 已存在")
        
        # 检查URL是否已存在
        for server in servers:
            if server.get("url") == url:
                raise ValueError(f"服务器URL '{url}' 已存在")
        
        # 生成唯一ID
        server_id = f"server_{uuid.uuid4().hex[:8]}"
        # 确保ID唯一
        existing_ids = {s.get("id") for s in servers}
        while server_id in existing_ids:
            server_id = f"server_{uuid.uuid4().hex[:8]}"
        
        # 创建新服务器配置
        new_server = {
            "id": server_id,
            "name": name,
            "url": url.rstrip('/'),  # 移除末尾的斜杠
            "auth_token": auth_token if auth_token else None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        servers.append(new_server)
        config["servers"] = servers
        
        # 如果没有默认服务器，设置新添加的为默认
        if not config.get("default_server") and servers:
            config["default_server"] = server_id
        
        self._save_config(config)
        return new_server
    
    def update_server(self, server_id, name=None, url=None, auth_token=None):
        """更新服务器配置"""
        config = self._load_config()
        servers = config.get("servers", [])
        
        server_index = None
        for i, server in enumerate(servers):
            if server.get("id") == server_id:
                server_index = i
                break
        
        if server_index is None:
            raise ValueError(f"服务器ID '{server_id}' 不存在")
        
        old_server = servers[server_index]
        
        # 更新字段
        if name is not None:
            # 检查名称是否与其他服务器重复
            for i, s in enumerate(servers):
                if i != server_index and s.get("name") == name:
                    raise ValueError(f"服务器名称 '{name}' 已被使用")
            old_server["name"] = name
        
        if url is not None:
            # 验证URL格式
            try:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError("无效的URL格式")
            except Exception as e:
                raise ValueError(f"URL格式错误: {e}")
            
            # 检查URL是否与其他服务器重复
            for i, s in enumerate(servers):
                if i != server_index and s.get("url") == url:
                    raise ValueError(f"服务器URL '{url}' 已被使用")
            
            old_server["url"] = url.rstrip('/')
        
        if auth_token is not None:
            old_server["auth_token"] = auth_token if auth_token else None
        
        old_server["updated_at"] = datetime.now().isoformat()
        
        self._save_config(config)
        return old_server
    
    def delete_server(self, server_id):
        """删除服务器配置"""
        config = self._load_config()
        servers = config.get("servers", [])
        default_id = config.get("default_server")
        
        # 不能删除默认服务器
        if server_id == default_id:
            raise ValueError("不能删除默认服务器，请先设置其他服务器为默认")
        
        # 查找并删除
        server_to_delete = None
        for i, server in enumerate(servers):
            if server.get("id") == server_id:
                server_to_delete = servers.pop(i)
                break
        
        if server_to_delete is None:
            raise ValueError(f"服务器ID '{server_id}' 不存在")
        
        config["servers"] = servers
        
        # 如果删除后没有服务器了，清空默认服务器
        if not servers:
            config["default_server"] = None
        
        self._save_config(config)
        return server_to_delete
    
    def set_default_server(self, server_id):
        """设置默认服务器"""
        config = self._load_config()
        servers = config.get("servers", [])
        
        # 验证服务器是否存在
        server_exists = any(s.get("id") == server_id for s in servers)
        if not server_exists:
            raise ValueError(f"服务器ID '{server_id}' 不存在")
        
        config["default_server"] = server_id
        self._save_config(config)
        return True

# 全局服务器配置管理器实例
_server_config_manager = ServerConfigManager()

# ============ 服务器连接测试 ============

async def test_server_connection(url, auth_token=None):
    """测试服务器连接
    
    Args:
        url: 服务器URL
        auth_token: 认证Token（可选）
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        
        # 尝试连接到服务器的队列端点（轻量级检查）
        test_url = f"{url.rstrip('/')}/queue"
        
        timeout = aiohttp.ClientTimeout(total=5)  # 5秒超时
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, headers=headers) as response:
                if response.status == 200:
                    return True, "连接成功"
                elif response.status == 401:
                    return False, "认证失败：Token无效"
                elif response.status == 403:
                    return False, "访问被拒绝：权限不足"
                else:
                    return False, f"连接失败：HTTP {response.status}"
    
    except aiohttp.ClientError as e:
        return False, f"连接错误：{str(e)}"
    except asyncio.TimeoutError:
        return False, "连接超时：服务器无响应"
    except Exception as e:
        return False, f"未知错误：{str(e)}"

routes = PromptServer.instance.routes

@routes.post("/group_executor/execute_backend")
async def execute_backend(request):
    """接收前端发送的执行请求，在后台执行组"""
    try:
        data = await request.json()
        node_id = data.get("node_id")
        execution_list = data.get("execution_list", [])
        full_api_prompt = data.get("api_prompt", {})
        
        if not node_id:
            return web.json_response({"status": "error", "message": "缺少 node_id"}, status=400)
        
        if not execution_list:
            return web.json_response({"status": "error", "message": "执行列表为空"}, status=400)
        
        if not full_api_prompt:
            return web.json_response({"status": "error", "message": "缺少 API prompt"}, status=400)
        
        print(f"[GroupExecutor] 收到后台执行请求: node_id={node_id}, 执行项数={len(execution_list)}")
        
        # 启动后台执行
        success = _backend_executor.execute_in_background(
            node_id,
            execution_list,
            full_api_prompt
        )
        
        if success:
            return web.json_response({"status": "success", "message": "后台执行已启动"})
        else:
            return web.json_response({"status": "error", "message": "已有任务在执行中"}, status=409)
            
    except Exception as e:
        print(f"[GroupExecutor] 后台执行请求处理失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@routes.get("/group_executor/configs")
async def get_configs(request):
    try:

        configs = []
        for filename in os.listdir(CONFIG_DIR):
            if filename.endswith('.json'):
                configs.append({
                    "name": filename[:-5]
                })
        return web.json_response({"status": "success", "configs": configs})
    except Exception as e:
        print(f"[GroupExecutor] 获取配置失败: {str(e)}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@routes.post("/group_executor/configs")
async def save_config(request):
    try:
        print("[GroupExecutor] 收到保存配置请求")
        data = await request.json()
        config_name = data.get('name')
        if not config_name:
            return web.json_response({"status": "error", "message": "配置名称不能为空"}, status=400)
            
        safe_name = "".join(c for c in config_name if c.isalnum() or c in (' ', '-', '_'))
        filename = os.path.join(CONFIG_DIR, f"{safe_name}.json")
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"[GroupExecutor] 配置已保存: {filename}")
        return web.json_response({"status": "success"})
    except json.JSONDecodeError as e:
        print(f"[GroupExecutor] JSON解析错误: {str(e)}")
        return web.json_response({"status": "error", "message": f"JSON格式错误: {str(e)}"}, status=400)
    except Exception as e:
        print(f"[GroupExecutor] 保存配置失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@routes.get('/group_executor/configs/{name}')
async def get_config(request):
    try:
        config_name = request.match_info.get('name')
        if not config_name:
            return web.json_response({"error": "配置名称不能为空"}, status=400)
            
        filename = os.path.join(CONFIG_DIR, f"{config_name}.json")
        if not os.path.exists(filename):
            return web.json_response({"error": "配置不存在"}, status=404)
            
        with open(filename, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        return web.json_response(config)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@routes.delete('/group_executor/configs/{name}')
async def delete_config(request):
    try:
        config_name = request.match_info.get('name')
        if not config_name:
            return web.json_response({"error": "配置名称不能为空"}, status=400)
            
        filename = os.path.join(CONFIG_DIR, f"{config_name}.json")
        if not os.path.exists(filename):
            return web.json_response({"error": "配置不存在"}, status=404)
            
        os.remove(filename)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# ============ 按组名的配置文件API ============

@routes.get('/group_executor/group_config/{group_name}')
async def get_group_config(request):
    """按组名读取状态文件"""
    try:
        group_name = request.match_info.get('group_name')
        if not group_name:
            return web.json_response({"status": "error", "message": "组名不能为空"}, status=400)
        
        status = _group_result_manager.load_status_by_group(group_name)
        if status is None:
            return web.json_response({"status": "error", "message": "状态文件不存在"}, status=404)
        
        return web.json_response({"status": "success", "config": status})
    except Exception as e:
        print(f"[GroupExecutor] 获取组状态文件失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@routes.get('/group_executor/group_config/{group_name}/completed')
async def check_group_completed(request):
    """检查组任务是否完成（按组名读取状态文件）"""
    try:
        group_name = request.match_info.get('group_name')
        if not group_name:
            return web.json_response({"status": "error", "message": "组名不能为空"}, status=400)
        
        completed = _group_result_manager.is_group_completed(group_name)
        return web.json_response({"status": "success", "completed": completed})
    except Exception as e:
        print(f"[GroupExecutor] 检查组任务状态失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# ============ 服务器配置管理API ============

@routes.get("/group_executor/servers")
async def get_servers(request):
    """获取所有服务器配置列表"""
    try:
        servers, default_id = _server_config_manager.get_all_servers()
        return web.json_response({
            "status": "success",
            "servers": servers,
            "default_server": default_id
        })
    except Exception as e:
        print(f"[GroupExecutor] 获取服务器列表失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.get("/group_executor/servers/{server_id}")
async def get_server(request):
    """获取指定服务器配置"""
    try:
        server_id = request.match_info.get('server_id')
        if not server_id:
            return web.json_response({
                "status": "error",
                "message": "服务器ID不能为空"
            }, status=400)
        
        server = _server_config_manager.get_server(server_id)
        if not server:
            return web.json_response({
                "status": "error",
                "message": f"服务器ID '{server_id}' 不存在"
            }, status=404)
        
        config = _server_config_manager._load_config()
        server["is_default"] = (server_id == config.get("default_server"))
        
        return web.json_response({
            "status": "success",
            "server": server
        })
    except Exception as e:
        print(f"[GroupExecutor] 获取服务器配置失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.post("/group_executor/servers")
async def add_server(request):
    """添加新服务器配置"""
    try:
        data = await request.json()
        # 安全地处理可能为None的值
        name_value = data.get('name')
        name = name_value.strip() if name_value and isinstance(name_value, str) else ''
        url_value = data.get('url')
        url = url_value.strip() if url_value and isinstance(url_value, str) else ''
        auth_token_value = data.get('auth_token')
        auth_token = auth_token_value.strip() if auth_token_value and isinstance(auth_token_value, str) else None
        
        if not name:
            return web.json_response({
                "status": "error",
                "message": "服务器名称不能为空"
            }, status=400)
        
        if not url:
            return web.json_response({
                "status": "error",
                "message": "服务器URL不能为空"
            }, status=400)
        
        server = _server_config_manager.add_server(name, url, auth_token)
        
        return web.json_response({
            "status": "success",
            "message": "服务器添加成功",
            "server": server
        })
    except ValueError as e:
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=400)
    except Exception as e:
        print(f"[GroupExecutor] 添加服务器失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.put("/group_executor/servers/{server_id}")
async def update_server(request):
    """更新服务器配置"""
    try:
        server_id = request.match_info.get('server_id')
        if not server_id:
            return web.json_response({
                "status": "error",
                "message": "服务器ID不能为空"
            }, status=400)
        
        data = await request.json()
        name = data.get('name')
        url = data.get('url')
        auth_token = data.get('auth_token')
        
        # 如果提供了值，去除首尾空格
        if name is not None:
            name = name.strip()
            if not name:
                return web.json_response({
                    "status": "error",
                    "message": "服务器名称不能为空"
                }, status=400)
        
        if url is not None:
            url = url.strip()
            if not url:
                return web.json_response({
                    "status": "error",
                    "message": "服务器URL不能为空"
                }, status=400)
        
        if auth_token is not None:
            auth_token = (auth_token.strip() if auth_token else None) if isinstance(auth_token, str) else None
        
        server = _server_config_manager.update_server(
            server_id,
            name=name,
            url=url,
            auth_token=auth_token
        )
        
        return web.json_response({
            "status": "success",
            "message": "服务器更新成功",
            "server": server
        })
    except ValueError as e:
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=400)
    except Exception as e:
        print(f"[GroupExecutor] 更新服务器失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.delete("/group_executor/servers/{server_id}")
async def delete_server(request):
    """删除服务器配置"""
    try:
        server_id = request.match_info.get('server_id')
        if not server_id:
            return web.json_response({
                "status": "error",
                "message": "服务器ID不能为空"
            }, status=400)
        
        server = _server_config_manager.delete_server(server_id)
        
        return web.json_response({
            "status": "success",
            "message": "服务器删除成功",
            "server": server
        })
    except ValueError as e:
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=400)
    except Exception as e:
        print(f"[GroupExecutor] 删除服务器失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.post("/group_executor/servers/{server_id}/set_default")
async def set_default_server(request):
    """设置默认服务器"""
    try:
        server_id = request.match_info.get('server_id')
        if not server_id:
            return web.json_response({
                "status": "error",
                "message": "服务器ID不能为空"
            }, status=400)
        
        _server_config_manager.set_default_server(server_id)
        
        return web.json_response({
            "status": "success",
            "message": "默认服务器设置成功"
        })
    except ValueError as e:
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=400)
    except Exception as e:
        print(f"[GroupExecutor] 设置默认服务器失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.post("/group_executor/servers/{server_id}/test")
async def test_server_connection_api(request):
    """测试服务器连接"""
    try:
        server_id = request.match_info.get('server_id')
        if not server_id:
            return web.json_response({
                "status": "error",
                "message": "服务器ID不能为空"
            }, status=400)
        
        server = _server_config_manager.get_server(server_id)
        if not server:
            return web.json_response({
                "status": "error",
                "message": f"服务器ID '{server_id}' 不存在"
            }, status=404)
        
        url = server.get("url")
        auth_token = server.get("auth_token")
        
        # 执行连接测试
        success, message = await test_server_connection(url, auth_token)
        
        return web.json_response({
            "status": "success" if success else "error",
            "success": success,
            "message": message
        })
    except Exception as e:
        print(f"[GroupExecutor] 测试服务器连接失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "success": False,
            "message": str(e)
        }, status=500)

@routes.post("/group_executor/servers/test")
async def test_server_url(request):
    """测试服务器URL连接（不需要先保存）"""
    try:
        data = await request.json()
        # 安全地处理可能为None的值
        url_value = data.get('url')
        url = url_value.strip() if url_value and isinstance(url_value, str) else ''
        auth_token_value = data.get('auth_token')
        auth_token = auth_token_value.strip() if auth_token_value and isinstance(auth_token_value, str) else None
        
        if not url:
            return web.json_response({
                "status": "error",
                "success": False,
                "message": "服务器URL不能为空"
            }, status=400)
        
        # 执行连接测试
        success, message = await test_server_connection(url, auth_token)
        
        return web.json_response({
            "status": "success" if success else "error",
            "success": success,
            "message": message
        })
    except Exception as e:
        print(f"[GroupExecutor] 测试服务器URL失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "success": False,
            "message": str(e)
        }, status=500)

# ============ 组执行结果管理API ============

@routes.post("/group_executor/results/set")
async def set_group_result(request):
    """设置某个组的执行结果（只对非本地服务器保存）"""
    try:
        data = await request.json()
        execution_id = data.get("execution_id")
        group_name = data.get("group_name")
        result_data = data.get("result_data", {})
        server_id = data.get("server_id", None)  # 获取服务器ID，如果为None则不保存
        
        if not execution_id:
            return web.json_response({
                "status": "error",
                "message": "执行ID不能为空"
            }, status=400)
        
        if not group_name:
            return web.json_response({
                "status": "error",
                "message": "组名不能为空"
            }, status=400)
        
        success = _group_result_manager.set_group_result(execution_id, group_name, result_data, server_id=server_id)
        
        if success:
            return web.json_response({
                "status": "success",
                "message": "结果已设置"
            })
        else:
            return web.json_response({
                "status": "error",
                "message": "执行ID或组名不存在"
            }, status=404)
            
    except Exception as e:
        print(f"[GroupExecutor] 设置组结果失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.get("/group_executor/results/{execution_id}")
async def get_execution_results(request):
    """获取执行的所有结果"""
    try:
        execution_id = request.match_info.get('execution_id')
        if not execution_id:
            return web.json_response({
                "status": "error",
                "message": "执行ID不能为空"
            }, status=400)
        
        results = _group_result_manager.get_all_results(execution_id)
        completed = _group_result_manager.is_completed(execution_id)
        
        if results is None:
            return web.json_response({
                "status": "error",
                "message": f"执行ID '{execution_id}' 不存在"
            }, status=404)
        
        return web.json_response({
            "status": "success",
            "execution_id": execution_id,
            "results": results,
            "completed": completed
        })
            
    except Exception as e:
        print(f"[GroupExecutor] 获取执行结果失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.get("/group_executor/results/latest/id")
async def get_latest_execution_id(request):
    """获取最新的execution_id"""
    try:
        execution_id = _group_result_manager.get_latest_execution_id()
        
        if execution_id:
            return web.json_response({
                "status": "success",
                "execution_id": execution_id
            })
        else:
            return web.json_response({
                "status": "error",
                "message": "没有找到执行任务"
            }, status=404)
            
    except Exception as e:
        print(f"[GroupExecutor] 获取最新执行ID失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)

@routes.post("/group_executor/results/register")
async def register_execution(request):
    """注册一个执行任务（只对非本地服务器保存）"""
    try:
        data = await request.json()
        execution_id = data.get("execution_id")
        group_names = data.get("group_names", [])
        server_id = data.get("server_id", None)  # 获取服务器ID，如果为None则不保存
        
        if not execution_id:
            return web.json_response({
                "status": "error",
                "message": "执行ID不能为空"
            }, status=400)
        
        if not group_names or not isinstance(group_names, list):
            return web.json_response({
                "status": "error",
                "message": "组名列表不能为空"
            }, status=400)
        
        _group_result_manager.register_execution(execution_id, group_names, server_id=server_id)
        
        return web.json_response({
            "status": "success",
            "message": "执行任务已注册"
        })
            
    except Exception as e:
        print(f"[GroupExecutor] 注册执行任务失败: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)