## post.py
import time
import numpy as np
import cv2
# from config_v4 import *
# from config_v5 import *
from config import *

def xywh2xyxy(x):
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2  # top left x
    y[..., 1] = x[..., 1] - x[..., 3] / 2  # top left y
    y[..., 2] = x[..., 0] + x[..., 2] / 2  # bottom right x
    y[..., 3] = x[..., 1] + x[..., 3] / 2  # bottom right y
    return y

def xyxy2xywh(x):
    y = np.copy(x)
    y[..., 0] = (x[..., 0] + x[..., 2]) / 2  # x center
    y[..., 1] = (x[..., 1] + x[..., 3]) / 2  # y center
    y[..., 2] = x[..., 2] - x[..., 0]  # width
    y[..., 3] = x[..., 3] - x[..., 1]  # height
    return y


def xyxy2xywhn(x, w=1, h=1, clip=False, eps=0.0):
    if clip:
        clip_boxes(x, (h - eps, w - eps))  # warning: inplace clip
    y = np.copy(x)
    y[..., 0] = ((x[..., 0] + x[..., 2]) / 2) / w  # x center
    y[..., 1] = ((x[..., 1] + x[..., 3]) / 2) / h  # y center
    y[..., 2] = (x[..., 2] - x[..., 0]) / w  # width
    y[..., 3] = (x[..., 3] - x[..., 1]) / h  # height
    return y


def xywhn2xyxy(x, w=1, h=1, clip=False, eps=0.0):
    y = np.copy(x)
    y[..., 0] = (x[..., 0] - x[..., 2] / 2)  # top left x
    y[..., 1] = (x[..., 1] - x[..., 3] / 2)  # top left y
    y[..., 2] = (x[..., 0] + x[..., 2] / 2)  # bottom right x
    y[..., 3] = (x[..., 1] + x[..., 3] / 2)  # bottom right y
    y = np.clip(y, 0,1)
    y[..., [0,2]] = y[..., [0,2]]*w
    y[..., [1,3]] = y[..., [1,3]]*h
    return y

# def xywhn2xyxy(x, w=1, h=1, clip=False, eps=0.0):
#     y = np.copy(x)
#     y = np.clip(y, 0,1)
#     y[..., 0] = (x[..., 0] - x[..., 2] / 2) * w  # top left x
#     y[..., 1] = (x[..., 1] - x[..., 3] / 2) * h  # top left y
#     y[..., 2] = (x[..., 0] + x[..., 2] / 2) * w  # bottom right x
#     y[..., 3] = (x[..., 1] + x[..., 3] / 2) * h  # bottom right y
#     return y


def clip_boxes(boxes, shape):
    boxes[..., [0, 2]] = boxes[..., [0, 2]].clip(0, shape[1])  # x1, x2
    boxes[..., [1, 3]] = boxes[..., [1, 3]].clip(0, shape[0])  # y1, y2


def scale_boxes(img1_shape, boxes, img0_shape, ratio_pad=None):
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    boxes[..., [0, 2]] -= pad[0]  # x padding
    boxes[..., [1, 3]] -= pad[1]  # y padding
    boxes[..., :4] /= gain
    clip_boxes(boxes, img0_shape)
    return boxes

def crop_mask(masks, boxes):
    n, h, w = masks.shape
    x1, y1, x2, y2 = np.split(boxes[:, :, None], 4, axis=1)
    r = np.arange(w, dtype=np.float32)[None, None, :]  # rows shape(1,w,1)
    c = np.arange(h, dtype=np.float32)[None, :, None]  # cols shape(h,1,1)

    return masks * ((r >= x1) * (r < x2) * (c >= y1) * (c < y2))

def sigmoid(x): 
    return 1.0/(1+np.exp(-x))

