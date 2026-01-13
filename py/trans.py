from server import PromptServer
import os
import sys
import torch
import numpy as np
from PIL import Image, ImageSequence, ImageOps
import folder_paths
import random
from nodes import SaveImage
import json
from comfy.cli_args import args
from PIL.PngImagePlugin import PngInfo
import time
import node_helpers
import threading

CATEGORY_TYPE = "🎈LAOGOU/Group"
class AnyType(str):
    """用于表示任意类型的特殊类，在类型比较时总是返回相等"""
    def __eq__(self, _) -> bool:
        return True

    def __ne__(self, __value: object) -> bool:
        return False

any_typ = AnyType("*")

class LG_ImageSender:
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.compress_level = 1
        self.accumulated_results = []  
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "要发送的图像"}),
                "filename_prefix": ("STRING", {"default": "lg_send"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
                "accumulate": ("BOOLEAN", {"default": False, "tooltip": "开启后将累积所有图像一起发送"}), 
                "preview_rgba": ("BOOLEAN", {"default": True, "tooltip": "开启后预览显示RGBA格式，关闭则预览显示RGB格式"})
            },
            "optional": {
                "masks": ("MASK", {"tooltip": "要发送的遮罩"}),
                "signal_opt": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"})
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = (any_typ,)
    RETURN_NAMES = ("signal",)
    FUNCTION = "save_images"
    CATEGORY = CATEGORY_TYPE
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(s, images, filename_prefix, link_id, accumulate, preview_rgba, masks=None, prompt=None, extra_pnginfo=None):
        if isinstance(accumulate, list):
            accumulate = accumulate[0]
        
        if accumulate:
            return float("NaN") 
        
        # 非积累模式下计算hash
        hash_value = hash(str(images) + str(masks))
        return hash_value

    def save_images(self, images, filename_prefix, link_id, accumulate, preview_rgba, masks=None, prompt=None, extra_pnginfo=None):
        timestamp = int(time.time() * 1000)
        results = list()

        filename_prefix = filename_prefix[0] if isinstance(filename_prefix, list) else filename_prefix
        link_id = link_id[0] if isinstance(link_id, list) else link_id
        accumulate = accumulate[0] if isinstance(accumulate, list) else accumulate
        preview_rgba = preview_rgba[0] if isinstance(preview_rgba, list) else preview_rgba
        
        for idx, image_batch in enumerate(images):
            try:
                image = image_batch.squeeze()
                rgb_image = Image.fromarray(np.clip(255. * image.cpu().numpy(), 0, 255).astype(np.uint8))

                if masks is not None and idx < len(masks):
                    mask = masks[idx].squeeze()
                    mask_array = np.clip(255. * (1 - mask.cpu().numpy()), 0, 255).astype(np.uint8)
                    mask_img = Image.fromarray(mask_array, mode='L')
                    
                    # 确保 mask 尺寸与 rgb_image 匹配
                    if mask_img.size != rgb_image.size:
                        mask_img = mask_img.resize(rgb_image.size, Image.Resampling.LANCZOS)
                else:
                    mask_img = Image.new('L', rgb_image.size, 255)

                # 确保 mask_img 是 'L' 模式
                if mask_img.mode != 'L':
                    mask_img = mask_img.convert('L')

                r, g, b = rgb_image.convert('RGB').split()
                rgba_image = Image.merge('RGBA', (r, g, b, mask_img))

                # 保存RGBA格式，这是实际要发送的文件
                filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}.png"
                file_path = os.path.join(self.output_dir, filename)
                rgba_image.save(file_path, compress_level=self.compress_level)
                
                # 准备要发送的数据项
                original_result = {
                    "filename": filename,
                    "subfolder": "",
                    "type": self.type
                }
                
                # 如果是要显示RGB预览
                if not preview_rgba:
                    preview_filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}_preview.jpg"
                    preview_path = os.path.join(self.output_dir, preview_filename)
                    rgb_image.save(preview_path, format="JPEG", quality=95)
                    # 将预览图添加到UI显示结果中
                    results.append({
                        "filename": preview_filename,
                        "subfolder": "",
                        "type": self.type
                    })
                else:
                    # 显示RGBA
                    results.append(original_result)

                # 累积的始终是原始图像结果
                if accumulate:
                    self.accumulated_results.append(original_result)

            except Exception as e:
                print(f"[ImageSender] 处理图像 {idx+1} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                continue

        # 获取实际要发送的结果
        if accumulate:
            send_results = self.accumulated_results
        else:
            # 创建一个包含原始文件名的列表用于发送
            send_results = []
            for idx in range(len(results)):
                original_filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}.png"
                send_results.append({
                    "filename": original_filename,
                    "subfolder": "",
                    "type": self.type
                })
        
        if send_results:
            print(f"[ImageSender] 发送 {len(send_results)} 张图像")
            # 使用 None 作为 sid 参数，确保事件发送给所有连接的客户端
            # 这对于后台执行时确保预览图能正确显示很重要
            PromptServer.instance.send_sync("img-send", {
                "link_id": link_id,
                "images": send_results
            }, sid=None)
        if not accumulate:
            self.accumulated_results = []
        
        return { "ui": { "images": results } }

