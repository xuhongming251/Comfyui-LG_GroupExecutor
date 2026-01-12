from .py.lgutils import *
from .py.trans import *

WEB_DIRECTORY = "web"

NODE_CLASS_MAPPINGS = {
    "GroupExecutorSingle": GroupExecutorSingle,
    "GroupExecutorSender": GroupExecutorSender,
    "GroupExecutorRepeater": GroupExecutorRepeater,
    "GroupExecutorWaitAll": GroupExecutorWaitAll,
    "GroupExecutorExtractResult": GroupExecutorExtractResult,
    "LG_ImageSender": LG_ImageSender,
    "LG_ImageSenderPlus": LG_ImageSenderPlus,
    "LG_ImageReceiver": LG_ImageReceiver,
    "LG_ImageReceiverPlus": LG_ImageReceiverPlus,
    "LG_TextSender": LG_TextSender,
    "LG_TextReceiver": LG_TextReceiver,
    "LG_RemoteTextSender": LG_RemoteTextSender,
    "LG_RemoteImageSenderPlus": LG_RemoteImageSenderPlus,
    "LG_RemoteTextReceiverPlus": LG_RemoteTextReceiverPlus,
    "LG_RemoteImageReceiverPlus": LG_RemoteImageReceiverPlus,
    "ImageListSplitter": ImageListSplitter,
    "MaskListSplitter": MaskListSplitter,
    "ImageListRepeater": ImageListRepeater,
    "MaskListRepeater": MaskListRepeater,
    "LG_FastPreview": LG_FastPreview,
    "LG_AccumulatePreview": LG_AccumulatePreview,

}
NODE_DISPLAY_NAME_MAPPINGS = {
    "GroupExecutorSingle": "🎈GroupExecutorSingle",
    "GroupExecutorSender": "🎈GroupExecutorSender",
    "GroupExecutorRepeater": "🎈GroupExecutorRepeater",
    "GroupExecutorWaitAll": "🎈GroupExecutorWaitAll",
    "GroupExecutorExtractResult": "🎈GroupExecutorExtractResult",
    "LG_ImageSender": "🎈LG_ImageSender",
    "LG_ImageSenderPlus": "🎈LG_ImageSenderPlus",
    "LG_ImageReceiver": "🎈LG_ImageReceiver",
    "LG_ImageReceiverPlus": "🎈LG_ImageReceiverPlus",
    "LG_TextSender": "🎈LG_TextSender",
    "LG_TextReceiver": "🎈LG_TextReceiver",
    "LG_RemoteTextSender": "🎈LG_RemoteTextSender",
    "LG_RemoteImageSenderPlus": "🎈LG_RemoteImageSenderPlus",
    "LG_RemoteTextReceiverPlus": "🎈LG_RemoteTextReceiverPlus",
    "LG_RemoteImageReceiverPlus": "🎈LG_RemoteImageReceiverPlus",
    "ImageListSplitter": "🎈List-Image-Splitter",
    "MaskListSplitter": "🎈List-Mask-Splitter",
    "ImageListRepeater": "🎈List-Image-Repeater",
    "MaskListRepeater": "🎈List-Mask-Repeater",
    "LG_FastPreview": "🎈LG_FastPreview",
    "LG_AccumulatePreview": "🎈LG_AccumulatePreview",
}