def process_mask(protos, masks_in, bboxes, shape):

    c, mh, mw = protos.shape  # CHW
    ih, iw = shape
    masks = sigmoid(masks_in @ protos.reshape(c, -1)).reshape(-1, mh, mw)  # CHW 【lulu】

    downsampled_bboxes = bboxes.copy()
    downsampled_bboxes[:, 0] *= mw / iw
    downsampled_bboxes[:, 2] *= mw / iw
    downsampled_bboxes[:, 3] *= mh / ih
    downsampled_bboxes[:, 1] *= mh / ih

    masks = crop_mask(masks, downsampled_bboxes)  # CHW
    masks = np.transpose(masks, [1,2,0])
    # masks = cv2.resize(masks, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    masks = cv2.resize(masks, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
    masks = np.reshape(masks,(masks.shape[0], masks.shape[1], -1))  ## liulu
    
    masks = np.transpose(masks, [2,0,1])

    return np.where(masks>0.5,masks,0)

def nms(bboxes, scores, threshold=0.5):
    x1 = bboxes[:, 0]
    y1 = bboxes[:, 1]
    x2 = bboxes[:, 2]
    y2 = bboxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1: break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, (xx2 - xx1))
        h = np.maximum(0.0, (yy2 - yy1))
        inter = w * h

        iou = inter / (areas[i] + areas[order[1:]] - inter)
        ids = np.where(iou <= threshold)[0]
        order = order[ids + 1]

    return keep


def non_max_suppression(
        prediction,
        conf_thres=0.25,
        iou_thres=0.45,
        classes=None,
        agnostic=False,
        multi_label=False,
        labels=(),
        max_det=300,
        nc=0,  # number of classes (optional)
):

    # Checks
    assert 0 <= conf_thres <= 1, f'Invalid Confidence threshold {conf_thres}, valid values are between 0.0 and 1.0'
    assert 0 <= iou_thres <= 1, f'Invalid IoU {iou_thres}, valid values are between 0.0 and 1.0'

    #【lulu】prediction.shape[1]：box + cls + num_masks
    bs = prediction.shape[0]              # batch size
    nc = nc or (prediction.shape[1] - 4)  # number of classes
    nm = prediction.shape[1] - nc - 4     # num_masks
    mi = 4 + nc                           # mask start index
    xc = np.max(prediction[:, 4:mi], axis=1) > conf_thres ## 【lulu】

    # Settings
    # min_wh = 2  # (pixels) minimum box width and height
    max_wh = 7680  # (pixels) maximum box width and height
    max_nms = 30000  # maximum number of boxes into torchvision.ops.nms()
    time_limit = 0.5 + 0.05 * bs  # seconds to quit after
    multi_label &= nc > 1  # multiple labels per box (adds 0.5ms/img)

    t = time.time()
    output = [np.zeros((0,6 + nm))] * bs ## 【lulu】
    for xi, x in enumerate(prediction):  # image index, image inference
        # Apply constraints
        # x[((x[:, 2:4] < min_wh) | (x[:, 2:4] > max_wh)).any(1), 4] = 0  # width-height
        x = np.transpose(x,[1,0])[xc[xi]] ## 【lulu】

        # If none remain process next image
        if not x.shape[0]: continue

        # Detections matrix nx6 (xyxy, conf, cls)
        box, cls, mask = np.split(x, [4, 4+nc], axis=1) ## 【lulu】
        box = xywh2xyxy(box)  # center_x, center_y, width, height) to (x1, y1, x2, y2)

        j = np.argmax(cls, axis=1)  ## 【lulu】
        conf = cls[np.array(range(j.shape[0])), j].reshape(-1,1)
        x = np.concatenate([box, conf, j.reshape(-1,1), mask], axis=1)[conf.reshape(-1,)>conf_thres]

        # Check shape
        n = x.shape[0]  # number of boxes
        if not n: continue
        x = x[np.argsort(x[:, 4])[::-1][:max_nms]]  # sort by confidence and remove excess boxes 【lulu】

        # Batched NMS
        c = x[:, 5:6] * max_wh  # classes ## 乘以的原因是将相同类别放置统一尺寸区间进行nms
        boxes, scores = x[:, :4] + c, x[:, 4]  # boxes (offset by class), scores
        i = nms(boxes, scores, iou_thres) ## 【lulu】
        i = i[:max_det]  # limit detections

        output[xi] = x[i]
        if (time.time() - t) > time_limit:
            # LOGGER.warning(f'WARNING ⚠️ NMS time limit {time_limit:.3f}s exceeded')
            break  # time limit exceeded

    return output