class LG_ImageSenderPlus:
    def __init__(self):
        self.output_dir = folder_paths.get_input_directory()
        self.type = "input"
        self.compress_level = 1
        self.accumulated_results = []
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "要发送的图像"}),
                "filename_prefix": ("STRING", {"default": "lg_send_plus"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
                "accumulate": ("BOOLEAN", {"default": False, "tooltip": "开启后将累积所有图像一起发送"}), 
                "preview_rgba": ("BOOLEAN", {"default": True, "tooltip": "开启后预览显示RGBA格式，关闭则预览显示RGB格式"})
            },
            "optional": {
                "masks": ("MASK", {"tooltip": "要发送的遮罩"}),
                "signal_opt": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"})
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = (any_typ,)
    RETURN_NAMES = ("signal",)
    FUNCTION = "save_images"
    CATEGORY = CATEGORY_TYPE
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(s, images, filename_prefix, link_id, accumulate, preview_rgba, masks=None, prompt=None, extra_pnginfo=None):
        if isinstance(accumulate, list):
            accumulate = accumulate[0]
        
        if accumulate:
            return float("NaN") 
        
        # 非积累模式下计算hash
        hash_value = hash(str(images) + str(masks))
        return hash_value

    def save_images(self, images, filename_prefix, link_id, accumulate, preview_rgba, masks=None, prompt=None, extra_pnginfo=None):
        timestamp = int(time.time() * 1000)
        results = list()

        filename_prefix = filename_prefix[0] if isinstance(filename_prefix, list) else filename_prefix
        link_id = link_id[0] if isinstance(link_id, list) else link_id
        accumulate = accumulate[0] if isinstance(accumulate, list) else accumulate
        preview_rgba = preview_rgba[0] if isinstance(preview_rgba, list) else preview_rgba
        
        for idx, image_batch in enumerate(images):
            try:
                image = image_batch.squeeze()
                rgb_image = Image.fromarray(np.clip(255. * image.cpu().numpy(), 0, 255).astype(np.uint8))

                if masks is not None and idx < len(masks):
                    mask = masks[idx].squeeze()
                    mask_array = np.clip(255. * (1 - mask.cpu().numpy()), 0, 255).astype(np.uint8)
                    mask_img = Image.fromarray(mask_array, mode='L')
                    
                    # 确保 mask 尺寸与 rgb_image 匹配
                    if mask_img.size != rgb_image.size:
                        mask_img = mask_img.resize(rgb_image.size, Image.Resampling.LANCZOS)
                else:
                    mask_img = Image.new('L', rgb_image.size, 255)

                # 确保 mask_img 是 'L' 模式
                if mask_img.mode != 'L':
                    mask_img = mask_img.convert('L')

                r, g, b = rgb_image.convert('RGB').split()
                rgba_image = Image.merge('RGBA', (r, g, b, mask_img))

                # 保存RGBA格式到 input 目录，这是实际要发送的文件
                filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}.png"
                file_path = os.path.join(self.output_dir, filename)
                rgba_image.save(file_path, compress_level=self.compress_level)
                
                # 准备要发送的数据项
                original_result = {
                    "filename": filename,
                    "subfolder": "",
                    "type": self.type
                }
                
                # 如果是要显示RGB预览
                if not preview_rgba:
                    preview_filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}_preview.jpg"
                    preview_path = os.path.join(self.output_dir, preview_filename)
                    rgb_image.save(preview_path, format="JPEG", quality=95)
                    # 将预览图添加到UI显示结果中
                    results.append({
                        "filename": preview_filename,
                        "subfolder": "",
                        "type": self.type
                    })
                else:
                    # 显示RGBA
                    results.append(original_result)

                # 累积的始终是原始图像结果
                if accumulate:
                    self.accumulated_results.append(original_result)

            except Exception as e:
                print(f"[ImageSenderPlus] 处理图像 {idx+1} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                continue

        # 获取实际要发送的结果
        if accumulate:
            send_results = self.accumulated_results
        else:
            # 创建一个包含原始文件名的列表用于发送
            send_results = []
            for idx in range(len(results)):
                original_filename = f"{filename_prefix}_{link_id}_{timestamp}_{idx}.png"
                send_results.append({
                    "filename": original_filename,
                    "subfolder": "",
                    "type": self.type
                })
        
        if send_results:
            print(f"[ImageSenderPlus] 发送 {len(send_results)} 张图像到 input 目录")
            # 使用 None 作为 sid 参数，确保事件发送给所有连接的客户端
            # 这对于后台执行时确保预览图能正确显示很重要
            PromptServer.instance.send_sync("img-send", {
                "link_id": link_id,
                "images": send_results
            }, sid=None)
        if not accumulate:
            self.accumulated_results = []
        
        return { "ui": { "images": results } }

class LG_ImageReceiver:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("STRING", {"default": "", "multiline": False, "tooltip": "多个文件名用逗号分隔"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
            }
        }


    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "masks")
    CATEGORY = CATEGORY_TYPE
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "load_image"

    def load_image(self, image, link_id):
        image_files = [x.strip() for x in image.split(',') if x.strip()]
        print(f"[ImageReceiver] 加载图像: {image_files}")
        
        output_images = []
        output_masks = []
        
        if not image_files:
            empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
            return ([empty_image], [empty_mask])
        
        try:
            temp_dir = folder_paths.get_temp_directory()
            
            for img_file in image_files:
                try:
                    img_path = os.path.join(temp_dir, img_file)
                    
                    if not os.path.exists(img_path):
                        print(f"[ImageReceiver] 文件不存在: {img_path}")
                        continue
                    
                    img = Image.open(img_path)
                    
                    if img.mode == 'RGBA':
                        r, g, b, a = img.split()
                        rgb_image = Image.merge('RGB', (r, g, b))
                        image = np.array(rgb_image).astype(np.float32) / 255.0
                        image = torch.from_numpy(image)[None,]
                        mask = np.array(a).astype(np.float32) / 255.0
                        mask = torch.from_numpy(mask)[None,]
                        mask = 1.0 - mask
                    else:
                        image = np.array(img.convert('RGB')).astype(np.float32) / 255.0
                        image = torch.from_numpy(image)[None,]
                        mask = torch.zeros((1, image.shape[1], image.shape[2]), dtype=torch.float32, device="cpu")
                    
                    output_images.append(image)
                    output_masks.append(mask)
                    
                except Exception as e:
                    print(f"[ImageReceiver] 处理文件 {img_file} 时出错: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            return (output_images, output_masks)

        except Exception as e:
            print(f"[ImageReceiver] 处理图像时出错: {str(e)}")
            return ([], [])

class LG_ImageReceiverPlus:
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("STRING", {"default": "", "multiline": False, "tooltip": "图像文件名（从input或temp目录）"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID，需与发送端link_id匹配"}),
            },
            "optional": {
                "mask_file": ("STRING", {"default": "", "multiline": False, "tooltip": "可选的遮罩文件名，用于加载已编辑的遮罩"}),
                "signal": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", any_typ)
    RETURN_NAMES = ("images", "masks", "signal")
    CATEGORY = CATEGORY_TYPE
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = "load_image"
    INPUT_IS_LIST = False

    def load_image(self, image, link_id, mask_file="", signal=None, unique_id=None):
        output_images = []
        output_masks = []
        
        temp_dir = folder_paths.get_temp_directory()
        input_dir = folder_paths.get_input_directory()
        
        def parse_file_path(file_str):
            """解析文件路径，支持 'filename.png [input]' 或 'filename.png [temp]' 格式"""
            file_str = file_str.strip()
            # 检查是否有 [input] 或 [temp] 标识符
            if file_str.endswith(' [input]'):
                file_path = file_str[:-8].strip()  # 去掉 ' [input]'
                return file_path, 'input'
            elif file_str.endswith(' [temp]'):
                file_path = file_str[:-7].strip()  # 去掉 ' [temp]'
                return file_path, 'temp'
            else:
                # 没有标识符，返回原路径
                return file_str, None
        
        # 解析图像文件名（支持逗号分隔的多个文件）
        if isinstance(image, str):
            image_files = [x.strip() for x in image.split(',') if x.strip()]
        elif isinstance(image, list):
            image_files = [str(img).strip() for img in image if img]
        else:
            image_files = [str(image).strip()] if image else []
        
        if not image_files:
            empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
            return ([empty_image], [empty_mask], signal)
        
        print(f"[ImageReceiverPlus] 加载图像: {image_files}, link_id={link_id}")
        
        # 解析遮罩文件名（支持逗号分隔的多个文件）
        if isinstance(mask_file, str):
            mask_files = [x.strip() for x in mask_file.split(',') if x.strip()]
        elif isinstance(mask_file, list):
            mask_files = [str(m).strip() for m in mask_file if m]
        else:
            mask_files = [str(mask_file).strip()] if mask_file else []
        
        try:
            for idx, img_file in enumerate(image_files):
                try:
                    # 解析文件路径和类型
                    file_path, file_type = parse_file_path(img_file)
                    
                    # 根据文件类型或默认行为确定加载路径
                    if file_type == 'input':
                        # 明确指定从 input 目录加载
                        img_path = os.path.join(input_dir, file_path)
                        img_path = os.path.normpath(img_path)
                    elif file_type == 'temp':
                        # 明确指定从 temp 目录加载
                        img_path = os.path.join(temp_dir, file_path)
                        img_path = os.path.normpath(img_path)
                    else:
                        # 默认行为：先尝试 temp，再尝试 input
                        img_path = os.path.join(temp_dir, file_path)
                        img_path = os.path.normpath(img_path)
                        if not os.path.exists(img_path):
                            img_path = os.path.join(input_dir, file_path)
                            img_path = os.path.normpath(img_path)
                    
                    if not os.path.exists(img_path):
                        print(f"[ImageReceiverPlus] 文件不存在: {img_path}")
                        continue
                    
                    img = node_helpers.pillow(Image.open, img_path)
                    
                    w, h = None, None
                    frame_images = []
                    frame_masks = []
                    
                    # 处理图像序列（如 GIF、多帧 PNG 等）
                    for i in ImageSequence.Iterator(img):
                        i = node_helpers.pillow(ImageOps.exif_transpose, i)
                        
                        if i.mode == 'I':
                            i = i.point(lambda i: i * (1 / 255))
                        rgb_image = i.convert("RGB")
                        
                        if len(frame_images) == 0:
                            w = rgb_image.size[0]
                            h = rgb_image.size[1]
                        
                        if rgb_image.size[0] != w or rgb_image.size[1] != h:
                            continue
                        
                        image_tensor = np.array(rgb_image).astype(np.float32) / 255.0
                        image_tensor = torch.from_numpy(image_tensor)[None,]
                        
                        # 处理遮罩
                        if 'A' in i.getbands():
                            mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                            mask = 1. - torch.from_numpy(mask)
                        elif i.mode == 'P' and 'transparency' in i.info:
                            mask = np.array(i.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                            mask = 1. - torch.from_numpy(mask)
                        else:
                            mask = torch.zeros((rgb_image.size[1], rgb_image.size[0]), dtype=torch.float32, device="cpu")
                        
                        frame_images.append(image_tensor)
                        frame_masks.append(mask.unsqueeze(0))
                        
                        if img.format == "MPO":
                            break  # ignore all frames except the first one for MPO format
                    
                    # 如果提供了遮罩文件，尝试加载它（覆盖alpha通道）
                    if mask_files and idx < len(mask_files) and w is not None and h is not None:
                        # 解析遮罩文件路径和类型
                        mask_file_path_str, mask_file_type = parse_file_path(mask_files[idx])
                        
                        # 根据文件类型或默认行为确定加载路径
                        if mask_file_type == 'input':
                            # 明确指定从 input 目录加载
                            mask_file_path = os.path.join(input_dir, mask_file_path_str)
                            mask_file_path = os.path.normpath(mask_file_path)
                        elif mask_file_type == 'temp':
                            # 明确指定从 temp 目录加载
                            mask_file_path = os.path.join(temp_dir, mask_file_path_str)
                            mask_file_path = os.path.normpath(mask_file_path)
                        else:
                            # 默认行为：先尝试 temp，再尝试 input
                            mask_file_path = os.path.join(temp_dir, mask_file_path_str)
                            mask_file_path = os.path.normpath(mask_file_path)
                            if not os.path.exists(mask_file_path):
                                mask_file_path = os.path.join(input_dir, mask_file_path_str)
                                mask_file_path = os.path.normpath(mask_file_path)
                        
                        if os.path.exists(mask_file_path):
                            try:
                                mask_img = node_helpers.pillow(Image.open, mask_file_path)
                                
                                # 处理遮罩文件（可能是单帧或多帧）
                                mask_frames = []
                                for mask_frame in ImageSequence.Iterator(mask_img):
                                    mask_frame = node_helpers.pillow(ImageOps.exif_transpose, mask_frame)
                                    
                                    # 提取遮罩通道
                                    if mask_frame.mode == 'RGBA':
                                        mask_array = np.array(mask_frame.getchannel('A')).astype(np.float32) / 255.0
                                    elif mask_frame.mode == 'L':
                                        mask_array = np.array(mask_frame).astype(np.float32) / 255.0
                                    elif mask_frame.mode == 'P' and 'transparency' in mask_frame.info:
                                        mask_array = np.array(mask_frame.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                                    else:
                                        mask_array = np.array(mask_frame.convert('L')).astype(np.float32) / 255.0
                                    
                                    # 调整遮罩大小以匹配图像
                                    if mask_array.shape[0] != h or mask_array.shape[1] != w:
                                        mask_pil = Image.fromarray((mask_array * 255).astype(np.uint8))
                                        mask_pil = mask_pil.resize((w, h), Image.LANCZOS)
                                        mask_array = np.array(mask_pil).astype(np.float32) / 255.0
                                    
                                    mask_tensor = torch.from_numpy(mask_array)
                                    mask_tensor = 1.0 - mask_tensor  # 反转遮罩（ComfyUI中白色=透明区域）
                                    mask_frames.append(mask_tensor.unsqueeze(0))
                                    
                                    if mask_img.format == "MPO":
                                        break
                                
                                # 如果遮罩文件有多个帧，使用第一个；否则使用第一个遮罩
                                if mask_frames:
                                    # 更新所有帧的遮罩（如果遮罩文件只有一帧，则应用到所有图像帧）
                                    if len(mask_frames) == 1:
                                        # 单个遮罩应用到所有帧
                                        for frame_idx in range(len(frame_masks)):
                                            frame_masks[frame_idx] = mask_frames[0]
                                    else:
                                        # 多帧遮罩，按帧对应
                                        for frame_idx in range(min(len(frame_masks), len(mask_frames))):
                                            frame_masks[frame_idx] = mask_frames[frame_idx]
                                
                                print(f"[ImageReceiverPlus] 已加载遮罩文件: {mask_files[idx]}")
                            except Exception as e:
                                print(f"[ImageReceiverPlus] 加载遮罩文件失败: {str(e)}")
                                import traceback
                                traceback.print_exc()
                    
                    # 合并多帧图像
                    if len(frame_images) > 1:
                        output_image = torch.cat(frame_images, dim=0)
                        output_mask = torch.cat(frame_masks, dim=0)
                    elif len(frame_images) == 1:
                        output_image = frame_images[0]
                        output_mask = frame_masks[0]
                    else:
                        # 如果没有有效帧，创建空图像和遮罩
                        output_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                        output_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
                    
                    output_images.append(output_image)
                    output_masks.append(output_mask)
                    
                except Exception as e:
                    print(f"[ImageReceiverPlus] 处理文件 {img_file} 时出错: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            if not output_images:
                empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
                return ([empty_image], [empty_mask], signal)
            
            return (output_images, output_masks, signal)

        except Exception as e:
            print(f"[ImageReceiverPlus] 处理图像时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return ([], [], signal)
    
    @classmethod
    def IS_CHANGED(s, image, link_id, mask_file="", unique_id=None):
        # 计算hash以检测变化
        hash_value = hash(str(image) + str(mask_file))
        return hash_value

class LG_TextSender:
    def __init__(self):
        self.accumulated_texts = []
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "", "tooltip": "要发送的文本内容"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
                "accumulate": ("BOOLEAN", {"default": False, "tooltip": "开启后将累积所有文本一起发送"}), 
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = (any_typ,)
    RETURN_NAMES = ("signal",)
    FUNCTION = "send_text"
    CATEGORY = CATEGORY_TYPE
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(s, text, link_id, accumulate, prompt=None, extra_pnginfo=None):
        if isinstance(accumulate, list):
            accumulate = accumulate[0]
        
        if accumulate:
            return float("NaN") 
        
        # 非积累模式下计算hash
        hash_value = hash(str(text))
        return hash_value

    def send_text(self, text, link_id, accumulate, prompt=None, extra_pnginfo=None):
        text = text[0] if isinstance(text, list) else text
        link_id = link_id[0] if isinstance(link_id, list) else link_id
        accumulate = accumulate[0] if isinstance(accumulate, list) else accumulate
        
        # 累积文本
        if accumulate:
            if text:
                self.accumulated_texts.append(text)
        
        # 确定要发送的文本
        if accumulate:
            send_text = "\n".join(self.accumulated_texts) if self.accumulated_texts else ""
        else:
            send_text = text if text else ""
        
        # 发送文本
        if send_text:
            print(f"[TextSender] 发送文本 (link_id={link_id}): {len(send_text)} 字符")
            PromptServer.instance.send_sync("text-send", {
                "link_id": link_id,
                "text": send_text
            }, sid=None)
        
        if not accumulate:
            self.accumulated_texts = []
        
        # OUTPUT_IS_LIST=(True,) 要求返回列表，signal 赋值为结果文本
        return ([send_text],)

class LG_TextReceiver:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "", "tooltip": "接收的文本内容，可在此编辑"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "接收端连接ID，需与发送端link_id匹配"}),
            },
            "optional": {
                "signal": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"}),
            }
        }

    RETURN_TYPES = ("STRING", any_typ)
    RETURN_NAMES = ("text", "signal")
    CATEGORY = CATEGORY_TYPE
    OUTPUT_IS_LIST = (False, False)
    FUNCTION = "load_text"

    def load_text(self, text, link_id, signal=None):
        # 处理文本输入（可能来自列表）
        if isinstance(text, list):
            text = text[0] if text else ""
        text = text if text else ""
        
        # 处理 link_id（可能来自列表）
        if isinstance(link_id, list):
            link_id = link_id[0] if link_id else 1
        link_id = link_id if link_id else 1
        
        # 如果文本框内容为空（包括空字符串或只包含空格）且 signal 不为空，则使用 signal 转为文本
        if (not text or text.strip() == "") and signal is not None:
            # 将 signal 转换为文本
            if isinstance(signal, str):
                text = signal
            elif isinstance(signal, list):
                # 如果是列表，尝试提取第一个元素或转换为字符串
                if signal:
                    if isinstance(signal[0], str):
                        text = signal[0]
                    else:
                        text = str(signal[0])
                else:
                    text = ""
            else:
                # 其他类型直接转换为字符串
                text = str(signal)
        
        print(f"[TextReceiver] 加载文本 (link_id={link_id}): {len(text)} 字符")
        return (text, signal)

class ImageListSplitter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "indices": ("STRING", {
                    "default": "", 
                    "multiline": False,
                    "tooltip": "输入要提取的图片索引，用逗号分隔，如：0,1,3,4"
                }),
            },
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "split_images"
    CATEGORY = CATEGORY_TYPE

    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)  # (images,)

    def split_images(self, images, indices):
        try:
            # 解析索引字符串
            try:
                if isinstance(indices, list):
                    indices = indices[0] if indices else ""
                indices = [int(idx.strip()) for idx in indices.split(',') if idx.strip()]
            except ValueError:
                print("[ImageSplitter] 索引格式错误，请使用逗号分隔的数字")
                return ([],)
            
            # 确保images是列表
            if not isinstance(images, list):
                images = [images]
            
            # 处理批量图片的情况
            if len(images) == 1 and len(images[0].shape) == 4:  # [B, H, W, C]
                batch_images = images[0]
                total_images = batch_images.shape[0]
                print(f"[ImageSplitter] 检测到批量图片，总数: {total_images}")
                
                selected_images = []
                for idx in indices:
                    if 0 <= idx < total_images:
                        # 保持批次维度，使用unsqueeze确保维度为 [1, H, W, C]
                        img = batch_images[idx].unsqueeze(0)
                        selected_images.append(img)
                        print(f"[ImageSplitter] 从批量中选择第 {idx} 张图片")
                    else:
                        print(f"[ImageSplitter] 索引 {idx} 超出批量范围 0-{total_images-1}")
                
                if not selected_images:
                    return ([],)
                return (selected_images,)
            
            # 处理图片列表的情况
            total_images = len(images)
            print(f"[ImageSplitter] 检测到图片列表，总数: {total_images}")
            
            if total_images == 0:
                print("[ImageSplitter] 没有输入图片")
                return ([],)
            
            selected_images = []
            for idx in indices:
                if 0 <= idx < total_images:
                    selected_image = images[idx]
                    # 确保输出维度为 [1, H, W, C]
                    if len(selected_image.shape) == 3:  # [H, W, C]
                        selected_image = selected_image.unsqueeze(0)
                    selected_images.append(selected_image)
                    print(f"[ImageSplitter] 从列表中选择第 {idx} 张图片")
                else:
                    print(f"[ImageSplitter] 索引 {idx} 超出列表范围 0-{total_images-1}")
            
            if not selected_images:
                return ([],)
            return (selected_images,)

        except Exception as e:
            print(f"[ImageSplitter] 处理出错: {str(e)}")
            return ([],)

class MaskListSplitter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK",),
                "indices": ("STRING", {
                    "default": "", 
                    "multiline": False,
                    "tooltip": "输入要提取的遮罩索引，用逗号分隔，如：0,1,3,4"
                }),
            },
        }
    
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("masks",)
    FUNCTION = "split_masks"
    CATEGORY = CATEGORY_TYPE

    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)  # (masks,)

    def split_masks(self, masks, indices):
        try:
            # 解析索引字符串
            try:
                if isinstance(indices, list):
                    indices = indices[0] if indices else ""
                indices = [int(idx.strip()) for idx in indices.split(',') if idx.strip()]
            except ValueError:
                print("[MaskSplitter] 索引格式错误，请使用逗号分隔的数字")
                return ([],)
            
            # 确保masks是列表
            if not isinstance(masks, list):
                masks = [masks]
            
            # 处理批量遮罩的情况
            if len(masks) == 1 and len(masks[0].shape) == 3:  # [B, H, W]
                batch_masks = masks[0]
                total_masks = batch_masks.shape[0]
                print(f"[MaskSplitter] 检测到批量遮罩，总数: {total_masks}")
                
                selected_masks = []
                for idx in indices:
                    if 0 <= idx < total_masks:
                        selected_masks.append(batch_masks[idx].unsqueeze(0))
                        print(f"[MaskSplitter] 从批量中选择第 {idx} 个遮罩")
                    else:
                        print(f"[MaskSplitter] 索引 {idx} 超出批量范围 0-{total_masks-1}")
                
                if not selected_masks:
                    return ([],)
                return (selected_masks,)
            
            # 处理遮罩列表的情况
            total_masks = len(masks)
            print(f"[MaskSplitter] 检测到遮罩列表，总数: {total_masks}")
            
            if total_masks == 0:
                print("[MaskSplitter] 没有输入遮罩")
                return ([],)
            
            selected_masks = []
            for idx in indices:
                if 0 <= idx < total_masks:
                    selected_mask = masks[idx]
                    if len(selected_mask.shape) == 2:  # [H, W]
                        selected_mask = selected_mask.unsqueeze(0)
                    elif len(selected_mask.shape) != 3:  # 不是 [B, H, W]
                        print(f"[MaskSplitter] 不支持的遮罩维度: {selected_mask.shape}")
                        continue
                    selected_masks.append(selected_mask)
                    print(f"[MaskSplitter] 从列表中选择第 {idx} 个遮罩")
                else:
                    print(f"[MaskSplitter] 索引 {idx} 超出列表范围 0-{total_masks-1}")
            
            if not selected_masks:
                return ([],)
            return (selected_masks,)

        except Exception as e:
            print(f"[MaskSplitter] 处理出错: {str(e)}")
            return ([],)

