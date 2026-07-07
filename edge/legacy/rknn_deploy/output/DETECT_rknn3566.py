

import os
import urllib
import traceback
import time
import sys
import numpy as np
import cv2
# from rknn.api import RKNN
import POST_decoder as postdecoder
from POST_function import *

from rknn.api import RKNN

import glob
import onnxruntime as ort
import onnx
# import onnxruntime
# import post_pytorch as post_pytorch
import glob
import time

from config import *

os.environ["CUDA_VISIBLE_DEVICES"]="4" 

def gene_dataset_txt(DATASET_path, savefile):
    """获取量化图片文件名的列表, 并保存成txt, 用于量化时设置"""
    file_data = glob.glob(os.path.join(DATASET_path,"*.jpg"))
    with open(savefile, "w") as f:
        f.writelines("\n".join(file_data))


class DETECT_MODEL():
    def __init__(self) -> None:
        self.OBJ_THRESH = 0.5
        self.NMS_THRESH = 0.5
        # self.output_name = ["400","427"]
        self.output_name = ["/model.22/dfl/Reshape_1_output_0","/model.22/Sigmoid_output_0"]

        self.image_resize = (352,352)
        self.OFF = 0   ##352-224

    def run_model_cut(self, outputs, IMG_SIZE):

        a0 = outputs[0]
        stride = [8,16,32]
        x_shape = []
        for i in stride:
            x_shape.append([1,1,IMG_SIZE[1]//i,IMG_SIZE[0]//i])
        anchors, strides = (np.transpose(x, (1,0)) for x in postdecoder.make_anchors(x_shape, stride, 0.5))
        dbox = postdecoder.dist2bbox(a0, anchors[np.newaxis], xywh=True, dim=1) * strides
        outputs[0] = dbox
        outputs = [np.concatenate((outputs[0],outputs[1]), axis=1)]
        return outputs
    

    def load_and_export_rknnmodel(self, ONNX_MODEL, RKNN_MODEL, QUANTIZE_ON, DATASET=None):
        """
        rknn官方提供的onnx转rknn的代码, 并初始化仿真器运行环境
        需要手动设置的是图片的均值mean_values 和方差std_values
        """
        # Create RKNN object
        rknn = RKNN(verbose=True)

        # pre-process config
        print('--> Config model')
        rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]])
        print('done')

        # Load ONNX model
        print('--> Loading model')
        ret = rknn.load_onnx(model=ONNX_MODEL, outputs=self.output_name)
        if ret != 0:
            print('Load model failed!')
            exit(ret)
        print('done')

        # Build model
        print('--> Building model')

        # input()

        ret = rknn.build(do_quantization=QUANTIZE_ON, dataset=DATASET)
        if ret != 0:
            print('Build model failed!')
            exit(ret)
        print('done')
        
        # input()

        # Export RKNN model
        print('--> Export rknn model')
        ret = rknn.export_rknn(RKNN_MODEL)
        if ret != 0:
            print('Export rknn model failed!')
            exit(ret)
        print('done')

        # Init runtime environment
        print('--> Init runtime environment')
        ret = rknn.init_runtime()
        # ret = rknn.init_runtime('rk3566')
        if ret != 0:
            print('Init runtime environment failed!')
            exit(ret)
        print('done')

        self.rknn = rknn


    def run(self, image):

        image = cv2.resize(image, self.image_resize)[self.OFF:,:,:]
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        ## rk不需要，onnx的操作
        # im = np.transpose(img,(2,0,1)).astype(np.float32)[np.newaxis]/255.0

        outputs = self.rknn.inference(inputs=[img])
        outputs = self.run_model_cut(outputs, [img.shape[1],img.shape[0]])

        # outputs_rk3566 = load_RK3566_output("./OUT", output_name)
        # outputs = run_model_cut(outputs_rk3566, output_name, IMG_SIZE)

        boxes = postdecoder.postprocess(outputs, self.OBJ_THRESH, self.NMS_THRESH, classes=len(CLASSES)) 
        if len(boxes)!=0:
            boxes = boxes[:,[5, 0,1,2,3, 4]]
            boxes[:,[2,4]] = boxes[:,[2,4]]+self.OFF
            boxes[:, 1:] = postdecoder.xyxy2xywhn(boxes[:, 1:],w=self.image_resize[0], h=self.image_resize[1])
        return boxes