def clip_coords(coords, shape):
    """
    Clip line coordinates to the image boundaries.

    Args:
        coords (torch.Tensor | numpy.ndarray): A list of line coordinates.
        shape (tuple): A tuple of integers representing the size of the image in the format (height, width).

    Returns:
        (None): The function modifies the input `coordinates` in place, by clipping each coordinate to the image boundaries.
    """

    coords[..., 0] = coords[..., 0].clip(0, shape[1])  # x
    coords[..., 1] = coords[..., 1].clip(0, shape[0])  # y    

def scale_coords(img1_shape, coords, img0_shape, ratio_pad=None, normalize=False, padding=True):
    """
    Rescale segment coordinates (xyxy) from img1_shape to img0_shape

    Args:
      img1_shape (tuple): The shape of the image that the coords are from.
      coords (torch.Tensor): the coords to be scaled
      img0_shape (tuple): the shape of the image that the segmentation is being applied to
      ratio_pad (tuple): the ratio of the image size to the padded image size.
      normalize (bool): If True, the coordinates will be normalized to the range [0, 1]. Defaults to False
      padding (bool): If True, assuming the boxes is based on image augmented by yolo style. If False then do regular
        rescaling.

    Returns:
      coords (torch.Tensor): the segmented image.
    """
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    if padding:
        coords[..., 0] -= pad[0]  # x padding
        coords[..., 1] -= pad[1]  # y padding
    coords[..., 0] /= gain
    coords[..., 1] /= gain
    clip_coords(coords, img0_shape)
    if normalize:
        coords[..., 0] /= img0_shape[1]  # width
        coords[..., 1] /= img0_shape[0]  # height
    return coords


def postprocess(preds, OBJ_THRESH, NMS_THRESH, classes=None):
    # print(OBJ_THRESH,NMS_THRESH)
    # print(preds[0].shape)
    pred = non_max_suppression(preds[0],
                                OBJ_THRESH,
                                NMS_THRESH,
                                agnostic=False,
                                max_det=300,
                                nc=classes,
                                classes=None)                            

    return pred[0][..., :6]




def make_anchors(feats_shape, strides, grid_cell_offset=0.5):
    """Generate anchors from features."""
    anchor_points, stride_tensor = [], []
    assert feats_shape is not None
    dtype_ = np.float64
    for i, stride in enumerate(strides):
        _, _, h, w = feats_shape[i]
        sx = np.arange(w, dtype=dtype_) + grid_cell_offset  # shift x
        sy = np.arange(h, dtype=dtype_) + grid_cell_offset  # shift y

        sy, sx = np.meshgrid(sy, sx, indexing='ij') 
        anchor_points.append(np.stack((sx, sy), -1).reshape(-1, 2))
        stride_tensor.append(np.full((h * w, 1), stride, dtype=dtype_))
    return np.concatenate(anchor_points), np.concatenate(stride_tensor)


def dist2bbox(distance, anchor_points, xywh=True, dim=-1):
    """Transform distance(ltrb) to box(xywh or xyxy)."""
    lt, rb = np.split(distance, 2, dim)
    x1y1 = anchor_points - lt
    x2y2 = anchor_points + rb
    if xywh:
        c_xy = (x1y1 + x2y2) / 2
        wh = x2y2 - x1y1
        return np.concatenate((c_xy, wh), dim)  # xywh bbox
    return np.concatenate((x1y1, x2y2), dim)  # xyxy bbox


def draw(image_, boxes_, CLASSES):   
    ### 画box===============
    image = image_.copy()
    boxes = boxes_.copy()
    w, h = image.shape[1], image.shape[0]
    for lb_ in boxes:
        lb = (lb_*[1, w,h,w,h, 100]).astype(int)
        # lb = lb.astype(int)
        start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2)
        end_point = (lb[1] + lb[3]//2, lb[2] + lb[4]//2)
        cv2.rectangle(image, start_point, end_point, (255,0,0), 2)
        if lb[0]!=NAME2ID["normal"]:
            cv2.putText(image, f"{CLASSES[lb[0]]}_{lb[5]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        else:
            cv2.putText(image, f"{CLASSES[lb[0]]}_{lb[5]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        # cv2.putText(image, f"{lb[5]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
    return image
   