class ImageListRepeater:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "repeat_times": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 100,
                    "step": 1,
                    "tooltip": "每张图片重复的次数"
                }),
            },
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "repeat_images"
    CATEGORY = CATEGORY_TYPE

    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)

    def repeat_images(self, images, repeat_times):
        try:
            # 处理 repeat_times 参数
            if isinstance(repeat_times, list):
                repeat_times = repeat_times[0] if repeat_times else 1
            
            # 确保images是列表
            if not isinstance(images, list):
                images = [images]
            
            if len(images) == 0:
                print("[ImageRepeater] 没有输入图片")
                return ([],)
            
            # 创建重复后的图片列表
            repeated_images = []
            for idx, img in enumerate(images):
                for _ in range(int(repeat_times)):  # 确保 repeat_times 是整数
                    repeated_images.append(img)
                print(f"[ImageRepeater] 图片 {idx} 重复 {repeat_times} 次")
            
            print(f"[ImageRepeater] 输入 {len(images)} 张图片，输出 {len(repeated_images)} 张图片")
            return (repeated_images,)

        except Exception as e:
            print(f"[ImageRepeater] 处理出错: {str(e)}")
            return ([],)

class MaskListRepeater:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK",),
                "repeat_times": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 100,
                    "step": 1,
                    "tooltip": "每张遮罩重复的次数"
                }),
            },
        }
    
    RETURN_TYPES = ("MASK",)            
    RETURN_NAMES = ("masks",)
    FUNCTION = "repeat_masks"
    CATEGORY = CATEGORY_TYPE

    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)    

    def repeat_masks(self, masks, repeat_times):
        try:
            # 处理 repeat_times 参数
            if isinstance(repeat_times, list):
                repeat_times = repeat_times[0] if repeat_times else 1

            # 确保masks是列表
            if not isinstance(masks, list):
                masks = [masks]

            if len(masks) == 0:
                print("[MaskRepeater] 没有输入遮罩")
                return ([],)

            # 创建重复后的遮罩列表
            repeated_masks = []     
            for idx, mask in enumerate(masks):
                for _ in range(int(repeat_times)):  # 确保 repeat_times 是整数
                    repeated_masks.append(mask)
                print(f"[MaskRepeater] 遮罩 {idx} 重复 {repeat_times} 次")

            print(f"[MaskRepeater] 输入 {len(masks)} 个遮罩，输出 {len(repeated_masks)} 个遮罩")
            return (repeated_masks,)    

        except Exception as e:
            print(f"[MaskRepeater] 处理出错: {str(e)}")
            return ([],)


    