class CLASS_MODEL():
    def __init__(self) -> None:
        s=255
        self.TRAIN_MEAN = [0.5070751592371323*s, 0.48654887331495095*s, 0.4409178433670343*s]
        self.TRAIN_STD = [0.2673342858792401*s, 0.2564384629170883*s, 0.27615047132568404*s]
        self.image_resize = (96,96)
        self.output_name = ["output"]

    def load_and_export_rknnmodel(self, ONNX_MODEL, RKNN_MODEL, QUANTIZE_ON, DATASET=None):
        """
        rknn官方提供的onnx转rknn的代码, 并初始化仿真器运行环境
        需要手动设置的是图片的均值mean_values 和方差std_values
        """
        # Create RKNN object
        rknn = RKNN(verbose=True)

        # pre-process config
        print('--> Config model')
        rknn.config(mean_values=self.TRAIN_MEAN, std_values=self.TRAIN_STD)
        print('done')

        # Load ONNX model
        print('--> Loading model')
        ret = rknn.load_onnx(model=ONNX_MODEL, outputs=self.output_name)
        if ret != 0:
            print('Load model failed!')
            exit(ret)
        print('done')

        # Build model
        print('--> Building model')

        ret = rknn.build(do_quantization=QUANTIZE_ON, dataset=DATASET)
        if ret != 0:
            print('Build model failed!')
            exit(ret)
        print('done')

        # Export RKNN model
        print('--> Export rknn model')
        ret = rknn.export_rknn(RKNN_MODEL)
        if ret != 0:
            print('Export rknn model failed!')
            exit(ret)
        print('done')

        # Init runtime environment
        print('--> Init runtime environment')
        ret = rknn.init_runtime()
        # ret = rknn.init_runtime('rk3566')
        if ret != 0:
            print('Init runtime environment failed!')
            exit(ret)
        print('done')

        self.rknn = rknn


    def softmax_python(self, z):
        e_z = np.exp(z - np.max(z))
        return e_z / np.sum(e_z)


    def run(self, img):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # img = (img-self.TRAIN_MEAN)/self.TRAIN_STD
        # im = np.transpose(img,(2,0,1)).astype(np.float32)[np.newaxis]

        outputs = self.rknn.inference(inputs=[img])[0]
        outputs = self.softmax_python(outputs)
        cls, conf = np.argmax(outputs), np.max(outputs)
        return cls, conf
        



