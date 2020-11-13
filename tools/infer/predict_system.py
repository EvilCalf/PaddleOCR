# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import copy
import json
import math
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image

os.environ['KMP_DUPLICATE_LIB_OK'] = "True"
__dir__ = os.path.dirname(os.path.abspath(__file__))
sys.path.append(__dir__)
sys.path.append(os.path.abspath(os.path.join(__dir__, '../..')))
import tools.infer.predict_cls as predict_cls
import tools.infer.predict_det as predict_det
import tools.infer.predict_rec as predict_rec
import tools.infer.utility as utility
from ppocr.utils.utility import (check_and_read_gif, get_image_file_list,
                                 initial_logger)
from tools.infer.utility import draw_ocr, draw_ocr_box_txt

logger = initial_logger()


class TextSystem(object):
    def __init__(self, args):
        self.text_detector = predict_det.TextDetector(args)
        self.text_recognizer = predict_rec.TextRecognizer(args)
        self.use_angle_cls = args.use_angle_cls
        if self.use_angle_cls:
            self.text_classifier = predict_cls.TextClassifier(args)

    def get_rotate_crop_image(self, img, points):
        '''
        img_height, img_width = img.shape[0:2]
        left = int(np.min(points[:, 0]))
        right = int(np.max(points[:, 0]))
        top = int(np.min(points[:, 1]))
        bottom = int(np.max(points[:, 1]))
        img_crop = img[top:bottom, left:right, :].copy()
        points[:, 0] = points[:, 0] - left
        points[:, 1] = points[:, 1] - top
        '''
        img_crop_width = int(
            max(
                np.linalg.norm(points[0] - points[1]),
                np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(
            max(
                np.linalg.norm(points[0] - points[3]),
                np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0],
                              [img_crop_width, img_crop_height],
                              [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(
            img,
            M, (img_crop_width, img_crop_height),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC)
        # dst_img_height, dst_img_width = dst_img.shape[0:2]
        # if dst_img_height * 1.0 / dst_img_width >= 1.5:
        #     dst_img = np.rot90(dst_img)
        return dst_img

    def print_draw_crop_rec_res(self, img_crop_list, rec_res):
        bbox_num = len(img_crop_list)
        for bno in range(bbox_num):
            cv2.imwrite("./output/img_crop_%d.jpg" % bno, img_crop_list[bno])
            print(bno, rec_res[bno])

    def __call__(self, img):
        ori_im = img.copy()
        dt_boxes, elapse = self.text_detector(img)
        print("dt_boxes num : {}, elapse : {}".format(len(dt_boxes), elapse))
        if dt_boxes is None:
            return None, None
        img_crop_list = []

        dt_boxes = sorted_boxes(dt_boxes)

        for bno in range(len(dt_boxes)):
            tmp_box = copy.deepcopy(dt_boxes[bno])
            img_crop = self.get_rotate_crop_image(ori_im, tmp_box)
            img_crop_list.append(img_crop)
        if self.use_angle_cls:
            img_crop_list, angle_list, elapse = self.text_classifier(
                img_crop_list)
            print("cls num  : {}, elapse : {}".format(
                len(img_crop_list), elapse))
        rec_res, elapse = self.text_recognizer(img_crop_list)
        print("rec_res num  : {}, elapse : {}".format(len(rec_res), elapse))
        # self.print_draw_crop_rec_res(img_crop_list, rec_res)
        return dt_boxes, rec_res


def sorted_boxes(dt_boxes):
    """
    Sort text boxes in order from top to bottom, left to right
    args:
        dt_boxes(array):detected text boxes with shape [4, 2]
    return:
        sorted boxes(array) with shape [4, 2]
    """
    num_boxes = dt_boxes.shape[0]
    sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
    _boxes = list(sorted_boxes)

    for i in range(num_boxes - 1):
        if abs(_boxes[i + 1][0][1] - _boxes[i][0][1]) < 10 and \
                (_boxes[i + 1][0][0] < _boxes[i][0][0]):
            tmp = _boxes[i]
            _boxes[i] = _boxes[i + 1]
            _boxes[i + 1] = tmp
    return _boxes

def main(args):
    for root, dirs, files in os.walk(args.image_dir):
        for file in files:
            with open(root+"/"+file, "r") as f:
                imgpath = root+"/"+file
                image_file_list = get_image_file_list(imgpath)
                text_sys = TextSystem(args)
                is_visualize = True
                font_path = args.vis_font_path
                for image_file in image_file_list:
                    img, flag = check_and_read_gif(image_file)
                    if not flag:
                        img = cv2.imread(image_file)
                    if img is None:
                        logger.info("error in loading image:{}".format(image_file))
                        continue
                    starttime = time.time()
                    # img_gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
                    # img_bilater = cv2.bilateralFilter(img_gray, 5, 75, 75)
                    # img_bilater=cv2.cvtColor(img_bilater,cv2.COLOR_GRAY2BGR)
                    dt_boxes, rec_res = text_sys(img)
                    roi=()
                    name_box=np.empty(shape=(4,2))
                    for i, val in enumerate(rec_res):
                        if "姓名" in val[0]:
                            if len(val[0])<4:
                                name_box=dt_boxes[i+1]
                                rec_res.pop(i+1)
                                dt_boxes.pop(i+1)
                            else:
                                name_box=dt_boxes[i]
                                rec_res.pop(i)
                                dt_boxes.pop(i)
                            continue
                        if "名" in val[0]:
                            if len(val[0])<=2:
                                name_box=dt_boxes[i+1]
                                rec_res.pop(i+1)
                                dt_boxes.pop(i+1)
                            elif len(val[0])<=6:
                                name_box=dt_boxes[i]
                                rec_res.pop(i)
                                dt_boxes.pop(i)
                            continue   
                    roi=(int(name_box[0][0]),int(name_box[0][1]),int(name_box[2][0]),int(name_box[2][1]))                                                                     
                    elapse = time.time() - starttime
                    print("Predict time of %s: %.3fs" % (image_file, elapse))
            
                    drop_score = 0.5

                    json_img_save="./inference_results_json/"+root.replace(args.image_dir+"\\","")
                    if not os.path.exists(json_img_save):
                        os.makedirs(json_img_save)
                    with open(json_img_save+"/"+file.replace(".jpg", "")+".json", 'w', encoding='utf-8') as file_obj:
                        ans_json = {'data': [{'str': i[0]}
                                             for i in rec_res]}
                        json.dump(ans_json, file_obj, indent=4, ensure_ascii=False)
                    
                    if is_visualize:
                        image = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                        boxes = dt_boxes
                        txts = [rec_res[i][0] for i in range(len(rec_res))]
                        scores = [rec_res[i][1] for i in range(len(rec_res))]
            
                        draw_img = draw_ocr_box_txt(
                            image,
                            boxes,
                            txts,
                            scores,
                            drop_score=drop_score,
                            font_path=font_path)
                        draw_img.paste((0,0,0),roi)
                        draw_img=np.array(draw_img)
                        draw_img_save = "./inference_results/"+root.replace(args.image_dir+"\\","")
                        if not os.path.exists(draw_img_save):
                            os.makedirs(draw_img_save)
                        cv2.imwrite(
                            os.path.join(draw_img_save, os.path.basename(image_file)),
                            draw_img[:, :, ::-1])
                        print("The visualized image saved in {}".format(
                            os.path.join(draw_img_save, os.path.basename(image_file))))


if __name__ == "__main__":
    main(utility.parse_args())   