class LG_FastPreview(SaveImage):
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.prefix_append = "_temp_" + ''.join(random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5))
        
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
                    "images": ("IMAGE", ),
                    "format": (["PNG", "JPEG", "WEBP"], {"default": "JPEG"}),
                    "quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1}),
                },
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
               }
    
    RETURN_TYPES = ()
    FUNCTION = "save_images"
    
    CATEGORY = CATEGORY_TYPE
    DESCRIPTION = "快速预览图像,支持多种格式和质量设置"

    def save_images(self, images, format="JPEG", quality=95, prompt=None, extra_pnginfo=None):
        filename_prefix = "preview"
        filename_prefix += self.prefix_append
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0])
        
        results = list()
        for (batch_number, image) in enumerate(images):
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            save_kwargs = {}
            if format == "PNG":
                file_extension = ".png"

                compress_level = int(9 * (1 - quality/100)) 
                save_kwargs["compress_level"] = compress_level

                if not args.disable_metadata:
                    metadata = PngInfo()
                    if prompt is not None:
                        metadata.add_text("prompt", json.dumps(prompt))
                    if extra_pnginfo is not None:
                        for x in extra_pnginfo:
                            metadata.add_text(x, json.dumps(extra_pnginfo[x]))
                    save_kwargs["pnginfo"] = metadata
            elif format == "JPEG":
                file_extension = ".jpg"
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            else:  
                file_extension = ".webp"
                save_kwargs["quality"] = quality
                
            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            file = f"{filename_with_batch_num}_{counter:05}_{file_extension}"
            
            img.save(os.path.join(full_output_folder, file), format=format, **save_kwargs)
            
            results.append({
                "filename": file,
                "subfolder": subfolder,
                "type": self.type
            })
            counter += 1

        return { "ui": { "images": results } }
    