if __name__ == '__main__':

    CLASSES = CLASSNAME

    ####=====================================================
    PATH_DETECT_ONNX = "./MODEL/epoch260_352_352_yolov8n_0516.onnx"
    PATH_CLASS_ONNX = "./MODEL/CASE1_mobilenetv2_9_best.onnx"

    PATH_DETECT_RKNN = PATH_DETECT_ONNX.replace(".onnx", ".rknn")
    PATH_CLASS_RKNN = PATH_CLASS_ONNX.replace(".onnx", ".rknn")

    ## 动态测试集===========

    IAMGE_path   = "./DATASET/IMAGES_DETECT"
    Q_DETECT_path = makedir("./DATASET/IMAGES_Q_DETECT")
    Q_CLASS_path = makedir("./DATASET/IMAGES_Q_CLASS")
    RESULT_path  = makedir("./DATASET/RESULT_rk")

    ####=====================================================
    QUANTIZE_ON = True
    # QUANTIZE_ON = False
    dataset_detect_file = './dataset_detect.txt'
    dataset_class_file = './dataset_class.txt'

    if QUANTIZE_ON: 
        gene_dataset_txt(Q_DETECT_path, dataset_detect_file)
        gene_dataset_txt(Q_CLASS_path, dataset_class_file)

    DETECT = DETECT_MODEL()
    DETECT.load_and_export_rknnmodel(PATH_DETECT_ONNX, PATH_DETECT_RKNN, QUANTIZE_ON, dataset_detect_file)
    CLASS = CLASS_MODEL()
    CLASS.load_and_export_rknnmodel(PATH_CLASS_ONNX, PATH_CLASS_RKNN, QUANTIZE_ON, dataset_class_file)

    # exit()

    files = glob.glob(f"{IAMGE_path}/*.jpg")
    files.sort()

    ## 以下循环内容与onnx推理完全一致
    for ss, IMG_PATH in enumerate(files):
        basename = os.path.basename(IMG_PATH)

        if ss<16:continue
        print(ss, IMG_PATH)

        ###=====================================
        image_or = cv2.imread(IMG_PATH)
        boxes_DETECTOUT = DETECT.run(image_or)

        ## step2. 这里利用nms仅仅去除normal被重叠的框，其他的类别不去除。该部分移除代码能正常跑通==============
        ## 仅对障碍物做分类的处理和更多的处理
        mask1 = boxes_DETECTOUT[:,0]<15
        mask2 = boxes_DETECTOUT[:,0]==NAME2ID["normal"]
        mask = mask1+mask2
        boxes_FURNITURE = boxes_DETECTOUT[~mask]  
        boxes_OBSTACLE = boxes_DETECTOUT[mask]  

        boxes_nms = boxes_OBSTACLE.copy()
        boxes_nms[:, 1:] = postdecoder.xywhn2xyxy(boxes_nms[:, 1:], w=image_or.shape[1], h=image_or.shape[0])
        _, keep = nms_special(boxes_nms, 0.5, NAME2ID["normal"])
        boxes_OBSTACLE = boxes_OBSTACLE[keep]

        ## step3. 进行分类模型的推理，以及后处理的完成=================================================
        boxes_CLASSOUT = np.zeros((boxes_OBSTACLE.shape[0], 8)) ## xywh cls conf cls conf
        boxes_POSTOUT = np.zeros((boxes_OBSTACLE.shape[0], 6))
        if boxes_CLASSOUT.shape[0]!=0: 

            boxes_CLASSOUT[:, 0:6] = boxes_OBSTACLE[:,[1,2,3,4, 0,5]]  ## xywh cls conf
            boxes_xyxy = postdecoder.xywhn2xyxy(boxes_CLASSOUT[:, 0:4], w=image_or.shape[1], h=image_or.shape[0]).astype(int)

            for i, B in enumerate(boxes_xyxy):
                image_cut = image_or[B[1]:B[3], B[0]:B[2]]
                cls, conf = CLASS.run(image_cut)
                boxes_CLASSOUT[i, [6,7]] = [cls, conf]

                ## 保存用于class量化的数据
                # cv2.imwrite(os.path.join(Q_CLASS_path, basename+f"_{i}.jpg"), image_cut)
                # cv2.imwrite("test_cut.png", image_cut)

            boxes_POSTOUT = post_process_V3_class(boxes_CLASSOUT.copy(), [], "class")
            boxes_POSTOUT[boxes_POSTOUT[:,0]==NAME2ID["normal"],0] = NAME2ID["else"]

        # boxes_POSTOUT = np.concatenate((boxes_POSTOUT, boxes_FURNITURE), axis=0)
        
        # sub_path = os.path.basename(os.path.dirname(IMG_PATH))
        sub_path = os.path.dirname(IMG_PATH).split("/")[-LEVEL] 
        savepath_detect = makedir(os.path.join(RESULT_path, "a1_BOX", sub_path))
        savepath_class = makedir(os.path.join(RESULT_path, "a2_CLASS", sub_path))
        savepath_post = makedir(os.path.join(RESULT_path, "a3_POST", sub_path))
        np.savetxt(os.path.join(savepath_detect, basename.replace(".jpg", ".txt")), boxes_DETECTOUT)          
        np.savetxt(os.path.join(savepath_class, basename.replace(".jpg", ".txt")), boxes_CLASSOUT)          
        np.savetxt(os.path.join(savepath_post,   basename.replace(".jpg", ".txt")), boxes_POSTOUT)          
        # input()
        # continue

        if SHOW:
            ## 【不影响推理】结果可视化
            # image_show = draw(image_or, boxes_DETECTOUT, CLASSES, "box", ss)
            # cv2.imwrite(os.path.join(savepath_detect, basename), image_show)
            # cv2.imwrite("test_detect.png", image_show)

            ## 【不影响推理】结果可视化
            image_show = draw(image_or, boxes_CLASSOUT, CLASSES, "class", ss)
            image_show = draw(image_show, boxes_POSTOUT, CLASSES, "post", ss)
            cv2.imwrite(os.path.join(savepath_post, basename), image_show)
            # cv2.imwrite("test_class.png", image_show)           

        # print(boxes_CLASSOUT[:,4:])
        # print(boxes_POSTOUT)
        # print()
        # input()



                

            


