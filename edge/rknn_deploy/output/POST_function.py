import cv2
import shutil
# from config_v4 import *
from config import *
import POST_decoder as postdecoder


def draw(image_, boxes_, CLASSES, Method, string):
    # # 画box===============
    image = image_.copy()
    boxes = boxes_.copy()
    w,h = image.shape[1],image.shape[0]
    cv2.putText(image, f"{string}", (40,40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

    if Method=="box":
        for lb_ in boxes:
            lb = (lb_*[1, w,h,w,h, 100]).astype(int)
            # lb = (lb_*[1, 100, w,h,w,h]).astype(int)
            # lb = lb.astype(int)
            start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2)
            end_point = (lb[1] + lb[3]//2, lb[2] + lb[4]//2)

            cv2.rectangle(image, start_point, end_point, (255,0,0), 2)

            # if lb[2] - lb[4]//2>50:
            #     start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2-50)
            # else:
            #     start_point = (lb[1] - lb[3]//2, lb[2] + lb[4]//2)

            if lb[0]!=NAME2ID["normal"]:
                cv2.putText(image, f"{lb[5]}_{CLASSES[lb[0]]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            else:
                # start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2-25)
                cv2.putText(image, f"{lb[5]}_-----",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    if Method=="class":
        for lb_ in boxes:
            lb = (lb_*[w,h,w,h,1,100,1,100]).astype(int)
            # lb = lb.astype(int)
            start_point = (lb[0] - lb[2]//2, lb[1] - lb[3]//2)
            end_point = (lb[0] + lb[2]//2, lb[1] + lb[3]//2)
            cv2.rectangle(image, start_point, end_point, (255,0,0), 2)

            # if lb[2] - lb[4]//2>50:
            #     start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2-50)
            # else:
            #     start_point = (lb[1] - lb[3]//2, lb[2] + lb[4]//2)
            
            cv2.putText(image, f"B_{lb[5]}_{CLASSES[lb[4]]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            # start_point = (lb[0] - lb[2]//2, lb[1] - lb[3]//2-25)
            cv2.putText(image, f"C_{lb[7]}_{CLASSES[lb[6]]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    if Method=="post":
        for lb_ in boxes:
            lb = (lb_*[1, w,h,w,h, 100]).astype(int)
            if lb[0]==-1: continue

            # lb = lb.astype(int)
            start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2)
            end_point = (lb[1] + lb[3]//2, lb[2] + lb[4]//2)
            cv2.rectangle(image, start_point, end_point, (255,0,0), 2)
            
            # if lb[2] - lb[4]//2>50:
            #     start_point = (lb[1] - lb[3]//2, lb[2] - lb[4]//2-50)
            # else:
            #     start_point = (lb[1] - lb[3]//2, lb[2] + lb[4]//2)

            if lb[0] not in [NAME2ID["normal"], NAME2ID["else"]] and lb[5]>=85:
                cv2.putText(image, f"F_{lb[5]}_{CLASSES[lb[0]]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)  ## 红色
            else:
                cv2.putText(image, f"F_{lb[5]}_{CLASSES[lb[0]]}",  start_point, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)


    return image


def post_with_class(pred, ):

    # MDFF test0_9
    # for i, p in enumerate(pred):
    #     if p[4]==NAME2ID["blanket"]:  ## 电子秤错检为地毯
    #         p[4] = p[6]
    #     if p[6]==NAME2ID["blanket"]:  ## 电子秤错检为地毯
    #         p[6] = p[4]

    ## merge test6 =====================
    THead_out = {
    #              : [[app显示, 检测未确定, 低置信度避障], 分类阈值]],
    "weight_scale" : [[0.85, 0.6, 0.55], 0.97],
    "wire"         : [[0.85, 0.6, 0.55], 0.97],
    "shoe"         : [[0.85, 0.3, 0.45], 0.97],
    "socks"        : [[0.85, 0.3, 0.45], 0.97],

    "pet"                : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "pet_feces"          : [[0.85, 0.3, 0.45], 0.97],
    "metal_chair_foot"   : [[0.85, 0.3, 0.45], 0.97],##未调试
    "chair_base"         : [[0.85, 0.3, 0.45], 0.97],

    "swivel_chair"    : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "blanket"         : [[0.85, 0.6, 0.5], 0.97], ##未调试
    "charger"         : [[0.85, 0.3, 0.45], 0.97],
    "trash_can"       : [[0.85, 0.3, 0.4], 0.97], ##未调试
    "tissue"          : [[0.85, 0.3, 0.4], 0.97],
    "plastic_toy"     : [[0.85, 0.3, 0.4], 0.97], ##未调试
    "else"            : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "normal"          : [[0.85, 0.3, 0.45], 0.97],  ##未调试
    "keys"            : [[0.85, 0.3, 0.45], 0.97]  ##未调试
    }
 
    for pd in pred:
        if pd[4] == -1 : continue	
        if ID2NAME[pd[4]] not in list(THead_out.keys()):continue
        if pd[5] >= THead_out[ID2NAME[pd[4]]][0][0]: 
            continue
        elif pd[5] >= THead_out[ID2NAME[pd[4]]][0][1] and pd[4] == pd[6] and pd[7]>=THead_out[ID2NAME[pd[4]]][1]:
                pd[5] = pd[7]-(THead_out[ID2NAME[pd[4]]][1]-THead_out[ID2NAME[pd[4]]][0][0])
        else:
            if pd[5]<THead_out[ID2NAME[pd[4]]][0][2]:
                pd[4] = -1
  
    return pred


def post_with_class_V3(pred, ):

    # MDFF test0_9
    # for i, p in enumerate(pred):
    #     if p[4]==NAME2ID["blanket"]:  ## 电子秤错检为地毯
    #         p[4] = p[6]
    #     if p[6]==NAME2ID["blanket"]:  ## 电子秤错检为地毯
    #         p[6] = p[4]

    ## merge test6 =====================
    THead_out = {
    #              : [[app显示, 检测未确定, 低置信度避障], 分类阈值]],
    "weight_scale" : [[0.85, 0.6, 0.55], 0.97],
    "wire"         : [[0.85, 0.6, 0.55], 0.97],
    "shoe"         : [[0.85, 0.3, 0.45], 0.97],
    "socks"        : [[0.85, 0.3, 0.45], 0.97],

    "pet"                : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "pet_feces"          : [[0.85, 0.3, 0.45], 0.97],
    "metal_chair_foot"   : [[0.85, 0.3, 0.45], 0.97],##未调试
    "chair_base"         : [[0.85, 0.3, 0.45], 0.97],

    "swivel_chair"    : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "blanket"         : [[0.85, 0.6, 0.5], 0.97], ##未调试
    "charger"         : [[0.85, 0.3, 0.45], 0.97],
    "trash_can"       : [[0.85, 0.3, 0.4], 0.97], ##未调试
    "tissue"          : [[0.85, 0.3, 0.4], 0.97],
    "plastic_toy"     : [[0.85, 0.3, 0.4], 0.97], ##未调试
    "else"            : [[0.85, 0.3, 0.45], 0.97], ##未调试
    "normal"             : [[0.85, 0.3, 0.45], 0.97],  ##未调试
    "keys"            : [[0.85, 0.3, 0.45], 0.97]  ##未调试
    }
 
    for pd in pred:
        pd[4] = int(pd[4])
        if pd[4] == -1 : continue	
        if ID2NAME[pd[4]] not in list(THead_out.keys()):continue
        if pd[5] >= THead_out[ID2NAME[pd[4]]][0][0]: 
            continue
        elif pd[5] >= THead_out[ID2NAME[pd[4]]][0][1] and pd[4] == pd[6] and pd[7]>=THead_out[ID2NAME[pd[4]]][1]:
                pd[5] = pd[7]-(THead_out[ID2NAME[pd[4]]][1]-THead_out[ID2NAME[pd[4]]][0][0])
        else:
            if pd[5]<THead_out[ID2NAME[pd[4]]][0][2]:
                pd[4] = -1
  
    return pred



def down_line_box_V2(pred):

    ## merge test6 =====================
    THead_out = {
    "weight_scale"     : [0.85],
    "wire"             : [0.85],
    "shoe"             : [0.85],
    "socks"            : [0.85],

    "pet"                : [0.85], 
    "pet_feces"          : [0.85],
    "metal_chair_foot"   : [0.85],
    "chair_base"         : [0.85],

    "swivel_chair"    : [0], 
    "blanket"         : [0.8], 
    "charger"         : [0.85],
    "trash_can"       : [0.85], 
    "tissue"          : [0.85],
    "plastic_toy"     : [0.85], 
    "else"            : [0.85], 
    "normal"          : [0.85],  
    }

    pred_xyxy = postdecoder.xywhn2xyxy(pred[:,0:4])

    for i, p in enumerate(pred):
        if ID2NAME[p[4]] not in list(THead_out.keys()):continue

        if pred_xyxy[i,3]>(1-10/360):
            if p[5]<THead_out[ID2NAME[p[4]]]:
                p[4] = -1
            else:
                p[5] = min(0.84, p[5])
                p[7] = min(0.84, p[7])
    return pred

## 8392
## V1============================================

def post_process_V2_class(pred, no_count_id, Method):

    if pred.shape[0]==0:return pred 

    ### 2.贴底边的框的处理==
    pred = down_line_box_V2(pred)  ## MDFF TEST0_6

    ### 3.结合分类的处理====
    pred = post_with_class(pred)
    # ##==================

    pred = pred[:, [4,0,1,2,3,5]]
    for c in no_count_id:
        pred = pred[pred[:,0] != c]
    return pred



def post_process_V3_class(pred, no_count_id, Method):

    if pred.shape[0]==0:return pred 

    ### 2.贴底边的框的处理==
    pred = down_line_box_V2(pred)  ## MDFF TEST0_6

    ### 3.结合分类的处理====
    pred = post_with_class_V3(pred)
    # ##==================

    pred = pred[:, [4,0,1,2,3,5]]
    for c in no_count_id:
        pred = pred[pred[:,0] != c]
    pred = pred[pred[:,0] <15]

    return pred

def post_process_V2_box(pred, no_count_id, Method):
    return pred


## V1.2============================================
def post_process_V2(pred, no_count_id, Method):
    if Method=="class":
        if pred.shape[1]==6: return pred
        return post_process_V2_class(pred, no_count_id, Method)
    else:
        return post_process_V2_box(pred, no_count_id, Method)
        


def nms_special(data, thresh, normal_ID): 
    
    # data: class、x1、y1、x2、y2、以及score赋值 

    """Pure Python NMS baseline."""
    if data.shape[0]==0:
        return data, []
    data[data[:,0]!=normal_ID,5] +=1
    dets = data[:,1:]
    x1 = dets[:, 0] 
    y1 = dets[:, 1] 
    x2 = dets[:, 2] 
    y2 = dets[:, 3] 
    scores = dets[:, 4] 
    #每一个检测框的面积 
    areas = (x2 - x1 + 1) * (y2 - y1 + 1) 
    #按照score置信度降序排序 
    order = scores.argsort()[::-1] 
    keep = [] #保留的结果框集合 
    while order.size > 0: 
        i = order[0] 
        keep.append(i) #保留该类剩余box中得分最高的一个 
        #得到相交区域,左上及右下 
        xx1 = np.maximum(x1[i], x1[order[1:]]) 
        yy1 = np.maximum(y1[i], y1[order[1:]]) 
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]]) 
        #计算相交的面积,不重叠时面积为0 
        w = np.maximum(0.0, xx2 - xx1 + 1) 
        h = np.maximum(0.0, yy2 - yy1 + 1) 
        inter = w * h 
        #计算IoU：重叠面积 /（面积1+面积2-重叠面积） 
        ovr = inter / (areas[i] + areas[order[1:]] - inter) 
        #保留IoU小于阈值的box 
        inds = np.where(ovr <= thresh)[0] 
        order = order[inds + 1] #因为ovr数组的长度比order数组少一个,所以这里要将所有下标后移一位 
        # break
    data = data[keep]
    data[data[:,0]!=normal_ID,5] -=1
    return data, keep

    
    # data: class、x1、y1、x2、y2、以及score赋值 

    """Pure Python NMS baseline."""
    if data.shape[0]==0:
        return data, []
    
    mask = data[:,0]>=0
    for m in mask:
        mask = np.logical_and(mask, data[:,0]!=m)

    data[mask,5] +=1
    dets = data[:,1:]
    x1 = dets[:, 0] 
    y1 = dets[:, 1] 
    x2 = dets[:, 2] 
    y2 = dets[:, 3] 
    scores = dets[:, 4] 
    #每一个检测框的面积 
    areas = (x2 - x1 + 1) * (y2 - y1 + 1) 
    #按照score置信度降序排序 
    order = scores.argsort()[::-1] 
    keep = [] #保留的结果框集合 
    while order.size > 0: 
        i = order[0] 
        keep.append(i) #保留该类剩余box中得分最高的一个 
        #得到相交区域,左上及右下 
        xx1 = np.maximum(x1[i], x1[order[1:]]) 
        yy1 = np.maximum(y1[i], y1[order[1:]]) 
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]]) 
        #计算相交的面积,不重叠时面积为0 
        w = np.maximum(0.0, xx2 - xx1 + 1) 
        h = np.maximum(0.0, yy2 - yy1 + 1) 
        inter = w * h 
        #计算IoU：重叠面积 /（面积1+面积2-重叠面积） 
        ovr = inter / (areas[i] + areas[order[1:]] - inter) 
        #保留IoU小于阈值的box 
        inds = np.where(ovr <= thresh)[0] 
        order = order[inds + 1] #因为ovr数组的长度比order数组少一个,所以这里要将所有下标后移一位 
        # break
    data = data[keep]
    data[mask,5] -=1
    return data, keep