class LG_AccumulatePreview(SaveImage):
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.prefix_append = "_acc_" + ''.join(random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5))
        self.accumulated_images = []
        self.accumulated_masks = []
        self.counter = 0
        
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
                    "images": ("IMAGE", ),
                },
                "optional": {
                    "mask": ("MASK",),
                },
                "hidden": {
                    "prompt": "PROMPT", 
                    "extra_pnginfo": "EXTRA_PNGINFO",
                    "unique_id": "UNIQUE_ID"
                },
               }
    
    RETURN_TYPES = ("IMAGE", "MASK", "INT")
    RETURN_NAMES = ("images", "masks", "image_count")
    FUNCTION = "accumulate_images"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True, True, False)
    CATEGORY = CATEGORY_TYPE
    DESCRIPTION = "累计图像预览"

    def accumulate_images(self, images, mask=None, prompt=None, extra_pnginfo=None, unique_id=None):
        # 添加调试信息
        print(f"[AccumulatePreview] accumulate_images - 当前累积图片数量: {len(self.accumulated_images)}")
        print(f"[AccumulatePreview] accumulate_images - 新输入图片数量: {len(images)}")
        print(f"[AccumulatePreview] accumulate_images - unique_id: {unique_id}")
        
        filename_prefix = "accumulate"
        filename_prefix += self.prefix_append

        full_output_folder, filename, _, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )

        for image in images:
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

            file = f"{filename}_{self.counter:05}.png"
            img.save(os.path.join(full_output_folder, file), format="PNG")

            if len(image.shape) == 3:
                image = image.unsqueeze(0) 
            self.accumulated_images.append({
                "image": image,
                "info": {
                    "filename": file,
                    "subfolder": subfolder,
                    "type": self.type
                }
            })

            if mask is not None:
                if len(mask.shape) == 2:
                    mask = mask.unsqueeze(0)
                self.accumulated_masks.append(mask)
            else:
                self.accumulated_masks.append(None)
            
            self.counter += 1

        if not self.accumulated_images:
            return {"ui": {"images": []}, "result": ([], [], 0)}

        accumulated_tensors = []
        for item in self.accumulated_images:
            img = item["image"]
            if len(img.shape) == 3:  # [H, W, C]
                img = img.unsqueeze(0)  # 变成 [1, H, W, C]
            accumulated_tensors.append(img)

        accumulated_masks = [m for m in self.accumulated_masks if m is not None]
        
        ui_images = [item["info"] for item in self.accumulated_images]
        
        return {
            "ui": {"images": ui_images},
            "result": (accumulated_tensors, accumulated_masks, len(self.accumulated_images))
        }

# ============ Remote版本：通过文件保存和读取结果 ============

# 远程结果文件存储目录
try:
    REMOTE_RESULTS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status", "remote_results")
except:
    REMOTE_RESULTS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status", "remote_results")
os.makedirs(REMOTE_RESULTS_DIR, exist_ok=True)

# 状态文件存储目录（用于配置文件）
try:
    STATUS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status")
except:
    STATUS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "execution_status")
os.makedirs(STATUS_DIR, exist_ok=True)

# 线程局部存储：用于在执行时传递组名
_execution_context = threading.local()

def set_current_group_name(group_name):
    """设置当前执行的组名（用于线程局部存储）"""
    _execution_context.group_name = group_name

def get_current_group_name():
    """获取当前执行的组名（从线程局部存储）"""
    return getattr(_execution_context, 'group_name', None)

def _get_group_name_from_prompt(prompt=None, extra_pnginfo=None, unique_id=None):
    """从prompt或extra_pnginfo中获取组名，如果获取不到则从线程局部存储中获取"""
    group_name = ""
    
    # 处理prompt可能是列表的情况（INPUT_IS_LIST=True时）
    if prompt and isinstance(prompt, list):
        prompt = prompt[0] if prompt else None
    
    # 处理extra_pnginfo可能是列表的情况（INPUT_IS_LIST=True时）
    if extra_pnginfo and isinstance(extra_pnginfo, list):
        extra_pnginfo = extra_pnginfo[0] if extra_pnginfo else None
    
    # 处理unique_id可能是列表的情况
    if unique_id and isinstance(unique_id, list):
        unique_id = unique_id[0] if unique_id else None
    
    if prompt and unique_id:
        # 确保prompt是字典类型
        if isinstance(prompt, dict):
            # 从prompt中获取当前节点的配置
            node_data = prompt.get(str(unique_id), {})
            node_inputs = node_data.get("inputs", {})
            
            # 首先尝试从 _execution_group_name 获取组名（执行时自动添加的）
            if "_execution_group_name" in node_inputs:
                group_name = node_inputs.get("_execution_group_name", "")
            # 然后尝试从properties中获取组名
            elif "group_name" in node_inputs:
                group_name = node_inputs.get("group_name", "")
    
    # 如果从prompt中获取不到，尝试从extra_pnginfo中获取
    if not group_name and extra_pnginfo:
        # 确保extra_pnginfo是字典类型
        if isinstance(extra_pnginfo, dict):
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
    
    # 如果从prompt和extra_pnginfo中都无法获取，尝试从线程局部存储中获取（用于远端执行）
    if not group_name:
        group_name = get_current_group_name()
    
    return group_name if group_name else ""

def _get_safe_filename(name):
    """生成安全的文件名（移除特殊字符）"""
    safe_name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' '))
    safe_name = safe_name.replace(' ', '_')  # 将空格替换为下划线
    return safe_name

class LG_RemoteTextSender:
    """远程文本发送器：将文本保存到配置文件中（用于远端服务器异步执行）"""
    def __init__(self):
        self.status_dir = STATUS_DIR
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "", "tooltip": "要发送的文本内容"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
            },
            "optional": {
                "signal_opt": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"})
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (any_typ,)
    RETURN_NAMES = ("signal",)
    FUNCTION = "save_text"
    CATEGORY = CATEGORY_TYPE
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(s, text, link_id, prompt=None, extra_pnginfo=None, unique_id=None):
        # 获取组名用于hash计算
        group_name = _get_group_name_from_prompt(prompt, extra_pnginfo, unique_id)
        # 计算hash
        hash_value = hash(str(text) + str(group_name) + str(link_id))
        return hash_value

    def save_text(self, text, link_id, signal_opt=None, prompt=None, extra_pnginfo=None, unique_id=None):
        text = text[0] if isinstance(text, list) else text
        link_id = link_id[0] if isinstance(link_id, list) else link_id
        
        # 处理 signal_opt（INPUT_IS_LIST=True 时，输入是列表）
        if signal_opt is not None:
            # signal_opt 本身可能就是列表（因为 INPUT_IS_LIST=True）
            if isinstance(signal_opt, list):
                signal_output = signal_opt  # 直接返回列表
            else:
                signal_output = [signal_opt]  # 包装成列表
        else:
            signal_output = [None]  # OUTPUT_IS_LIST=(True,) 需要返回列表
        
        # 从节点属性中获取组名
        group_name = _get_group_name_from_prompt(prompt, extra_pnginfo, unique_id)
        
        if not group_name:
            print(f"[RemoteTextSender] 警告：组名为空，使用默认组名 'default'")
            group_name = "default"
        
        # 处理文本
        save_text = text if text else ""
        
        # 按组名和link_id创建配置文件
        safe_group_name = _get_safe_filename(group_name)
        config_filename = f"{safe_group_name}_{link_id}.json"
        config_file_path = os.path.join(self.status_dir, config_filename)
        
        try:
            # 确保目录存在
            os.makedirs(self.status_dir, exist_ok=True)
            
            # 如果配置文件已存在，保留created_at字段
            created_at = time.time()
            if os.path.exists(config_file_path):
                try:
                    with open(config_file_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    # 保留原有的created_at时间
                    if "created_at" in existing_data:
                        created_at = existing_data["created_at"]
                except:
                    pass
            
            # 构建配置文件数据（OUTPUT_NODE执行时任务已完成）
            config_data = {
                "group_name": group_name,
                "link_id": link_id,
                "result_text": save_text,
                "completed": True,  # OUTPUT_NODE执行时任务已完成
                "completed_at": time.time(),
                "created_at": created_at
            }
            
            # 写入配置文件
            temp_file = config_file_path + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            # 原子性替换
            if os.path.exists(config_file_path):
                os.remove(config_file_path)
            os.rename(temp_file, config_file_path)
            
            print(f"[RemoteTextSender] 保存文本到配置文件 (group_name={group_name}, link_id={link_id}): {config_file_path}, {len(save_text)} 字符")
        except Exception as e:
            print(f"[RemoteTextSender] 保存配置文件失败: {str(e)}")
            import traceback
            traceback.print_exc()
            # 清理临时文件
            temp_file = config_file_path + ".tmp"
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
        
        # OUTPUT_IS_LIST=(True,) 要求返回列表
        return (signal_output,)

class LG_RemoteImageSenderPlus:
    """远程图像发送器：将图像保存到文件中（用于远端服务器异步执行）"""
    def __init__(self):
        self.results_dir = REMOTE_RESULTS_DIR
        self.compress_level = 1
        self.accumulated_results = []
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "要发送的图像"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID"}),
                "accumulate": ("BOOLEAN", {"default": False, "tooltip": "开启后将累积所有图像一起发送"}), 
                "preview_rgba": ("BOOLEAN", {"default": True, "tooltip": "开启后预览显示RGBA格式，关闭则预览显示RGB格式"}),
            },
            "optional": {
                "masks": ("MASK", {"tooltip": "要发送的遮罩"}),
                "signal_opt": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"})
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (any_typ,)
    RETURN_NAMES = ("signal",)
    FUNCTION = "save_images"
    CATEGORY = CATEGORY_TYPE
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True,)
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(s, images, link_id, accumulate, preview_rgba, masks=None, prompt=None, extra_pnginfo=None, unique_id=None):
        if isinstance(accumulate, list):
            accumulate = accumulate[0]
        
        if accumulate:
            return float("NaN") 
        
        # 获取组名用于hash计算
        group_name = _get_group_name_from_prompt(prompt, extra_pnginfo, unique_id)
        # 非积累模式下计算hash
        hash_value = hash(str(images) + str(masks) + str(group_name))
        return hash_value

    def save_images(self, images, link_id, accumulate, preview_rgba, masks=None, signal_opt=None, prompt=None, extra_pnginfo=None, unique_id=None):
        results = list()

        link_id = link_id[0] if isinstance(link_id, list) else link_id
        accumulate = accumulate[0] if isinstance(accumulate, list) else accumulate
        preview_rgba = preview_rgba[0] if isinstance(preview_rgba, list) else preview_rgba
        
        # 从节点属性中获取组名
        group_name = _get_group_name_from_prompt(prompt, extra_pnginfo, unique_id)
        
        if not group_name:
            print(f"[RemoteImageSenderPlus] 警告：组名为空，使用默认组名 'default'")
            group_name = "default"
        
        safe_group_name = _get_safe_filename(group_name)
        
        # 处理 signal_opt
        if signal_opt is not None:
            if isinstance(signal_opt, list):
                signal_output = signal_opt
            else:
                signal_output = [signal_opt]
        else:
            signal_output = [None]
        
        for idx, image_batch in enumerate(images):
            try:
                image = image_batch.squeeze()
                rgb_image = Image.fromarray(np.clip(255. * image.cpu().numpy(), 0, 255).astype(np.uint8))

                if masks is not None and idx < len(masks):
                    mask = masks[idx].squeeze()
                    mask_array = np.clip(255. * (1 - mask.cpu().numpy()), 0, 255).astype(np.uint8)
                    mask_img = Image.fromarray(mask_array, mode='L')
                    
                    # 确保 mask 尺寸与 rgb_image 匹配
                    if mask_img.size != rgb_image.size:
                        mask_img = mask_img.resize(rgb_image.size, Image.Resampling.LANCZOS)
                else:
                    mask_img = Image.new('L', rgb_image.size, 255)

                # 确保 mask_img 是 'L' 模式
                if mask_img.mode != 'L':
                    mask_img = mask_img.convert('L')

                r, g, b = rgb_image.convert('RGB').split()
                rgba_image = Image.merge('RGBA', (r, g, b, mask_img))

                # 保存RGBA格式到文件，文件名格式：{group_name}_{link_id}_{index}.png
                filename = f"{safe_group_name}_{link_id}_{idx}.png"
                file_path = os.path.join(self.results_dir, filename)
                
                try:
                    # 确保目录存在
                    os.makedirs(self.results_dir, exist_ok=True)
                    
                    # 保存图像
                    rgba_image.save(file_path, compress_level=self.compress_level)
                    
                    # 准备结果数据
                    original_result = {
                        "filename": filename,
                        "file_path": file_path,
                        "group_name": group_name,
                        "link_id": link_id,
                        "index": idx
                    }
                    
                    # 如果是要显示RGB预览
                    if not preview_rgba:
                        preview_filename = f"{safe_group_name}_{link_id}_{idx}_preview.jpg"
                        preview_path = os.path.join(self.results_dir, preview_filename)
                        rgb_image.save(preview_path, format="JPEG", quality=95)
                        # 将预览图添加到UI显示结果中
                        results.append({
                            "filename": preview_filename,
                            "file_path": preview_path,
                            "group_name": group_name,
                            "link_id": link_id,
                            "index": idx
                        })
                    else:
                        # 显示RGBA
                        results.append(original_result)

                    # 累积的始终是原始图像结果
                    if accumulate:
                        self.accumulated_results.append(original_result)
                    
                    print(f"[RemoteImageSenderPlus] 保存图像到文件 (group_name={group_name}, link_id={link_id}, index={idx}): {file_path}")

                except Exception as e:
                    print(f"[RemoteImageSenderPlus] 保存图像文件失败: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue

            except Exception as e:
                print(f"[RemoteImageSenderPlus] 处理图像 {idx+1} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                continue

        # 获取实际要保存的结果
        if accumulate:
            save_results = self.accumulated_results
        else:
            # 创建一个包含原始文件名的列表
            save_results = []
            for idx in range(len(results)):
                original_filename = f"{safe_group_name}_{link_id}_{idx}.png"
                save_results.append({
                    "filename": original_filename,
                    "file_path": os.path.join(self.results_dir, original_filename),
                    "group_name": group_name,
                    "link_id": link_id,
                    "index": idx
                })
        
        if save_results:
            print(f"[RemoteImageSenderPlus] 保存 {len(save_results)} 张图像到文件 (group_name={group_name}, link_id={link_id})")
        
        if not accumulate:
            self.accumulated_results = []
        
        return (signal_output,)

class LG_RemoteTextReceiver:
    """远程文本接收器：从配置文件中读取文本结果（用于本地服务器读取远端执行结果）"""
    def __init__(self):
        self.status_dir = STATUS_DIR
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "group_name": ("STRING", {"default": "", "multiline": False, "tooltip": "组名，用于查找配置文件"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID，需与发送端link_id匹配"}),
            },
            "optional": {
                "signal": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", any_typ)
    RETURN_NAMES = ("text", "signal")
    CATEGORY = CATEGORY_TYPE
    OUTPUT_IS_LIST = (False, False)
    FUNCTION = "load_text"
    INPUT_IS_LIST = False

    def load_text(self, group_name, link_id, signal=None, unique_id=None):
        # 处理输入（可能来自列表）
        if isinstance(group_name, list):
            group_name = group_name[0] if group_name else ""
        group_name = group_name if group_name else ""
        
        if isinstance(link_id, list):
            link_id = link_id[0] if link_id else 1
        link_id = link_id if link_id else 1
        
        # 处理 signal（原样输出）
        signal_output = signal
        
        if not group_name:
            print(f"[RemoteTextReceiver] 警告：组名为空，无法读取配置文件")
            return ("", signal_output)
        
        # 生成配置文件路径：{group_name}_{link_id}.json
        safe_group_name = _get_safe_filename(group_name)
        config_filename = f"{safe_group_name}_{link_id}.json"
        config_file_path = os.path.join(self.status_dir, config_filename)
        
        print(f"[RemoteTextReceiver] 尝试读取配置文件 (group_name={group_name}, link_id={link_id}): {config_file_path}")
        
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # 从配置文件中读取 result_text 字段
                text = config_data.get("result_text", "")
                print(f"[RemoteTextReceiver] 成功读取配置文件: {len(text)} 字符")
                return (text, signal_output)
            else:
                print(f"[RemoteTextReceiver] 配置文件不存在: {config_file_path}，返回空文本")
                return ("", signal_output)
        except Exception as e:
            print(f"[RemoteTextReceiver] 读取配置文件失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return ("", signal_output)
    
    @classmethod
    def IS_CHANGED(s, group_name, link_id, signal=None, unique_id=None):
        # 计算hash以检测变化
        hash_value = hash(str(group_name) + str(link_id))
        return hash_value

class LG_RemoteImageReceiverPlus:
    """远程图像接收器：从文件中读取图像结果（用于本地服务器读取远端执行结果）"""
    def __init__(self):
        self.results_dir = REMOTE_RESULTS_DIR
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "group_name": ("STRING", {"default": "", "multiline": False, "tooltip": "组名，用于查找文件"}),
                "link_id": ("INT", {"default": 1, "min": 0, "max": sys.maxsize, "step": 1, "tooltip": "发送端连接ID，需与发送端link_id匹配"}),
                "max_images": ("INT", {"default": 10, "min": 1, "max": 100, "step": 1, "tooltip": "最大读取图像数量"}),
            },
            "optional": {
                "mask_file": ("STRING", {"default": "", "multiline": False, "tooltip": "可选的遮罩文件名，用于加载已编辑的遮罩"}),
                "signal": (any_typ, {"tooltip": "信号输入，将在处理完成后原样输出"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", any_typ)
    RETURN_NAMES = ("images", "masks", "signal")
    CATEGORY = CATEGORY_TYPE
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "load_image"
    INPUT_IS_LIST = False

    def load_image(self, group_name, link_id, max_images, mask_file="", signal=None, unique_id=None):
        output_images = []
        output_masks = []
        
        # 处理输入
        if isinstance(group_name, list):
            group_name = group_name[0] if group_name else ""
        group_name = group_name if group_name else ""
        
        if isinstance(link_id, list):
            link_id = link_id[0] if link_id else 1
        link_id = link_id if link_id else 1
        
        if isinstance(max_images, list):
            max_images = max_images[0] if max_images else 10
        max_images = max_images if max_images else 10
        
        if isinstance(mask_file, list):
            mask_file = mask_file[0] if mask_file else ""
        mask_file = mask_file if mask_file else ""
        
        # 处理 signal（原样输出）
        signal_output = signal
        
        if not group_name:
            print(f"[RemoteImageReceiverPlus] 警告：组名为空，无法读取文件")
            empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
            return ([empty_image], [empty_mask], signal_output)
        
        # 生成文件名前缀：{group_name}_{link_id}_
        safe_group_name = _get_safe_filename(group_name)
        filename_prefix = f"{safe_group_name}_{link_id}_"
        
        print(f"[RemoteImageReceiverPlus] 尝试读取图像文件 (group_name={group_name}, link_id={link_id}, max_images={max_images})")
        
        try:
            # 查找所有匹配的图像文件
            image_files = []
            if os.path.exists(self.results_dir):
                for filename in os.listdir(self.results_dir):
                    # 匹配格式：{group_name}_{link_id}_{index}.png
                    if filename.startswith(filename_prefix) and filename.endswith('.png') and not filename.endswith('_preview.jpg'):
                        # 提取索引
                        try:
                            # 格式：{group_name}_{link_id}_{index}.png
                            base_name = filename[:-4]  # 去掉 .png
                            parts = base_name.split('_')
                            if len(parts) >= 3:
                                # 最后一部分应该是索引
                                index = int(parts[-1])
                                image_files.append((index, filename))
                        except:
                            continue
                
                # 按索引排序
                image_files.sort(key=lambda x: x[0])
                # 限制数量
                image_files = image_files[:max_images]
            
            if not image_files:
                print(f"[RemoteImageReceiverPlus] 未找到匹配的图像文件 (prefix={filename_prefix})")
                empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
                return ([empty_image], [empty_mask])
            
            print(f"[RemoteImageReceiverPlus] 找到 {len(image_files)} 个图像文件")
            
            # 解析遮罩文件名（支持逗号分隔的多个文件）
            if isinstance(mask_file, str):
                mask_files = [x.strip() for x in mask_file.split(',') if x.strip()]
            elif isinstance(mask_file, list):
                mask_files = [str(m).strip() for m in mask_file if m]
            else:
                mask_files = [str(mask_file).strip()] if mask_file else []
            
            for idx, (file_index, img_filename) in enumerate(image_files):
                try:
                    img_path = os.path.join(self.results_dir, img_filename)
                    
                    if not os.path.exists(img_path):
                        print(f"[RemoteImageReceiverPlus] 文件不存在: {img_path}")
                        continue
                    
                    img = node_helpers.pillow(Image.open, img_path)
                    
                    w, h = None, None
                    frame_images = []
                    frame_masks = []
                    
                    # 处理图像序列（如 GIF、多帧 PNG 等）
                    for i in ImageSequence.Iterator(img):
                        i = node_helpers.pillow(ImageOps.exif_transpose, i)
                        
                        if i.mode == 'I':
                            i = i.point(lambda i: i * (1 / 255))
                        rgb_image = i.convert("RGB")
                        
                        if len(frame_images) == 0:
                            w = rgb_image.size[0]
                            h = rgb_image.size[1]
                        
                        if rgb_image.size[0] != w or rgb_image.size[1] != h:
                            continue
                        
                        image_tensor = np.array(rgb_image).astype(np.float32) / 255.0
                        image_tensor = torch.from_numpy(image_tensor)[None,]
                        
                        # 处理遮罩
                        if 'A' in i.getbands():
                            mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                            mask = 1. - torch.from_numpy(mask)
                        elif i.mode == 'P' and 'transparency' in i.info:
                            mask = np.array(i.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                            mask = 1. - torch.from_numpy(mask)
                        else:
                            mask = torch.zeros((rgb_image.size[1], rgb_image.size[0]), dtype=torch.float32, device="cpu")
                        
                        frame_images.append(image_tensor)
                        frame_masks.append(mask.unsqueeze(0))
                        
                        if img.format == "MPO":
                            break  # ignore all frames except the first one for MPO format
                    
                    # 如果提供了遮罩文件，尝试加载它（覆盖alpha通道）
                    if mask_files and idx < len(mask_files) and w is not None and h is not None:
                        mask_file_path_str = mask_files[idx]
                        
                        # 尝试从results_dir加载遮罩文件
                        mask_file_path = os.path.join(self.results_dir, mask_file_path_str)
                        if not os.path.exists(mask_file_path):
                            # 如果不在results_dir，尝试从input或temp目录
                            temp_dir = folder_paths.get_temp_directory()
                            input_dir = folder_paths.get_input_directory()
                            mask_file_path = os.path.join(temp_dir, mask_file_path_str)
                            if not os.path.exists(mask_file_path):
                                mask_file_path = os.path.join(input_dir, mask_file_path_str)
                        
                        if os.path.exists(mask_file_path):
                            try:
                                mask_img = node_helpers.pillow(Image.open, mask_file_path)
                                
                                # 处理遮罩文件（可能是单帧或多帧）
                                mask_frames = []
                                for mask_frame in ImageSequence.Iterator(mask_img):
                                    mask_frame = node_helpers.pillow(ImageOps.exif_transpose, mask_frame)
                                    
                                    # 提取遮罩通道
                                    if mask_frame.mode == 'RGBA':
                                        mask_array = np.array(mask_frame.getchannel('A')).astype(np.float32) / 255.0
                                    elif mask_frame.mode == 'L':
                                        mask_array = np.array(mask_frame).astype(np.float32) / 255.0
                                    elif mask_frame.mode == 'P' and 'transparency' in mask_frame.info:
                                        mask_array = np.array(mask_frame.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                                    else:
                                        mask_array = np.array(mask_frame.convert('L')).astype(np.float32) / 255.0
                                    
                                    # 调整遮罩大小以匹配图像
                                    if mask_array.shape[0] != h or mask_array.shape[1] != w:
                                        mask_pil = Image.fromarray((mask_array * 255).astype(np.uint8))
                                        mask_pil = mask_pil.resize((w, h), Image.LANCZOS)
                                        mask_array = np.array(mask_pil).astype(np.float32) / 255.0
                                    
                                    mask_tensor = torch.from_numpy(mask_array)
                                    mask_tensor = 1.0 - mask_tensor  # 反转遮罩（ComfyUI中白色=透明区域）
                                    mask_frames.append(mask_tensor.unsqueeze(0))
                                    
                                    if mask_img.format == "MPO":
                                        break
                                
                                # 如果遮罩文件有多个帧，使用第一个；否则使用第一个遮罩
                                if mask_frames:
                                    # 更新所有帧的遮罩（如果遮罩文件只有一帧，则应用到所有图像帧）
                                    if len(mask_frames) == 1:
                                        # 单个遮罩应用到所有帧
                                        for frame_idx in range(len(frame_masks)):
                                            frame_masks[frame_idx] = mask_frames[0]
                                    else:
                                        # 多帧遮罩，按帧对应
                                        for frame_idx in range(min(len(frame_masks), len(mask_frames))):
                                            frame_masks[frame_idx] = mask_frames[frame_idx]
                                
                                print(f"[RemoteImageReceiverPlus] 已加载遮罩文件: {mask_files[idx]}")
                            except Exception as e:
                                print(f"[RemoteImageReceiverPlus] 加载遮罩文件失败: {str(e)}")
                                import traceback
                                traceback.print_exc()
                    
                    # 合并多帧图像
                    if len(frame_images) > 1:
                        output_image = torch.cat(frame_images, dim=0)
                        output_mask = torch.cat(frame_masks, dim=0)
                    elif len(frame_images) == 1:
                        output_image = frame_images[0]
                        output_mask = frame_masks[0]
                    else:
                        # 如果没有有效帧，创建空图像和遮罩
                        output_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                        output_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
                    
                    output_images.append(output_image)
                    output_masks.append(output_mask)
                    
                except Exception as e:
                    print(f"[RemoteImageReceiverPlus] 处理文件 {img_filename} 时出错: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            if not output_images:
                empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
                return ([empty_image], [empty_mask], signal_output)
            
            print(f"[RemoteImageReceiverPlus] 成功加载 {len(output_images)} 张图像")
            return (output_images, output_masks, signal_output)

        except Exception as e:
            print(f"[RemoteImageReceiverPlus] 处理图像时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            empty_image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            empty_mask = torch.zeros((1, 64, 64), dtype=torch.float32)
            return ([empty_image], [empty_mask], signal_output)
    
    @classmethod
    def IS_CHANGED(s, group_name, link_id, max_images, mask_file="", signal=None, unique_id=None):
        # 计算hash以检测变化
        hash_value = hash(str(group_name) + str(link_id) + str(max_images) + str(mask_file))
        return hash_value